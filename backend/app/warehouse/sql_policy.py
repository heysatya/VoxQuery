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


from typing import Any

def build_allowlist(schema_tables: list[SchemaTable]) -> SchemaAllowlist:
    """schema_tables: list of SchemaTable from a WarehouseConnector.fetch_schema_snapshot() call."""
    tables: dict[str, set[str]] = {}
    for t in schema_tables:
        tables[t.table_name.lower()] = {c.name.lower() for c in t.columns}
    return SchemaAllowlist(tables=tables)


def build_allowlist_from_context(schema_context: list[Any]) -> SchemaAllowlist:
    """Construct a SchemaAllowlist from a list of SchemaTable or SchemaChunk objects or dicts."""
    tables: dict[str, set[str]] = {}
    common_cols = {"id", "tenant_id", "user_id", "created_at", "updated_at", "date", "time", "year", "month", "day"}

    for item in schema_context:
        if hasattr(item, "table_name") and hasattr(item, "columns"):
            t_name = str(item.table_name).lower()
            if t_name not in tables:
                tables[t_name] = set(common_cols)
            for c in item.columns:
                c_name = getattr(c, "name", getattr(c, "column_name", str(c))).lower()
                tables[t_name].add(c_name)
        else:
            t_name = getattr(item, "table", getattr(item, "table_name", None))
            c_name = getattr(item, "column", getattr(item, "column_name", None))
            content = getattr(item, "content", "") or ""

            if isinstance(item, dict):
                t_name = t_name or item.get("table") or item.get("table_name")
                c_name = c_name or item.get("column") or item.get("column_name")
                content = content or item.get("content", "")

            if t_name:
                t_name_str = str(t_name).lower()
                if t_name_str not in tables:
                    tables[t_name_str] = set(common_cols)
                if c_name:
                    tables[t_name_str].add(str(c_name).lower())
                if content:
                    import re
                    words = re.findall(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\b", str(content))
                    for w in words:
                        tables[t_name_str].add(w.lower())

    for t_name in list(tables.keys()):
        base_name = t_name.rstrip("s")
        fk = f"{base_name}_id"
        for target_table in tables:
            tables[target_table].add(fk)

    return SchemaAllowlist(tables=tables)


def validate_against_allowlist(parsed: exp.Expression, allowlist: SchemaAllowlist) -> None:
    # Walk referenced tables against the schema allowlist.
    referenced_tables = set()
    for table in parsed.find_all(exp.Table):
        table_name = table.name.lower()
        if table_name not in allowlist.tables:
            raise SqlPolicyError(
                f'Query references a table ("{table_name}") that isn\'t part of the connected schema.'
            )
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
                    raise SqlPolicyError(
                        f'Query references a column ("{table_ref}.{col_name}") that doesn\'t exist in the connected schema.'
                    )
        else:
            found = False
            for t in referenced_tables:
                if col_name in allowlist.tables[t]:
                    found = True
                    break

            if not found:
                raise SqlPolicyError(
                    f'Query references a column ("{col_name}") that doesn\'t exist in the connected schema.'
                )


def _is_readonly_query(node: exp.Expression) -> bool:
    if isinstance(node, exp.Select):
        return True
    if isinstance(node, (exp.Union, exp.Intersect, exp.Except)):
        return _is_readonly_query(node.this) and _is_readonly_query(node.expression)
    return False


def auto_fix_snowflake_types(parsed: exp.Expression) -> exp.Expression:
    """
    Safely rewrites AST nodes for Snowflake execution:
    1. Wraps date parameters in DATE_TRUNC, DATEADD, DATEDIFF with TRY_TO_TIMESTAMP(...) to prevent VARCHAR compilation errors.
    2. Converts division operations (a / b) to DIV0(a, b) to prevent Division by Zero runtime crashes.
    """

    def _is_already_timestamp_cast(node: exp.Expression) -> bool:
        if isinstance(node, (exp.Cast, exp.TryCast)):
            return True
        if isinstance(node, exp.Anonymous) and node.name.upper() in (
            "TRY_TO_TIMESTAMP",
            "TO_TIMESTAMP",
            "TRY_TO_DATE",
            "TO_DATE",
            "TRY_TO_TIME",
            "TO_TIME",
        ):
            return True
        if isinstance(node, exp.Func) and str(node).upper().startswith(
            ("TRY_TO_TIMESTAMP", "TO_TIMESTAMP", "TRY_TO_DATE", "TO_DATE")
        ):
            return True
        return False

    def _wrap(node: exp.Expression) -> exp.Expression:
        if _is_already_timestamp_cast(node):
            return node
        return exp.Anonymous(this="TRY_TO_TIMESTAMP", expressions=[node])

    def _is_inside_div0(node: exp.Expression) -> bool:
        curr = node.parent
        while curr:
            if isinstance(curr, exp.If):
                true_arg = curr.args.get("true")
                if isinstance(true_arg, exp.Literal) and str(true_arg.this) == "0":
                    return True
            curr = curr.parent
        return False

    # 1. Fix date/time function arguments
    for node in parsed.find_all(exp.DateTrunc):
        if (
            node.this
            and not isinstance(node.this, (exp.Literal, exp.DateTrunc))
            and not _is_already_timestamp_cast(node.this)
        ):
            node.set("this", _wrap(node.this))

    for node in list(parsed.find_all(exp.Anonymous)):
        func_name = node.name.upper()
        exprs = node.expressions
        if func_name == "DATE_TRUNC" and len(exprs) >= 2:
            if not _is_already_timestamp_cast(exprs[1]) and not isinstance(exprs[1], exp.Literal):
                exprs[1] = _wrap(exprs[1])
        elif func_name == "DATEADD" and len(exprs) >= 3:
            if not _is_already_timestamp_cast(exprs[2]) and not isinstance(exprs[2], exp.Literal):
                exprs[2] = _wrap(exprs[2])
        elif func_name == "DATEDIFF" and len(exprs) >= 3:
            if not _is_already_timestamp_cast(exprs[1]) and not isinstance(exprs[1], exp.Literal):
                exprs[1] = _wrap(exprs[1])
            if not _is_already_timestamp_cast(exprs[2]) and not isinstance(exprs[2], exp.Literal):
                exprs[2] = _wrap(exprs[2])

    # 2. Convert division (a / b) to DIV0(a, b) for safe zero-division handling in Snowflake
    for div_node in list(parsed.find_all(exp.Div)):
        if _is_inside_div0(div_node):
            continue
        left = div_node.this
        right = div_node.expression
        if left and right:
            div0_ast = sqlglot.parse_one(
                f"DIV0({left.sql(dialect='snowflake')}, {right.sql(dialect='snowflake')})",
                read="snowflake",
            )
            div_node.replace(div0_ast)

    return parsed


def validate_schema_context(parsed: exp.Expression, schema_context: list[Any]) -> None:
    """Extract table and column names from generated SQL and verify they exist in schema_context."""
    if not schema_context:
        return

    context_text_parts = []
    known_tables = set()
    known_columns = set()
    has_full_schema = False

    for item in schema_context:
        if hasattr(item, "table_name") and item.table_name:
            known_tables.add(str(item.table_name).lower())
            if hasattr(item, "columns") and item.columns:
                has_full_schema = True
                for col in item.columns:
                    c_name = getattr(col, "name", getattr(col, "column_name", str(col)))
                    known_columns.add(str(c_name).lower())
        if hasattr(item, "table") and item.table:
            known_tables.add(str(item.table).lower())
        if hasattr(item, "column_name") and item.column_name:
            known_columns.add(str(item.column_name).lower())
        if hasattr(item, "column") and item.column:
            known_columns.add(str(item.column).lower())
        if hasattr(item, "content") and item.content:
            context_text_parts.append(str(item.content).lower())
        elif isinstance(item, str):
            context_text_parts.append(item.lower())

    full_context_text = " ".join(context_text_parts)

    if has_full_schema:
        for table in parsed.find_all(exp.Table):
            t_name = table.name.lower()
            if not t_name:
                continue
            if t_name not in known_tables and t_name not in full_context_text:
                raise SqlPolicyError(
                    f'Query references a hallucinated table ("{t_name}") that does not exist in the connected schema.'
                )

        common_cols = {
            "id", "tenant_id", "user_id", "created_at", "updated_at", "date", "time",
            "year", "month", "day", "country", "region", "state", "city", "status",
            "order_status", "amount", "total", "revenue", "net_revenue", "price", "cost"
        }
        for column in parsed.find_all(exp.Column):
            col_name = column.name.lower()
            if not col_name or col_name in ("*", "count") or col_name.endswith("_id") or col_name in common_cols:
                continue
            if col_name not in known_columns and col_name not in full_context_text:
                raise SqlPolicyError(
                    f'Query references a hallucinated column ("{col_name}") that does not exist in the connected schema.'
                )


def canonicalize_readonly_sql(
    sql: str,
    *,
    dialect: str = "snowflake",
    row_limit: int = 10000,
    allowlist: SchemaAllowlist | None = None,
    schema_context: list[Any] | None = None,
) -> CanonicalSql:
    """Return read-only SQL with the top-level row limit made explicit, optionally checking schema."""
    if sql:
        import re

        sql = sql.strip()
        # Strip XML tags if present
        sql_match = re.search(r"<sql>(.*?)</sql>", sql, flags=re.IGNORECASE | re.DOTALL)
        if sql_match:
            sql = sql_match.group(1).strip()
        else:
            unclosed_match = re.search(r"<sql>(.*)", sql, flags=re.IGNORECASE | re.DOTALL)
            if unclosed_match:
                sql = unclosed_match.group(1).strip()
        # Strip markdown fences
        sql = re.sub(r"^```[a-zA-Z]*\n?", "", sql.strip())
        sql = re.sub(r"\n?```$", "", sql.strip())
        lines = [
            line
            for line in sql.splitlines()
            if line.strip().lower() not in ("<sql>", "</sql>", "```", "```sql", "```xml")
        ]
        sql = "\n".join(lines).strip()

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

    if dialect == "snowflake":
        parsed = auto_fix_snowflake_types(parsed)

    if allowlist:
        validate_against_allowlist(parsed, allowlist)
    elif schema_context:
        validate_schema_context(parsed, schema_context)

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

    res_sql = parsed.sql(dialect=dialect)
    import re
    if not re.search(r"\blimit\b", res_sql, re.IGNORECASE):
        res_sql = f"{res_sql.rstrip(';')} LIMIT 50"

    return CanonicalSql(
        sql=res_sql,
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
            raise SqlPolicyError(
                "Query contains an explicit CROSS JOIN; add a constrained join condition."
            )
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
