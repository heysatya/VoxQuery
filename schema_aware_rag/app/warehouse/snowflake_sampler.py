"""
snowflake_sampler.py
─────────────────────
Advanced statistical sampling for Snowflake tables.

Uses Snowflake-native features:
- TABLESAMPLE BERNOULLI for large table sampling
- APPROX_COUNT_DISTINCT for cardinality estimation
- Snowflake column statistics view
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from app.warehouse.snowflake_connector import SnowflakeConnector

logger = logging.getLogger(__name__)


@dataclass
class SnowflakeColumnProfile:
    """Statistical profile for a Snowflake column."""
    column_name: str
    data_type: str
    null_pct: float = 0.0
    approx_distinct: Optional[int] = None
    min_value: Optional[str] = None
    max_value: Optional[str] = None
    sample_values: list[Any] = field(default_factory=list)
    is_likely_pk: bool = False
    is_likely_fk: bool = False
    is_likely_metric: bool = False
    is_likely_date: bool = False


@dataclass
class SnowflakeTableProfile:
    """Full statistical profile for a Snowflake table."""
    schema_name: str
    table_name: str
    row_count: int
    bytes_size: Optional[int] = None
    column_profiles: list[SnowflakeColumnProfile] = field(default_factory=list)
    sample_rows: list[dict[str, Any]] = field(default_factory=list)


class SnowflakeSampler:
    """
    Statistical sampler for Snowflake tables.

    Usage:
        sampler = SnowflakeSampler(connector)
        profile = sampler.profile_table("SALES_MART", "FCT_ORDERS")
    """

    METRIC_KEYWORDS = frozenset({
        "total", "amount", "revenue", "count", "quantity",
        "price", "cost", "value", "sum", "avg", "sales",
    })

    FK_KEYWORDS = frozenset({"_id", "_key", "_ref", "_fk", "_sk"})

    def __init__(self, connector: SnowflakeConnector):
        self.connector = connector

    def profile_table(
        self,
        schema_name: str,
        table_name: str,
        sample_pct: float = 10.0,
    ) -> SnowflakeTableProfile:
        """
        Create a full statistical profile of a Snowflake table.

        Args:
            schema_name: Schema containing the table
            table_name: Table to profile
            sample_pct: TABLESAMPLE percentage (1-100)

        Returns:
            SnowflakeTableProfile with column stats
        """
        # Row count from metadata (no scan)
        row_count = self.connector.get_row_count(schema_name, table_name) or 0

        # Get column names
        raw_cols = self.connector.extract_columns(schema_name, table_name)

        # Sample rows
        sample_rows = self._sample_rows(schema_name, table_name, sample_pct)

        # Profile each column
        col_profiles = []
        for col in raw_cols:
            profile = self._profile_column(
                schema_name=schema_name,
                table_name=table_name,
                column_name=col.column_name,
                data_type=col.data_type,
                row_count=row_count,
                sample_rows=sample_rows,
            )
            col_profiles.append(profile)

        return SnowflakeTableProfile(
            schema_name=schema_name,
            table_name=table_name,
            row_count=row_count,
            column_profiles=col_profiles,
            sample_rows=sample_rows,
        )

    def _sample_rows(
        self,
        schema_name: str,
        table_name: str,
        sample_pct: float,
    ) -> list[dict[str, Any]]:
        """Sample rows using Snowflake TABLESAMPLE BERNOULLI."""
        # Get column names for dict mapping
        raw_cols = self.connector.extract_columns(schema_name, table_name)
        col_names = [c.column_name for c in raw_cols]

        sql = f"""
        SELECT *
        FROM "{schema_name}"."{table_name}"
        TABLESAMPLE BERNOULLI ({sample_pct})
        LIMIT 5
        """
        try:
            rows = self.connector.execute(sql)
            return [
                {col_names[i]: val for i, val in enumerate(row)}
                for row in rows
            ]
        except Exception as e:
            logger.warning("Sampling failed for %s.%s: %s",
                           schema_name, table_name, e)
            return []

    def _profile_column(
        self,
        schema_name: str,
        table_name: str,
        column_name: str,
        data_type: str,
        row_count: int,
        sample_rows: list[dict],
    ) -> SnowflakeColumnProfile:
        """Profile a single Snowflake column."""

        profile = SnowflakeColumnProfile(
            column_name=column_name,
            data_type=data_type,
        )

        # Sample values from already-fetched rows
        profile.sample_values = [
            row.get(column_name)
            for row in sample_rows
            if row.get(column_name) is not None
        ][:5]

        if row_count > 0:
            try:
                # Approximate distinct count (Snowflake HyperLogLog)
                sql = f"""
                SELECT
                    APPROX_COUNT_DISTINCT("{column_name}") AS distinct_ct,
                    SUM(CASE WHEN "{column_name}" IS NULL THEN 1 ELSE 0 END)
                        / COUNT(*) * 100.0 AS null_pct
                FROM "{schema_name}"."{table_name}"
                """
                rows = self.connector.execute(sql)
                if rows:
                    profile.approx_distinct = int(rows[0][0] or 0)
                    profile.null_pct = float(rows[0][1] or 0.0)
            except Exception:
                pass

            # Min/max for numeric and date types
            numeric_keywords = {"NUMBER", "FLOAT", "DECIMAL", "INT"}
            date_keywords = {"DATE", "TIMESTAMP"}
            type_upper = data_type.upper()

            if any(k in type_upper for k in numeric_keywords | date_keywords):
                try:
                    sql = f"""
                    SELECT
                        MIN("{column_name}"),
                        MAX("{column_name}")
                    FROM "{schema_name}"."{table_name}"
                    """
                    rows = self.connector.execute(sql)
                    if rows:
                        profile.min_value = (
                            str(rows[0][0]) if rows[0][0] is not None else None
                        )
                        profile.max_value = (
                            str(rows[0][1]) if rows[0][1] is not None else None
                        )
                except Exception:
                    pass

        # Heuristic classification
        col_lower = column_name.lower()
        profile.is_likely_pk = (
            col_lower == "id"
            or col_lower == f"{schema_name.lower()}_id"
            or (profile.approx_distinct == row_count and "id" in col_lower)
        )
        profile.is_likely_fk = any(
            col_lower.endswith(kw) for kw in self.FK_KEYWORDS
        ) and not profile.is_likely_pk
        profile.is_likely_metric = any(
            kw in col_lower for kw in self.METRIC_KEYWORDS
        )
        profile.is_likely_date = any(
            t in data_type.upper() for t in {"DATE", "TIMESTAMP"}
        )

        return profile

    def get_column_distinct_values(
        self,
        schema_name: str,
        table_name: str,
        column_name: str,
        max_cardinality: int = 50,
        limit: int = 20,
    ) -> list[Any]:
        """
        Return distinct values for low-cardinality columns.
        Useful for categorical columns like STATUS, REGION, TYPE.
        """
        try:
            sql = f"""
            SELECT DISTINCT "{column_name}"
            FROM "{schema_name}"."{table_name}"
            WHERE "{column_name}" IS NOT NULL
            ORDER BY "{column_name}"
            LIMIT {limit}
            """
            rows = self.connector.execute(sql)
            return [row[0] for row in rows]
        except Exception:
            return []
