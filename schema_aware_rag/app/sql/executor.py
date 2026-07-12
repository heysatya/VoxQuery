from __future__ import annotations

from typing import Any

import duckdb

from app.sql.validator import is_read_only, validate_sql


class SQLExecutor:
    def __init__(self, conn: duckdb.DuckDBPyConnection) -> None:
        self._conn = conn

    def execute(self, sql: str, max_rows: int = 500) -> list[dict[str, Any]]:
        valid, err = validate_sql(sql)
        if not valid:
            raise ValueError(f"Invalid SQL: {err}")
        if not is_read_only(sql):
            raise PermissionError("Only SELECT statements are permitted.")
        df = self._conn.execute(sql).fetchdf()
        return df.head(max_rows).to_dict(orient="records")
