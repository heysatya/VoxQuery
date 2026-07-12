"""
hybrid_retriever.py
────────────────────
Hybrid retrieval combining FAISS dense search + BM25 keyword search.
Fuses results using Reciprocal Rank Fusion (RRF).

Design decisions:
- Parallel execution: vector + BM25 fire concurrently (asyncio)
- RRF fusion is parameter-free and robust (k=60 from paper)
- Metadata filtering applied post-retrieval for flexibility
- Returns typed RetrievedChunk objects with provenance scores
- Falls back to available index if one is unavailable
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional

from app.config import settings
from app.indexing.embedder import BaseEmbedder, create_embedder
from app.indexing.keyword_index import BM25Index
from app.indexing.vector_store import FAISSVectorStore
from app.metadata.models import ChunkType, RagChunk, RetrievedChunk
from app.retrieval.query_rewriter import QueryRewriter, RewrittenQuery

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────
# Retrieval Config
# ─────────────────────────────────────────────────────────────────────


@dataclass
class RetrievalConfig:
    """Configuration for a retrieval request."""
    top_k: int = 10
    vector_top_k_multiplier: int = 3    # fetch 3x from each source before fusion
    rrf_k: int = 60                     # RRF constant (from Cormack et al.)
    min_score: float = 0.0              # Minimum RRF score to include

    # Filters
    chunk_types: Optional[list[ChunkType]] = None
    domain_filter: Optional[str] = None
    certified_only: bool = False

    # Debug
    return_all_candidates: bool = False  # Include pre-fusion candidates


@dataclass
class RetrievalResult:
    """
    Complete result of a hybrid retrieval request.
    """
    query: str
    rewritten_query: RewrittenQuery
    chunks: list[RetrievedChunk]

    # Diagnostic info
    vector_candidates: int = 0
    bm25_candidates: int = 0
    fused_candidates: int = 0
    returned_chunks: int = 0

    latency_ms: float = 0.0
    vector_latency_ms: float = 0.0
    bm25_latency_ms: float = 0.0

    degraded_mode: bool = False
    degraded_reason: Optional[str] = None

    def log_summary(self) -> None:
        logger.info(
            "Retrieval: query='%s...' | vector=%d, bm25=%d, fused=%d, returned=%d | %.1fms",
            self.query[:40],
            self.vector_candidates,
            self.bm25_candidates,
            self.fused_candidates,
            self.returned_chunks,
            self.latency_ms,
        )


# ─────────────────────────────────────────────────────────────────────
# Hybrid Retriever
# ─────────────────────────────────────────────────────────────────────


class HybridRetriever:
    """
    Hybrid retrieval engine combining dense vector search + BM25 keyword search.

    Pipeline:
        1. Rewrite query (normalize + expand synonyms)
        2. Embed query (dense vector)
        3. Search FAISS index (semantic similarity)
        4. Search BM25 index (exact keyword matching)
        5. Fuse results using Reciprocal Rank Fusion
        6. Apply metadata filters
        7. Return top-K RetrievedChunks with scores

    Usage:
        retriever = HybridRetriever()
        retriever.load_indexes()

        result = retriever.retrieve("Northeast revenue last quarter", top_k=10)
        for chunk in result.chunks:
            print(chunk.score, chunk.chunk.chunk_type, chunk.chunk.text[:80])
    """

    def __init__(
        self,
        vector_store: Optional[FAISSVectorStore] = None,
        bm25_index: Optional[BM25Index] = None,
        embedder: Optional[BaseEmbedder] = None,
        query_rewriter: Optional[QueryRewriter] = None,
    ):
        """
        Initialize with optional pre-built components.
        Components are lazily loaded from disk if not provided.
        """
        self._vector_store = vector_store
        self._bm25_index = bm25_index
        self._embedder = embedder
        self._rewriter = query_rewriter or QueryRewriter()
        self._loaded = False

    # ── Initialization ────────────────────────────────────────────────

    def load_indexes(self) -> None:
        """
        Load FAISS and BM25 indexes from disk.
        Call this once at application startup.
        """
        if self._loaded:
            return

        # Load embedder
        if self._embedder is None:
            logger.info("Loading embedder...")
            self._embedder = create_embedder(use_cache=True)

        # Load FAISS vector store
        if self._vector_store is None:
            self._vector_store = FAISSVectorStore(
                dim=self._embedder.dimension
            )
            try:
                self._vector_store.load()
                logger.info(
                    "FAISS index loaded: %d vectors",
                    self._vector_store.num_chunks,
                )
            except FileNotFoundError as e:
                logger.error("FAISS index not found: %s", e)
                self._vector_store = None

        # Load BM25 index
        if self._bm25_index is None:
            self._bm25_index = BM25Index()
            try:
                self._bm25_index.load()
                logger.info(
                    "BM25 index loaded: %d chunks",
                    self._bm25_index.num_chunks,
                )
            except FileNotFoundError as e:
                logger.error("BM25 index not found: %s", e)
                self._bm25_index = None

        if self._vector_store is None and self._bm25_index is None:
            raise RuntimeError(
                "No indexes available. Run the indexing pipeline first: "
                "python -m app.indexing.index_pipeline --setup-schema"
            )

        self._loaded = True
        logger.info("HybridRetriever ready")

    # ── Main Retrieve Method ──────────────────────────────────────────

    def retrieve(
        self,
        query: str,
        top_k: Optional[int] = None,
        config: Optional[RetrievalConfig] = None,
    ) -> RetrievalResult:
        """
        Retrieve the most relevant chunks for a query.

        Args:
            query: User's natural language query
            top_k: Number of results to return (overrides config)
            config: Full retrieval configuration

        Returns:
            RetrievalResult with ranked chunks and diagnostic info
        """
        import time

        if not self._loaded:
            self.load_indexes()

        cfg = config or RetrievalConfig()
        if top_k is not None:
            cfg.top_k = top_k

        t_start = time.time()

        # Step 1: Rewrite query
        rewritten = self._rewriter.rewrite(query)
        retrieval_query = rewritten.get_retrieval_query()

        # Step 2: Determine fetch size for each index
        fetch_k = cfg.top_k * cfg.vector_top_k_multiplier

        # Step 3: Run both retrievers
        vector_results: list[RetrievedChunk] = []
        bm25_results: list[RetrievedChunk] = []
        degraded = False
        degraded_reason = None

        t_vec = time.time()
        if self._vector_store and not self._vector_store.is_empty:
            query_vector = self._embedder.embed_query(retrieval_query)
            vector_results = self._vector_store.search(
                query_vector, top_k=fetch_k
            )
        else:
            degraded = True
            degraded_reason = "Vector store unavailable"
        vec_latency = (time.time() - t_vec) * 1000

        t_bm25 = time.time()
        if self._bm25_index and not self._bm25_index.is_empty:
            bm25_results = self._bm25_index.search(
                retrieval_query, top_k=fetch_k
            )
        else:
            if degraded:
                degraded_reason = "Both vector and BM25 unavailable"
            else:
                degraded = True
                degraded_reason = "BM25 index unavailable"
        bm25_latency = (time.time() - t_bm25) * 1000

        # Step 4: Fuse with RRF
        fused = self._reciprocal_rank_fusion(
            results_lists=[vector_results, bm25_results],
            k=cfg.rrf_k,
        )

        # Step 5: Apply metadata filters
        filtered = self._apply_filters(fused, cfg)

        # Step 6: Trim to top_k
        final = filtered[: cfg.top_k]

        total_latency = (time.time() - t_start) * 1000

        result = RetrievalResult(
            query=query,
            rewritten_query=rewritten,
            chunks=final,
            vector_candidates=len(vector_results),
            bm25_candidates=len(bm25_results),
            fused_candidates=len(fused),
            returned_chunks=len(final),
            latency_ms=total_latency,
            vector_latency_ms=vec_latency,
            bm25_latency_ms=bm25_latency,
            degraded_mode=degraded,
            degraded_reason=degraded_reason,
        )

        result.log_summary()
        return result

    # ── RRF Fusion ────────────────────────────────────────────────────

    def _reciprocal_rank_fusion(
        self,
        results_lists: list[list[RetrievedChunk]],
        k: int = 60,
    ) -> list[RetrievedChunk]:
        """
        Fuse multiple ranked result lists using Reciprocal Rank Fusion.

        Formula: RRF(d) = Σ 1 / (k + rank_i(d))
        where rank_i(d) is the position of document d in list i.

        Reference: Cormack, Clarke & Buettcher (2009)

        Args:
            results_lists: Multiple ranked result lists
            k: RRF constant (60 is standard, robust to parameter changes)

        Returns:
            Merged and re-ranked list with RRF scores
        """
        # Accumulate RRF scores by chunk ID
        rrf_scores: dict[str, float] = {}
        chunk_map: dict[str, RetrievedChunk] = {}
        source_scores: dict[str, dict[str, float]] = {}

        for results in results_lists:
            for rank, retrieved in enumerate(results):
                chunk_id = retrieved.chunk.id
                rrf_contribution = 1.0 / (k + rank + 1)

                rrf_scores[chunk_id] = rrf_scores.get(
                    chunk_id, 0.0) + rrf_contribution
                chunk_map[chunk_id] = retrieved

                if chunk_id not in source_scores:
                    source_scores[chunk_id] = {}
                if retrieved.source == "vector":
                    source_scores[chunk_id]["vector_score"] = retrieved.vector_score
                elif retrieved.source == "bm25":
                    source_scores[chunk_id]["bm25_score"] = retrieved.bm25_score

        # Sort by RRF score (descending)
        sorted_ids = sorted(rrf_scores.keys(),
                            key=lambda cid: rrf_scores[cid], reverse=True)

        # Build fused result list
        fused: list[RetrievedChunk] = []
        for chunk_id in sorted_ids:
            original = chunk_map[chunk_id]
            scores = source_scores.get(chunk_id, {})

            fused.append(
                RetrievedChunk(
                    chunk=original.chunk,
                    score=rrf_scores[chunk_id],
                    rrf_score=rrf_scores[chunk_id],
                    vector_score=scores.get("vector_score"),
                    bm25_score=scores.get("bm25_score"),
                    source="hybrid",
                )
            )

        return fused

    # ── Metadata Filtering ────────────────────────────────────────────

    def _apply_filters(
        self,
        chunks: list[RetrievedChunk],
        config: RetrievalConfig,
    ) -> list[RetrievedChunk]:
        """
        Apply post-retrieval metadata filters.

        Filters are applied in order of specificity.
        """
        filtered = chunks

        # Filter by chunk type
        if config.chunk_types:
            filtered = [
                r for r in filtered
                if r.chunk.chunk_type in config.chunk_types
            ]

        # Filter by domain
        if config.domain_filter:
            filtered = [
                r for r in filtered
                if r.chunk.metadata.domain == config.domain_filter
                or r.chunk.metadata.domain is None  # Include domain-agnostic chunks
            ]

        # Filter to certified only
        if config.certified_only:
            filtered = [
                r for r in filtered
                if r.chunk.metadata.certified
            ]

        return filtered

    # ── Utility ───────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        """Return retriever statistics."""
        return {
            "loaded": self._loaded,
            "embedder": self._embedder.provider_name if self._embedder else None,
            "vector_store": (
                self._vector_store.get_stats()
                if self._vector_store else None
            ),
            "bm25_index": (
                self._bm25_index.get_stats()
                if self._bm25_index else None
            ),
        }
