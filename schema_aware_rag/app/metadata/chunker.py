"""
chunker.py
──────────
Converts metadata objects into typed RagChunks for indexing.

Design decisions:
- One chunk per table (not per column) for retrieval precision
- One chunk per metric (with full formula + synonyms)
- Self-contained chunks (no cross-references needed to understand)
- Text format optimized for both embedding and BM25 matching
- PII columns excluded from chunk text
"""

from __future__ import annotations

import logging
import uuid
from typing import Optional

from app.metadata.models import (
    BusinessRule,
    ChunkMetadata,
    ChunkType,
    MetricDefinition,
    RagChunk,
    SampleQuery,
    TableMetadata,
)

logger = logging.getLogger(__name__)


class MetadataChunker:
    """
    Converts metadata objects into RagChunks for indexing.

    Usage:
        chunker = MetadataChunker()

        # Single objects
        chunk = chunker.table_to_chunk(table_metadata)
        chunk = chunker.metric_to_chunk(metric_definition)

        # Batch
        chunks = chunker.tables_to_chunks(all_tables)
        chunks = chunker.metrics_to_chunks(all_metrics)
    """

    def __init__(
        self,
        max_sample_rows: int = 3,
        max_columns_in_text: int = 30,
    ):
        self.max_sample_rows = max_sample_rows
        self.max_columns_in_text = max_columns_in_text

    # ── Table Cards ──────────────────────────────────────────────────

    def table_to_chunk(
        self,
        table: TableMetadata,
        extra_synonyms: Optional[list[str]] = None,
    ) -> RagChunk:
        """
        Convert a TableMetadata into a table_card chunk.

        The text is designed for:
        1. Semantic embedding (description, domain, synonyms)
        2. BM25 exact matching (table name, column names)
        3. SQL generation context (column types, sample values)

        Args:
            table: Table metadata object
            extra_synonyms: Additional synonyms to include

        Returns:
            RagChunk of type table_card
        """
        all_synonyms = (table.synonyms or []) + (extra_synonyms or [])

        # Build non-PII column list
        visible_columns = [
            col for col in table.columns if not col.is_pii
        ][:self.max_columns_in_text]

        # Format column lines
        column_lines = []
        for col in visible_columns:
            line = f"  - {col.name} ({col.data_type})"
            if col.description:
                line += f": {col.description}"
            if col.synonyms:
                line += f" [aka: {', '.join(col.synonyms)}]"
            if col.sample_values:
                samples = [str(v)
                           for v in col.sample_values[:3] if v is not None]
                if samples:
                    line += f" [e.g.: {', '.join(samples)}]"
            column_lines.append(line)

        # Format sample rows
        sample_section = ""
        if table.sample_rows and self.max_sample_rows > 0:
            safe_rows = []
            pii_col_names = {col.name for col in table.columns if col.is_pii}
            for row in table.sample_rows[:self.max_sample_rows]:
                safe_row = {
                    k: v for k, v in row.items()
                    if k not in pii_col_names
                }
                safe_rows.append(str(safe_row))
            if safe_rows:
                sample_section = "\nSample rows:\n" + "\n".join(
                    f"  {r}" for r in safe_rows
                )

        # Build the full chunk text
        text_parts = [
            f"Table: {table.full_name}",
        ]

        if table.description:
            text_parts.append(f"Description: {table.description}")

        if table.domain:
            text_parts.append(f"Domain: {table.domain}")

        if table.row_count is not None:
            text_parts.append(f"Row count: {table.row_count:,}")

        if all_synonyms:
            text_parts.append(f"Also known as: {', '.join(all_synonyms)}")

        text_parts.append(f"Columns:\n" + "\n".join(column_lines))

        if sample_section:
            text_parts.append(sample_section)

        text = "\n".join(text_parts)

        return RagChunk(
            id=str(uuid.uuid4()),
            chunk_type=ChunkType.TABLE_CARD,
            text=text,
            metadata=ChunkMetadata(
                schema=table.schema_name,
                table=table.full_name,
                domain=table.domain,
                certified=False,
                source="extracted",
                chunk_type=ChunkType.TABLE_CARD.value,
            ),
            source_table=table.full_name,
        )

    def tables_to_chunks(
        self,
        tables: list[TableMetadata],
    ) -> list[RagChunk]:
        """Convert a list of tables to chunks."""
        chunks = []
        for table in tables:
            try:
                chunk = self.table_to_chunk(table)
                chunks.append(chunk)
                logger.debug(
                    "Chunked table: %s (%d chars)",
                    table.full_name,
                    len(chunk.text),
                )
            except Exception as e:
                logger.error(
                    "Failed to chunk table %s: %s",
                    table.full_name,
                    e,
                )
        return chunks

    # ── Metric Cards ─────────────────────────────────────────────────

    def metric_to_chunk(self, metric: MetricDefinition) -> RagChunk:
        """
        Convert a MetricDefinition into a metric_card chunk.

        The text includes all synonyms to maximize BM25 recall
        for varied user phrasings.

        Args:
            metric: Metric definition from registry

        Returns:
            RagChunk of type metric_card
        """
        text = metric.to_metric_text()

        return RagChunk(
            id=str(uuid.uuid4()),
            chunk_type=ChunkType.METRIC_CARD,
            text=text,
            metadata=ChunkMetadata(
                table=metric.source_table,
                metric=metric.name,
                certified=metric.certified,
                source="yaml",
                chunk_type=ChunkType.METRIC_CARD.value,
            ),
            source_metric=metric.name,
        )

    def metrics_to_chunks(
        self,
        metrics: list[MetricDefinition],
    ) -> list[RagChunk]:
        """Convert a list of metrics to chunks."""
        chunks = []
        for metric in metrics:
            try:
                chunk = self.metric_to_chunk(metric)
                chunks.append(chunk)
                logger.debug("Chunked metric: %s", metric.name)
            except Exception as e:
                logger.error("Failed to chunk metric %s: %s", metric.name, e)
        return chunks

    # ── Sample Query Examples ─────────────────────────────────────────

    def sample_query_to_chunk(self, sample: SampleQuery) -> RagChunk:
        """
        Convert a SampleQuery into a query_example chunk.

        Args:
            sample: Validated Q→SQL pair

        Returns:
            RagChunk of type query_example
        """
        text = sample.to_example_text()

        # Include paraphrases for BM25 coverage
        if sample.paraphrases:
            text += "\nParaphrases: " + " | ".join(sample.paraphrases)

        return RagChunk(
            id=sample.id,
            chunk_type=ChunkType.QUERY_EXAMPLE,
            text=text,
            metadata=ChunkMetadata(
                domain=sample.domain,
                source="sample_queries",
                chunk_type=ChunkType.QUERY_EXAMPLE.value,
            ),
        )

    def sample_queries_to_chunks(
        self,
        samples: list[SampleQuery],
    ) -> list[RagChunk]:
        """Convert a list of sample queries to chunks."""
        chunks = []
        for sample in samples:
            try:
                chunk = self.sample_query_to_chunk(sample)
                chunks.append(chunk)
            except Exception as e:
                logger.error(
                    "Failed to chunk sample query '%s': %s",
                    sample.natural_language[:50],
                    e,
                )
        return chunks

    # ── Business Rules ────────────────────────────────────────────────

    def business_rule_to_chunk(self, rule: BusinessRule) -> RagChunk:
        """
        Convert a BusinessRule into a business_rule chunk.

        Args:
            rule: Business rule definition

        Returns:
            RagChunk of type business_rule
        """
        text = rule.to_rule_text()

        return RagChunk(
            id=rule.id,
            chunk_type=ChunkType.BUSINESS_RULE,
            text=text,
            metadata=ChunkMetadata(
                source="yaml",
                chunk_type=ChunkType.BUSINESS_RULE.value,
            ),
        )

    # ── Unified Batch Method ──────────────────────────────────────────

    def create_all_chunks(
        self,
        tables: list[TableMetadata],
        metrics: list[MetricDefinition],
        sample_queries: Optional[list[SampleQuery]] = None,
        business_rules: Optional[list[BusinessRule]] = None,
    ) -> list[RagChunk]:
        """
        Create all chunks from all metadata sources.

        Priority order matches retrieval priority:
        1. Metric cards (certified first)
        2. Table cards
        3. Sample queries
        4. Business rules

        Args:
            tables: Extracted table metadata
            metrics: Metric definitions from registry
            sample_queries: Optional Q→SQL examples
            business_rules: Optional business rules

        Returns:
            All chunks, ready for indexing
        """
        chunks: list[RagChunk] = []

        # 1. Metric cards (certified first)
        certified = [m for m in metrics if m.certified]
        non_certified = [m for m in metrics if not m.certified]
        chunks.extend(self.metrics_to_chunks(certified))
        chunks.extend(self.metrics_to_chunks(non_certified))

        # 2. Table cards
        chunks.extend(self.tables_to_chunks(tables))

        # 3. Sample queries
        if sample_queries:
            chunks.extend(self.sample_queries_to_chunks(sample_queries))

        # 4. Business rules
        if business_rules:
            for rule in business_rules:
                try:
                    chunks.append(self.business_rule_to_chunk(rule))
                except Exception as e:
                    logger.error("Failed to chunk rule '%s': %s", rule.name, e)

        logger.info(
            "Created %d total chunks: %d metric, %d table, %d example, %d rule",
            len(chunks),
            sum(1 for c in chunks if c.chunk_type == ChunkType.METRIC_CARD),
            sum(1 for c in chunks if c.chunk_type == ChunkType.TABLE_CARD),
            sum(1 for c in chunks if c.chunk_type == ChunkType.QUERY_EXAMPLE),
            sum(1 for c in chunks if c.chunk_type == ChunkType.BUSINESS_RULE),
        )

        return chunks
