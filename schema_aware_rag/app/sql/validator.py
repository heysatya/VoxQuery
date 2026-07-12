from __future__ import annotations

import duckdb
import sqlglot


def validate_sql(sql: str, dialect: str = "duckdb") -> tuple[bool, str]:
    """Parse *sql* with sqlglot; return (is_valid, error_message)."""
    try:
        sqlglot.parse_one(sql, dialect=dialect)
        return True, ""
    except sqlglot.errors.ParseError as exc:
        return False, str(exc)


def is_read_only(sql: str) -> bool:
    """Return True only if the statement is a SELECT (no mutations)."""
    try:
        stmt = sqlglot.parse_one(sql)
        return isinstance(stmt, sqlglot.expressions.Select)
    except Exception:
        return False
