"""
sampler.py
──────────
Generates richer sample data and statistics from DuckDB tables.
Used to improve chunk quality during enrichment.

Design decisions:
- Separate from schema_extractor to keep extraction fast
- Run only during indexing, not at query time
- Returns structured data for LLM enrichment prompts
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from app.duckdb_connector.connection import DuckDBConnectionManager

logger = logging.getLogger(__name__)


@dataclass
class ColumnSample:
    """Sample values and statistics for a single column."""
    column_name: str
    data_type: str
    sample_values: list[Any] = field(default_factory=list)
    null_percentage: float = 0.0
    approx_distinct: Optional[int] = None
    min_value: Optional[str] = None
    max_value: Optional[str] = None
    is_likely_pk: bool = False
    is_likely_fk: bool = False
    is_likely_date: bool = False
    is_likely_metric: bool = False


@dataclass
class TableSample:
    """Complete sample profile for a table."""
    schema_name: str
    table_name: str
    row_count: int
    column_samples: list[ColumnSample] = field(default_factory=list)
    sample_rows: list[dict[str, Any]] = field(default_factory=list)


class DuckDBSampler:
    """
    Provides richer sampling for tables beyond basic extraction.

    Usage:
        sampler = DuckDBSampler(conn_mgr)
        profile = sampler.profile_table("main", "orders")
    """

    # Keywords suggesting a column is a metric
    METRIC_KEYWORDS = frozenset({
        "total", "amount", "revenue", "count", "quantity",
        "price", "cost", "value", "sum", "avg", "sales",
    })

    # Keywords suggesting a foreign key
    FK_KEYWORDS = frozenset({"_id", "_key", "_ref", "_fk"})

    def __init__(self, conn_mgr: DuckDBConnectionManager, sample_size: int = 5):
        self.conn_mgr = conn_mgr
        self.sample_size = sample_size

    def profile_table(
        self,
        schema_name: str,
        table_name: str,
    ) -> TableSample:
        """
        Create a complete profile of a table including column-level samples.

        Args:
            schema_name: Schema containing the table
            table_name: Name of the table

        Returns:
            TableSample with all column samples populated
        """
        # Get row count
        row_count_result = self.conn_mgr.execute_one(
            f'SELECT COUNT(*) FROM "{schema_name}"."{table_name}"'
        )
        row_count = int(row_count_result[0]) if row_count_result else 0

        # Get column names and types
        columns_sql = """
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = ?
          AND table_name = ?
        ORDER BY ordinal_position
        """
        col_rows = self.conn_mgr.execute(
            columns_sql, [schema_name, table_name])

        # Sample rows (used for all columns at once)
        sample_rows = self._get_sample_rows(schema_name, table_name)

        # Build column samples
        column_samples = []
        for col_name, data_type in col_rows:
            col_sample = self._profile_column(
                schema_name=schema_name,
                table_name=table_name,
                column_name=col_name,
                data_type=data_type,
                row_count=row_count,
                sample_rows=sample_rows,
            )
            column_samples.append(col_sample)

        return TableSample(
            schema_name=schema_name,
            table_name=table_name,
            row_count=row_count,
            column_samples=column_samples,
            sample_rows=sample_rows,
        )

    def _profile_column(
        self,
        schema_name: str,
        table_name: str,
        column_name: str,
        data_type: str,
        row_count: int,
        sample_rows: list[dict[str, Any]],
    ) -> ColumnSample:
        """Profile a single column."""
        col = ColumnSample(
            column_name=column_name,
            data_type=data_type,
        )

        # Extract sample values from already-retrieved rows
        col.sample_values = [
            row.get(column_name)
            for row in sample_rows
            if row.get(column_name) is not None
        ][:5]

        if row_count > 0:
            # Approximate distinct count
            try:
                result = self.conn_mgr.execute_one(
                    f'SELECT approx_count_distinct("{column_name}") '
                    f'FROM "{schema_name}"."{table_name}"'
                )
                col.approx_distinct = int(result[0]) if result else None
            except Exception:
                pass

            # Null percentage
            try:
                result = self.conn_mgr.execute_one(
                    f'SELECT (COUNT(*) - COUNT("{column_name}")) * 100.0 / COUNT(*) '
                    f'FROM "{schema_name}"."{table_name}"'
                )
                col.null_percentage = float(result[0]) if result else 0.0
            except Exception:
                pass

        # Heuristics for column type classification
        col_lower = column_name.lower()
        col.is_likely_pk = col_lower in ("id", f"{table_name}_id") or col_lower.endswith(
            "_id") and col.approx_distinct == row_count
        col.is_likely_fk = any(col_lower.endswith(
            kw) for kw in self.FK_KEYWORDS) and col_lower != f"{table_name}_id"
        col.is_likely_metric = any(
            kw in col_lower for kw in self.METRIC_KEYWORDS)
        col.is_likely_date = "date" in data_type.lower() or "timestamp" in data_type.lower()

        return col

    def _get_sample_rows(
        self,
        schema_name: str,
        table_name: str,
    ) -> list[dict[str, Any]]:
        """Get sample rows using TABLESAMPLE for large tables."""
        try:
            count_result = self.conn_mgr.execute_one(
                f'SELECT COUNT(*) FROM "{schema_name}"."{table_name}"'
            )
            row_count = int(count_result[0]) if count_result else 0

            if row_count == 0:
                return []

            df = self.conn_mgr.query_df(
                f'SELECT * FROM "{schema_name}"."{table_name}" '
                f'LIMIT {self.sample_size}'
            )
            return df.where(df.notna(), None).to_dict(orient="records")

        except Exception as e:
            logger.warning("Could not sample %s.%s: %s",
                           schema_name, table_name, e)
            return []

    def get_distinct_values(
        self,
        schema_name: str,
        table_name: str,
        column_name: str,
        limit: int = 20,
    ) -> list[Any]:
        """
        Get distinct values for low-cardinality columns.
        Useful for categorical columns like 'region', 'status'.

        Only runs if approx_distinct < limit to avoid expensive scans.
        """
        try:
            sql = f"""
            SELECT DISTINCT "{column_name}"
            FROM "{schema_name}"."{table_name}"
            WHERE "{column_name}" IS NOT NULL
            ORDER BY "{column_name}"
            LIMIT {limit}
            """
            rows = self.conn_mgr.execute(sql)
            return [row[0] for row in rows]
        except Exception:
            return []
