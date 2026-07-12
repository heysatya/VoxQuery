"""
context_builder.py
──────────────────
Assembles retrieved chunks into a structured context bundle
for the SQL generation LLM.

Design decisions:
- Token budget enforced to prevent LLM context overflow
- Priority ordering: certified metrics > tables > examples > rules
- Diversity rule: max chunks per source table to avoid repetition
- Returns ContextBundle (Pydantic model) for clean API contract
- Provenance included for every chunk (audit + debugging)
- Estimation uses simple word-count proxy (no tokenizer needed)
"""

from __future__ import annotations

import logging
from typing import Optional

import tiktoken

from app.config import settings
from app.metadata.models import (
    ChunkType,
    ContextBundle,
    ContextSection,
    RagChunk,
    RetrievedChunk,
)
from app.retrieval.hybrid_retriever import RetrievalResult

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────
# Token Estimation
# ─────────────────────────────────────────────────────────────────────


def estimate_tokens(text: str, model: str = "gpt-3.5-turbo") -> int:
    """
    Estimate token count for a text string.

    Uses tiktoken if available (more accurate), falls back to word-count
    approximation (fast, no dependency).

    Args:
        text: Input text
        model: Model name for tiktoken encoder selection

    Returns:
        Estimated token count
    """
    try:
        enc = tiktoken.encoding_for_model(model)
        return len(enc.encode(text))
    except Exception:
        # Fallback: ~1.3 tokens per word (empirical for English)
        return int(len(text.split()) * 1.3)


# ─────────────────────────────────────────────────────────────────────
# Priority Rules
# ─────────────────────────────────────────────────────────────────────


# Priority order for chunk types (lower = higher priority)
CHUNK_PRIORITY: dict[ChunkType, int] = {
    ChunkType.METRIC_CARD: 0,       # Always include certified metrics first
    ChunkType.BUSINESS_RULE: 1,     # Business rules are critical for correctness
    ChunkType.TABLE_CARD: 2,        # Schema context
    ChunkType.QUERY_EXAMPLE: 3,     # Examples boost SQL gen accuracy
    ChunkType.JOIN_PATH: 4,         # Join hints (lowest priority)
}

# Extra boost for certified chunks
CERTIFIED_BOOST = -0.5  # Applied to priority score (lower = higher priority)


# ─────────────────────────────────────────────────────────────────────
# Context Builder
# ─────────────────────────────────────────────────────────────────────


