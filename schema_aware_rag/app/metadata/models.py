"""
models.py
──────────
Pydantic models for all metadata objects in the RAG layer.

Design decisions:
- Strict typing throughout (Pydantic v2 strict mode where needed)
- RagChunk is the universal retrieval unit
- RetrievedChunk wraps RagChunk with retrieval scores
- ContextBundle is the final output to the SQL generator
- All models are serializable to/from JSON for persistence
"""

from __future__ import annotations

import uuid
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


# ─────────────────────────────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────────────────────────────


class ChunkType(str, Enum):
    """Supported chunk types for the RAG knowledge base."""
    TABLE_CARD = "table_card"
    METRIC_CARD = "metric_card"
    QUERY_EXAMPLE = "query_example"
    BUSINESS_RULE = "business_rule"
    JOIN_PATH = "join_path"


class EmbeddingProvider(str, Enum):
    """Supported embedding providers."""
    OPENAI = "openai"
    LOCAL = "local"


# ─────────────────────────────────────────────────────────────────────
# Column & Table Metadata
# ─────────────────────────────────────────────────────────────────────


class ColumnMetadata(BaseModel):
    """Metadata for a single database column."""
    name: str
    data_type: str
    nullable: bool = True
    ordinal_position: int = 0
    default_value: Optional[str] = None

    # Enriched fields (from sampler or LLM)
    description: Optional[str] = None
    synonyms: list[str] = Field(default_factory=list)
    is_pii: bool = False
    is_primary_key: bool = False
    is_foreign_key: bool = False
    references_table: Optional[str] = None
    references_column: Optional[str] = None

    # Statistics
    approx_distinct: Optional[int] = None
    null_percentage: Optional[float] = None
    min_value: Optional[str] = None
    max_value: Optional[str] = None
    sample_values: list[Any] = Field(default_factory=list)

    # Classification hints
    is_likely_metric: bool = False
    is_likely_date: bool = False
    is_likely_dimension: bool = False

    def to_schema_line(self) -> str:
        """Format column as a single-line schema description."""
        parts = [f"{self.name} ({self.data_type})"]
        if self.description:
            parts.append(f"— {self.description}")
        if self.synonyms:
            parts.append(f"[also: {', '.join(self.synonyms)}]")
        return " ".join(parts)


class TableMetadata(BaseModel):
    """Complete metadata for a database table."""
    schema_name: str
    table_name: str
    table_type: str = "BASE TABLE"           # BASE TABLE or VIEW

    # Descriptive
    description: Optional[str] = None
    domain: Optional[str] = None            # sales, finance, product
    synonyms: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)

    # Statistics
    row_count: Optional[int] = None

    # Schema
    columns: list[ColumnMetadata] = Field(default_factory=list)
    sample_rows: list[dict[str, Any]] = Field(default_factory=list)

    @property
    def full_name(self) -> str:
        """Fully qualified table name."""
        return f"{self.schema_name}.{self.table_name}"

    @property
    def column_names(self) -> list[str]:
        """List of column names."""
        return [col.name for col in self.columns]

    def get_column(self, name: str) -> Optional[ColumnMetadata]:
        """Find a column by name (case-insensitive)."""
        name_lower = name.lower()
        return next(
            (col for col in self.columns if col.name.lower() == name_lower),
            None,
        )

    def to_schema_text(self) -> str:
        """
        Render table as human-readable schema text for embedding.

        Example output:
            Table: main.orders
            Description: Order-level fact table for completed transactions.
            Columns:
            - order_id (INTEGER) — Unique order identifier
            - order_date (DATE) — Date the order was placed
            ...
        """
        lines = [
            f"Table: {self.full_name}",
        ]

        if self.description:
            lines.append(f"Description: {self.description}")

        if self.domain:
            lines.append(f"Domain: {self.domain}")

        if self.row_count is not None:
            lines.append(f"Row count: {self.row_count:,}")

        if self.synonyms:
            lines.append(f"Synonyms: {', '.join(self.synonyms)}")

        lines.append("Columns:")
        for col in self.columns:
            if not col.is_pii:
                lines.append(f"  - {col.to_schema_line()}")

        if self.sample_rows:
            lines.append(f"Sample rows (first {len(self.sample_rows)}):")
            for row in self.sample_rows[:3]:
                # Mask PII columns
                safe_row = {
                    k: v
                    for k, v in row.items()
                    if not any(
                        col.name == k and col.is_pii
                        for col in self.columns
                    )
                }
                lines.append(f"  {safe_row}")

        return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────
# Metric Registry
# ─────────────────────────────────────────────────────────────────────


class MetricDefinition(BaseModel):
    """Definition of a certified business metric."""
    name: str
    display_name: str
    description: str

    formula: str                             # SQL expression
    source_table: str
    additional_tables: list[str] = Field(default_factory=list)

    synonyms: list[str] = Field(default_factory=list)
    related_metrics: list[str] = Field(default_factory=list)
    default_dimensions: list[str] = Field(default_factory=list)
    default_grain: str = "day"              # day, week, month, quarter, year

    certified: bool = False
    owner: Optional[str] = None
    format: Optional[str] = None           # currency, percentage, number

    @property
    def all_names(self) -> list[str]:
        """All known names for this metric (for matching)."""
        return [self.name, self.display_name] + self.synonyms

    def to_metric_text(self) -> str:
        """
        Render metric as human-readable text for embedding.

        Example output:
            Metric: Revenue [CERTIFIED]
            Description: Total net sales revenue from completed orders.
            Formula: SUM(order_total - COALESCE(discount_amount, 0))
            Source: main.orders
            Synonyms: sales, net sales, topline
            Dimensions: region, order_date, product_category
        """
        lines = [
            f"Metric: {self.display_name}"
            + (" [CERTIFIED]" if self.certified else ""),
            f"Name: {self.name}",
            f"Description: {self.description}",
            f"Formula: {self.formula}",
            f"Source table: {self.source_table}",
        ]

        if self.synonyms:
            lines.append(f"Synonyms: {', '.join(self.synonyms)}")

        if self.default_dimensions:
            lines.append(
                f"Default dimensions: {', '.join(self.default_dimensions)}"
            )

        if self.format:
            lines.append(f"Format: {self.format}")

        return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────
