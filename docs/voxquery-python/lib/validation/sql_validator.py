import re
from dataclasses import dataclass
import sqlglot
from sqlglot import exp


@dataclass
class ValidationResult:
    ok: bool
    sql: str | None = None  # the (possibly LIMIT-injected) safe SQL to execute
    error: str | None = None  # user-facing, never a raw parser exception
    rejected_reason: str | None = None  # "not_select" | "parse_error" | "unknown_table" | "unknown_column" | "multiple_statements"


@dataclass
class SchemaAllowlist:
    # table name (lowercase) -> set of column names (lowercase)
    tables: dict[str, set[str]]


def build_allowlist(schema_tables) -> SchemaAllowlist:
    """schema_tables: list of SchemaTable from a DBAdapter.fetch_schema_snapshot() call."""
    tables: dict[str, set[str]] = {}
    for t in schema_tables:
        tables[t.table_name.lower()] = {c.name.lower() for c in t.columns}
    return SchemaAllowlist(tables=tables)


def validate_and_cap_sql(
    raw_sql: str,
    dialect: str,
    allowlist: SchemaAllowlist,
    row_cap: int,
) -> ValidationResult:
    """
    Mirrors the 4.5 acceptance criteria:
      - root node must be SELECT (blocks DDL/DML before any DB connection opens)
      - unknown tables/columns rejected with a structured user-facing error
      - queries without LIMIT are capped automatically
      - never raises a raw parser exception to the caller
    """
    # Reject stacked statements outright — the classic injection pattern.
    statement_count = len([s for s in raw_sql.split(";") if s.strip()])
    if statement_count > 1:
        return ValidationResult(
            ok=False,
            error="Only a single query is allowed per request.",
            rejected_reason="multiple_statements",
        )

    try:
        parsed = sqlglot.parse_one(raw_sql, dialect=dialect)
    except Exception:
        return ValidationResult(
            ok=False,
            error="The generated query could not be parsed. Please rephrase your question.",
            rejected_reason="parse_error",
        )

    if not isinstance(parsed, exp.Select):
        return ValidationResult(
            ok=False,
            error="Only read (SELECT) queries are permitted.",
            rejected_reason="not_select",
        )

    # Walk referenced tables against the schema allowlist.
    for table in parsed.find_all(exp.Table):
        table_name = table.name.lower()
        if table_name not in allowlist.tables:
            return ValidationResult(
                ok=False,
                error=f'Query references a table ("{table_name}") that isn\'t part of the connected schema.',
                rejected_reason="unknown_table",
            )

    # Walk referenced columns against the allowlist, where the table can be resolved.
    for column in parsed.find_all(exp.Column):
        col_name = column.name.lower()
        table_ref = column.table.lower() if column.table else None
        if table_ref and table_ref in allowlist.tables:
            if col_name not in allowlist.tables[table_ref] and col_name != "*":
                return ValidationResult(
                    ok=False,
                    error=f'Query references a column ("{table_ref}.{col_name}") that doesn\'t exist in the connected schema.',
                    rejected_reason="unknown_column",
                )

    # Inject LIMIT if absent.
    has_limit = re.search(r"\blimit\s+\d+", raw_sql, re.IGNORECASE) is not None
    safe_sql = raw_sql.strip().rstrip(";") if has_limit else f"{raw_sql.strip().rstrip(';')} LIMIT {row_cap}"

    return ValidationResult(ok=True, sql=safe_sql)
