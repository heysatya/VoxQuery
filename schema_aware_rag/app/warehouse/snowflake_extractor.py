"""
snowflake_extractor.py
───────────────────────
High-level schema extraction for Snowflake.
Builds enriched TableMetadata from raw Snowflake metadata.

Snowflake-specific enrichments:
- Table COMMENTs (business descriptions already written by data team)
- Column-level tags (PII flags, domain tags)
- Clustering keys (indicates important dimensions)
- Query history mining (real usage patterns)
- Storage metrics (row counts without expensive COUNT(*))
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from app.metadata.models import (
    ColumnMetadata,
    TableMetadata,
)
from app.warehouse.base import RawTableInfo
from app.warehouse.snowflake_connector import SnowflakeConnector

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────
# Domain Mapping
# ─────────────────────────────────────────────────────────────────────

DOMAIN_MAP: dict[str, list[str]] = {
    "sales": ["order", "sale", "revenue", "transaction", "invoice"],
    "customers": ["customer", "client", "buyer", "user", "account"],
    "products": ["product", "item", "sku", "catalog", "inventory"],
    "marketing": ["campaign", "marketing", "promo", "lead", "funnel"],
    "finance": ["finance", "budget", "cost", "expense", "payment"],
    "operations": ["shipping", "delivery", "warehouse", "fulfillment"],
    "analytics": ["dim_", "fct_", "agg_", "mart_", "rpt_"],
}


class SnowflakeSchemaExtractor:
    """
    Extracts and enriches Snowflake schema for RAG indexing.

    Key enrichments over base extraction:
    1. Uses Snowflake COMMENT as table/column descriptions (free metadata!)
    2. Maps Snowflake tags to PII flags and domains
    3. Uses INFORMATION_SCHEMA row counts (no table scan)
    4. Detects clustering keys as important dimension columns
    5. Mines query history for usage patterns

    Usage:
        connector = SnowflakeConnector()
        extractor = SnowflakeSchemaExtractor(connector)
        tables = extractor.extract_all_enriched()
    """

    def __init__(
        self,
        connector: SnowflakeConnector,
        include_views: bool = True,
        sample_rows: int = 5,
    ):
        self.connector = connector
        self.include_views = include_views
        self.sample_rows = sample_rows

    def extract_all_enriched(
        self,
        excluded_schemas: Optional[list[str]] = None,
    ) -> list[TableMetadata]:
        """
        Extract all tables and return enriched TableMetadata.

        Args:
            excluded_schemas: Schemas to skip

        Returns:
            List of fully enriched TableMetadata objects
        """
        excluded = set(
            excluded_schemas or self.connector.config.excluded_schemas)
        table_list = self.connector.list_tables(
            include_views=self.include_views
        )

        enriched_tables = []
        for t in table_list:
            if t["schema_name"].upper() in excluded:
                continue

            try:
                enriched = self._extract_enriched_table(
                    schema_name=t["schema_name"],
                    table_name=t["table_name"],
                    table_type=t.get("table_type", "TABLE"),
                )
                enriched_tables.append(enriched)
                logger.info(
                    "Extracted: %s.%s (%d cols, %s rows, domain=%s)",
                    t["schema_name"], t["table_name"],
                    len(enriched.columns),
                    f"{enriched.row_count:,}" if enriched.row_count else "?",
                    enriched.domain,
                )
            except Exception as e:
                logger.error(
                    "Failed to extract %s.%s: %s",
                    t["schema_name"], t["table_name"], e
                )

        logger.info(
            "Snowflake extraction complete: %d tables",
            len(enriched_tables)
        )
        return enriched_tables

    def _extract_enriched_table(
        self,
        schema_name: str,
        table_name: str,
        table_type: str,
    ) -> TableMetadata:
        """Extract and enrich a single table."""

        # ── Raw data ──────────────────────────────────────────────
        raw_columns = self.connector.extract_columns(schema_name, table_name)
        table_comment = self.connector.get_table_comment(
            schema_name, table_name)
        storage_metrics = self.connector.get_table_storage_metrics(
            schema_name, table_name)
        tags = self.connector.get_tags(schema_name, table_name)
        sample_rows = self.connector.get_sample_rows(
            schema_name, table_name, limit=self.sample_rows
        )

        # ── Determine row count (from storage metrics first) ──────
        row_count = storage_metrics.get("row_count")
        if row_count is None:
            row_count = self.connector.get_row_count(schema_name, table_name)

        # ── Parse clustering key ──────────────────────────────────
        cluster_key = storage_metrics.get("clustering_key", "")
        cluster_columns = self._parse_cluster_key(cluster_key)

        # ── Infer domain ──────────────────────────────────────────
        domain = self._infer_domain(schema_name, table_name, tags)

        # ── Build enriched columns ────────────────────────────────
        enriched_columns = []
        for col in raw_columns:
            is_pii = self._detect_pii(col.column_name, col.data_type, tags)
            is_pk = col.column_name.lower() in {
                "id", "pk"} or col.is_primary_key
            is_metric = self._is_likely_metric(col.column_name, col.data_type)
            is_date = self._is_likely_date(col.column_name, col.data_type)
            is_dim = col.column_name in cluster_columns

            enriched_columns.append(
                ColumnMetadata(
                    name=col.column_name,
                    data_type=col.data_type,
                    nullable=col.is_nullable,
                    ordinal_position=col.ordinal_position,
                    default_value=col.column_default,
                    description=col.comment or "",
                    is_pii=is_pii,
                    is_primary_key=is_pk,
                    is_likely_metric=is_metric,
                    is_likely_date=is_date,
                    is_likely_dimension=is_dim,
                )
            )

        # ── Build TableMetadata ───────────────────────────────────
        synonyms = self._infer_synonyms(table_name)

        return TableMetadata(
            schema_name=schema_name,
            table_name=table_name,
            table_type=table_type,
            description=table_comment,
            domain=domain,
            synonyms=synonyms,
            row_count=int(row_count) if row_count else None,
            columns=enriched_columns,
            sample_rows=sample_rows[:3],
            tags=list(tags.keys()),
        )

    def _parse_cluster_key(self, cluster_key: str) -> set[str]:
        """Parse Snowflake clustering key string into column names."""
        if not cluster_key:
            return set()
        # Cluster key format: "LINEAR(col1, col2)"
        import re
        cols = re.findall(r'[A-Za-z_][A-Za-z0-9_]*', cluster_key)
        return {c.upper() for c in cols if c.upper() != "LINEAR"}

    def _infer_domain(
        self,
        schema_name: str,
        table_name: str,
        tags: dict[str, str],
    ) -> str:
        """Infer business domain from name patterns and tags."""
        # Check tags first (authoritative)
        if "DOMAIN" in tags:
            return tags["DOMAIN"].lower()

        name = (schema_name + "_" + table_name).lower()
        for domain, patterns in DOMAIN_MAP.items():
            if any(p in name for p in patterns):
                return domain

        return "general"

    def _detect_pii(
        self,
        column_name: str,
        data_type: str,
        tags: dict[str, str],
    ) -> bool:
        """Detect PII via tags or column name patterns."""
        # Snowflake tag-based detection (authoritative)
        if tags.get("PII", "").upper() in ("TRUE", "YES", "1"):
            return True

        pii_patterns = {
            "email", "phone", "ssn", "social_security", "dob",
            "birth_date", "passport", "credit_card", "cvv",
            "address", "ip_address", "device_id",
        }
        name_lower = column_name.lower()
        return any(p in name_lower for p in pii_patterns)

    def _is_likely_metric(self, column_name: str, data_type: str) -> bool:
        """Detect numeric metric columns."""
        metric_types = {"NUMBER", "FLOAT", "DECIMAL", "NUMERIC", "INTEGER"}
        metric_words = {"total", "amount", "revenue", "count", "qty",
                        "quantity", "price", "cost", "value", "sum", "sales"}
        name_lower = column_name.lower()
        is_numeric = any(t in data_type.upper() for t in metric_types)
        has_metric_word = any(w in name_lower for w in metric_words)
        return is_numeric and has_metric_word

    def _is_likely_date(self, column_name: str, data_type: str) -> bool:
        """Detect date/timestamp columns."""
        date_types = {"DATE", "TIMESTAMP", "TIMESTAMP_NTZ",
                      "TIMESTAMP_LTZ", "TIMESTAMP_TZ"}
        return any(t in data_type.upper() for t in date_types)

    def _infer_synonyms(self, table_name: str) -> list[str]:
        """Generate synonyms from table naming conventions."""
        name = table_name.lower()
        synonyms = []

        # Remove common prefixes
        for prefix in ["fct_", "dim_", "stg_", "rpt_", "agg_", "mart_"]:
            if name.startswith(prefix):
                synonyms.append(name.replace(prefix, "").replace("_", " "))

        # Add plural/singular variants
        if not name.endswith("s"):
            synonyms.append(name.replace("_", " ") + "s")

        return list(set(synonyms))