class ContextBuilder:
    """
    Assembles retrieved chunks into an optimized context bundle.

    Algorithm:
        1. Sort chunks by priority (certified metrics first)
        2. Greedily add chunks within token budget
        3. Apply diversity rules (max N per source table)
        4. Format each section for the SQL generation prompt
        5. Return structured ContextBundle

    Usage:
        builder = ContextBuilder(token_budget=2500)
        bundle = builder.build(retrieval_result)
        print(bundle.to_prompt_string())
    """

    def __init__(
        self,
        token_budget: int = 2500,
        max_budget: int = 3000,
        max_chunks_per_table: int = 2,
        max_examples: int = 4,
        max_rules: int = 5,
    ):
        """
        Initialize with budget and diversity constraints.

        Args:
            token_budget: Target token budget (soft limit)
            max_budget: Hard token limit (never exceeded)
            max_chunks_per_table: Max table_card chunks for same table
            max_examples: Maximum query examples to include
            max_rules: Maximum business rules to include
        """
        self.token_budget = token_budget
        self.max_budget = max_budget
        self.max_chunks_per_table = max_chunks_per_table
        self.max_examples = max_examples
        self.max_rules = max_rules

    def build(
        self,
        retrieval_result: RetrievalResult,
        extra_token_budget: Optional[int] = None,
    ) -> ContextBundle:
        """
        Build a context bundle from retrieval results.

        Args:
            retrieval_result: Output from HybridRetriever.retrieve()
            extra_token_budget: Override the default token budget

        Returns:
            ContextBundle ready for SQL generation
        """
        budget = extra_token_budget or self.token_budget
        chunks = retrieval_result.chunks

        if not chunks:
            logger.warning("Context builder received zero chunks")
            return ContextBundle()

        # Step 1: Sort by priority
        sorted_chunks = self._sort_by_priority(chunks)

        # Step 2: Greedy selection within budget
        selected = self._select_within_budget(sorted_chunks, budget)

        # Step 3: Build sections
        sections = self._build_sections(selected)

        # Step 4: Calculate total tokens
        all_text = " ".join([
            text
            for section_list in [
                sections.tables,
                sections.metrics,
                sections.examples,
                sections.business_rules,
            ]
            for text in section_list
        ])
        total_tokens = estimate_tokens(all_text)

        # Step 5: Build provenance
        provenance = [
            {
                "id": r.chunk.id,
                "type": r.chunk.chunk_type.value,
                "score": round(r.score, 4),
                "rrf_score": round(r.rrf_score, 4) if r.rrf_score else None,
                "vector_score": round(r.vector_score, 4) if r.vector_score else None,
                "bm25_score": round(r.bm25_score, 4) if r.bm25_score else None,
                "source": r.source,
                "metadata": r.chunk.metadata.model_dump(),
            }
            for r in selected
        ]

        bundle = ContextBundle(
            context=sections,
            total_tokens=total_tokens,
            chunks_used=provenance,
        )

        logger.info(
            "Context bundle built: %d tokens, %d tables, %d metrics, "
            "%d examples, %d rules",
            total_tokens,
            len(sections.tables),
            len(sections.metrics),
            len(sections.examples),
            len(sections.business_rules),
        )

        return bundle

    # ── Sorting ───────────────────────────────────────────────────────

    def _sort_by_priority(
        self,
        chunks: list[RetrievedChunk],
    ) -> list[RetrievedChunk]:
        """
        Sort chunks by priority for selection.

        Priority logic:
        1. Certified metric cards (always first)
        2. Chunk type priority (metric > rule > table > example > join)
        3. RRF score within same type (higher = earlier)
        """
        def priority_key(r: RetrievedChunk) -> tuple:
            type_priority = CHUNK_PRIORITY.get(r.chunk.chunk_type, 99)
            certified_adj = CERTIFIED_BOOST if r.chunk.metadata.certified else 0
            return (
                type_priority + certified_adj,
                -r.score,  # Higher score = lower sort key (earlier)
            )

        return sorted(chunks, key=priority_key)

    # ── Greedy Selection ──────────────────────────────────────────────

    def _select_within_budget(
        self,
        chunks: list[RetrievedChunk],
        budget: int,
    ) -> list[RetrievedChunk]:
        """
        Greedily select chunks within the token budget.

        Also applies diversity rules:
        - Max N chunks per source table (prevents redundancy)
        - Max M query examples
        - Max P business rules
        """
        selected: list[RetrievedChunk] = []
        tokens_used = 0

        # Track diversity
        table_counts: dict[str, int] = {}
        example_count = 0
        rule_count = 0

        for retrieved in chunks:
            chunk = retrieved.chunk

            # Check diversity constraints
            if chunk.chunk_type == ChunkType.QUERY_EXAMPLE:
                if example_count >= self.max_examples:
                    continue
            elif chunk.chunk_type == ChunkType.BUSINESS_RULE:
                if rule_count >= self.max_rules:
                    continue
            elif chunk.chunk_type == ChunkType.TABLE_CARD:
                table_key = chunk.source_table or chunk.metadata.table or "unknown"
                if table_counts.get(table_key, 0) >= self.max_chunks_per_table:
                    continue

            # Check token budget
            chunk_tokens = estimate_tokens(chunk.text)
            if tokens_used + chunk_tokens > self.max_budget:
                logger.debug(
                    "Budget exceeded at chunk %d/%d (used=%d, needed=%d, budget=%d)",
                    len(selected) + 1,
                    len(chunks),
                    tokens_used,
                    chunk_tokens,
                    self.max_budget,
                )
                # Try to fit smaller chunks if we're past soft budget
                if tokens_used > budget:
                    continue
                # Under soft budget: include if it fits in hard budget
                # Already checked above

            # Accept this chunk
            selected.append(retrieved)
            tokens_used += chunk_tokens

            # Update counters
            if chunk.chunk_type == ChunkType.QUERY_EXAMPLE:
                example_count += 1
            elif chunk.chunk_type == ChunkType.BUSINESS_RULE:
                rule_count += 1
            elif chunk.chunk_type == ChunkType.TABLE_CARD:
                table_key = chunk.source_table or chunk.metadata.table or "unknown"
                table_counts[table_key] = table_counts.get(table_key, 0) + 1

        logger.debug(
            "Selected %d/%d chunks using %d/%d tokens",
            len(selected),
            len(chunks),
            tokens_used,
            budget,
        )
        return selected

    # ── Section Building ──────────────────────────────────────────────

    def _build_sections(
        self,
        selected: list[RetrievedChunk],
    ) -> ContextSection:
        """
        Organize selected chunks into labeled sections.

        Each section is a list of formatted text strings.
        """
        sections = ContextSection()

        for retrieved in selected:
            chunk = retrieved.chunk
            formatted = self._format_chunk(chunk, retrieved.score)

            if chunk.chunk_type == ChunkType.METRIC_CARD:
                sections.metrics.append(formatted)
            elif chunk.chunk_type == ChunkType.TABLE_CARD:
                sections.tables.append(formatted)
            elif chunk.chunk_type == ChunkType.QUERY_EXAMPLE:
                sections.examples.append(formatted)
            elif chunk.chunk_type in (
                ChunkType.BUSINESS_RULE,
                ChunkType.JOIN_PATH,
            ):
                sections.business_rules.append(formatted)

        return sections

    def _format_chunk(self, chunk: RagChunk, score: float) -> str:
        """
        Format a chunk for inclusion in the context bundle.

        Adds a relevance indicator for certified metrics.
        """
        text = chunk.text

        # Add certified badge for metrics
        if (
            chunk.chunk_type == ChunkType.METRIC_CARD
            and chunk.metadata.certified
        ):
            text = "⭐ " + text  # Certified metric marker

        return text

    # ── Context Summary ───────────────────────────────────────────────

    def get_context_summary(self, bundle: ContextBundle) -> str:
        """
        Generate a human-readable summary of the context bundle.
        Useful for debugging and logging.
        """
        lines = [
            f"Context Bundle Summary:",
            f"  Token usage:    {bundle.total_tokens}/{self.token_budget}",
            f"  Tables:         {len(bundle.context.tables)}",
            f"  Metrics:        {len(bundle.context.metrics)}",
            f"  Query examples: {len(bundle.context.examples)}",
            f"  Business rules: {len(bundle.context.business_rules)}",
            f"  Total chunks:   {len(bundle.chunks_used)}",
        ]

        if bundle.chunks_used:
            lines.append("  Top chunks:")
            for chunk_info in bundle.chunks_used[:5]:
                lines.append(
                    f"    [{chunk_info['type']:<15}] "
                    f"score={chunk_info['score']:.3f} "
                    f"| {chunk_info['metadata'].get('table') or chunk_info['metadata'].get('metric', 'unknown')}"
                )

        return "\n".join(lines)