# Sample Queries
# ─────────────────────────────────────────────────────────────────────


class SampleQuery(BaseModel):
    """A validated natural language → SQL example pair."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    natural_language: str
    paraphrases: list[str] = Field(default_factory=list)
    sql: str

    tables_used: list[str] = Field(default_factory=list)
    metrics_used: list[str] = Field(default_factory=list)
    dimensions_used: list[str] = Field(default_factory=list)

    domain: Optional[str] = None
    complexity: str = "simple"              # simple, medium, complex
    validated: bool = False

    def to_example_text(self) -> str:
        """Render as Q→SQL example for embedding."""
        lines = [
            f"Q: {self.natural_language}",
            f"SQL: {self.sql}",
        ]
        if self.tables_used:
            lines.append(f"Tables: {', '.join(self.tables_used)}")
        if self.metrics_used:
            lines.append(f"Metrics: {', '.join(self.metrics_used)}")
        return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────
# Business Rules
# ─────────────────────────────────────────────────────────────────────


class BusinessRule(BaseModel):
    """A business rule that affects SQL generation."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    description: str
    rule_text: str                          # Human-readable rule
    sql_pattern: Optional[str] = None      # SQL snippet that implements it
    applies_to_tables: list[str] = Field(default_factory=list)
    applies_to_metrics: list[str] = Field(default_factory=list)
    priority: int = 0                       # Higher = more important

    def to_rule_text(self) -> str:
        """Render rule for embedding."""
        lines = [
            f"Business Rule: {self.name}",
            f"Rule: {self.rule_text}",
        ]
        if self.sql_pattern:
            lines.append(f"SQL pattern: {self.sql_pattern}")
        if self.applies_to_tables:
            lines.append(
                f"Applies to tables: {', '.join(self.applies_to_tables)}")
        if self.applies_to_metrics:
            lines.append(
                f"Applies to metrics: {', '.join(self.applies_to_metrics)}")
        return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────
# RAG Chunks
# ─────────────────────────────────────────────────────────────────────


class ChunkMetadata(BaseModel):
    """Metadata attached to each RAG chunk for filtering and provenance."""
    schema: Optional[str] = None
    table: Optional[str] = None
    metric: Optional[str] = None
    domain: Optional[str] = None
    certified: bool = False
    source: str = "extracted"               # extracted, yaml, mined
    chunk_type: str = ""


class RagChunk(BaseModel):
    """
    Universal retrieval unit for the RAG knowledge base.
    Every piece of knowledge is stored as a RagChunk.
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    chunk_type: ChunkType
    text: str                               # Embedded text
    metadata: ChunkMetadata = Field(default_factory=ChunkMetadata)

    # Source object references
    source_table: Optional[str] = None
    source_metric: Optional[str] = None

    @field_validator("text")
    @classmethod
    def text_must_not_be_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Chunk text cannot be empty")
        return v.strip()

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for JSONL serialization."""
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RagChunk":
        """Reconstruct from JSONL dict."""
        return cls.model_validate(data)

    def __repr__(self) -> str:
        preview = self.text[:60].replace("\n", " ")
        return f"RagChunk(type={self.chunk_type.value}, text='{preview}...')"


# ─────────────────────────────────────────────────────────────────────
# Retrieval Results
# ─────────────────────────────────────────────────────────────────────


class RetrievedChunk(BaseModel):
    """A RagChunk with retrieval scores attached."""
    chunk: RagChunk
    score: float                            # Final relevance score (0-1)
    vector_score: Optional[float] = None   # Dense vector similarity
    bm25_score: Optional[float] = None     # BM25 keyword score
    rrf_score: Optional[float] = None      # Fused score
    source: str = "hybrid"                 # vector, bm25, hybrid


class ContextSection(BaseModel):
    """A section of the context bundle."""
    tables: list[str] = Field(default_factory=list)
    metrics: list[str] = Field(default_factory=list)
    examples: list[str] = Field(default_factory=list)
    business_rules: list[str] = Field(default_factory=list)


class ContextBundle(BaseModel):
    """
    Final output of the RAG layer, sent to the SQL generator.

    This is the contract between the RAG layer and downstream consumers.
    """
    context: ContextSection = Field(default_factory=ContextSection)
    total_tokens: int = 0
    chunks_used: list[dict[str, Any]] = Field(default_factory=list)

    def is_empty(self) -> bool:
        """True if no context was retrieved."""
        ctx = self.context
        return (
            not ctx.tables
            and not ctx.metrics
            and not ctx.examples
            and not ctx.business_rules
        )

    def to_prompt_string(self) -> str:
        """
        Render the context bundle as a single string for LLM injection.
        """
        sections = []

        if self.context.metrics:
            sections.append("=== METRIC DEFINITIONS ===")
            sections.extend(self.context.metrics)

        if self.context.tables:
            sections.append("=== TABLE SCHEMAS ===")
            sections.extend(self.context.tables)

        if self.context.examples:
            sections.append("=== SIMILAR QUERIES ===")
            sections.extend(self.context.examples)

        if self.context.business_rules:
            sections.append("=== BUSINESS RULES ===")
            sections.extend(self.context.business_rules)

        return "\n\n".join(sections)
