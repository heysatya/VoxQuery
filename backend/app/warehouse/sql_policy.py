from __future__ import annotations

from dataclasses import dataclass

import sqlglot
from sqlglot import exp

from app.models.contracts import SchemaTable


class SqlPolicyError(ValueError):
    """Raised when SQL cannot satisfy the read-only execution policy."""


@dataclass(frozen=True)
class CanonicalSql:
    sql: str
    dialect: str
    row_limit: int
    limit_added: bool
    limit_clamped: bool


@dataclass(frozen=True)
class SchemaAllowlist:
    # table name (lowercase) -> set of column names (lowercase)
    tables: dict[str, set[str]]


def build_allowlist(schema_tables: list[SchemaTable]) -> SchemaAllowlist:
    """schema_tables: list of SchemaTable from a WarehouseConnector.fetch_schema_snapshot() call."""
    tables: dict[str, set[str]] = {}
    for t in schema_tables:
        tables[t.table_name.lower()] = {c.name.lower() for c in t.columns}
    return SchemaAllowlist(tables=tables)


def validate_against_allowlist(parsed: exp.Expression, allowlist: SchemaAllowlist) -> None:
    # Walk referenced tables against the schema allowlist.
    referenced_tables = set()
    for table in parsed.find_all(exp.Table):
        table_name = table.name.lower()
        if table_name not in allowlist.tables:
            raise SqlPolicyError(f'Query references a table ("{table_name}") that isn\'t part of the connected schema.')
        referenced_tables.add(table_name)

    # Walk referenced columns against the allowlist.
    for column in parsed.find_all(exp.Column):
        col_name = column.name.lower()
        if col_name == "*":
            continue
            
        table_ref = column.table.lower() if column.table else None
        
        if table_ref:
            if table_ref in allowlist.tables:
                if col_name not in allowlist.tables[table_ref]:
                    raise SqlPolicyError(f'Query references a column ("{table_ref}.{col_name}") that doesn\'t exist in the connected schema.')
        else:
            found = False
            for t in referenced_tables:
                if col_name in allowlist.tables[t]:
                    found = True
                    break
            
            if not found:
                raise SqlPolicyError(f'Query references a column ("{col_name}") that doesn\'t exist in the connected schema.')


def _is_readonly_query(node: exp.Expression) -> bool:
    if isinstance(node, exp.Select):
        return True
    if isinstance(node, (exp.Union, exp.Intersect, exp.Except)):
        return _is_readonly_query(node.this) and _is_readonly_query(node.expression)
    return False


def canonicalize_readonly_sql(
    sql: str, 
    *, 
    dialect: str = "snowflake", 
    row_limit: int = 10000,
    allowlist: SchemaAllowlist | None = None
) -> CanonicalSql:
    """Return read-only SQL with the top-level row limit made explicit, optionally checking schema."""
    try:
        statements = sqlglot.parse(sql, read=dialect)
    except Exception as exc:
        raise SqlPolicyError(f"SQL parsing failed: {exc}") from exc

    if len(statements) != 1 or statements[0] is None:
        raise SqlPolicyError("Exactly one SQL statement is required.")

    parsed = statements[0]
    if not _is_readonly_query(parsed):
        raise SqlPolicyError("Only SELECT, UNION, INTERSECT, and EXCEPT statements are allowed.")

    validate_no_cartesian_joins(parsed)

    if allowlist:
        validate_against_allowlist(parsed, allowlist)

    limit_added = False
    limit_clamped = False
    limit_exp = parsed.args.get("limit")

    if limit_exp is None:
        parsed = parsed.limit(row_limit)
        limit_added = True
    else:
        limit_value = _limit_value(limit_exp)
        if limit_value is None or limit_value > row_limit:
            limit_exp.set("expression", exp.Literal.number(row_limit))
            limit_clamped = True

    return CanonicalSql(
        sql=parsed.sql(dialect=dialect),
        dialect=dialect,
        row_limit=row_limit,
        limit_added=limit_added,
        limit_clamped=limit_clamped,
    )


def _limit_value(limit_exp: exp.Limit) -> int | None:
    expression = limit_exp.expression
    if expression is None:
        return None
    try:
        return int(expression.name)
    except (TypeError, ValueError):
        return None


def validate_no_cartesian_joins(parsed: exp.Expression) -> None:
    """Reject generated SQL that can multiply rows through unconstrained joins."""
    for join in parsed.find_all(exp.Join):
        if join.args.get("kind") == "CROSS":
            raise SqlPolicyError("Query contains an explicit CROSS JOIN; add a constrained join condition.")
        if join.args.get("on") is None and join.args.get("using") is None:
            raise SqlPolicyError("Query joins tables without an ON or USING condition.")

    for select in parsed.find_all(exp.Select):
        from_clause = select.args.get("from")
        if from_clause is None:
            continue
        expressions = list(getattr(from_clause, "expressions", []) or [])
        joins = list(select.args.get("joins") or [])
        if len(expressions) > 1 and not joins:
            raise SqlPolicyError("Query lists multiple tables without explicit join conditions.")
