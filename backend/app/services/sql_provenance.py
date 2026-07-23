"""Parses executed SQL to extract provenance: source tables and filter predicates.
Used to build memory-graph entity/filter nodes and to construct safe drilldown queries.
"""
from __future__ import annotations
from typing import Any
import sqlglot
from sqlglot import exp

SAFE_OPERATORS: dict[str, str] = {
    "eq": "=",
    "gt": ">",
    "lt": "<",
    "gte": ">=",
    "lte": "<=",
}


def parse_sql_provenance(sql: str) -> tuple[list[str], list[dict[str, Any]]]:
    if not sql or not sql.strip():
        return [], []
    try:
        tree = sqlglot.parse_one(sql, read="snowflake")
    except Exception:
        return [], []

    tables = sorted({t.name for t in tree.find_all(exp.Table) if t.name})

    predicates: list[dict[str, Any]] = []
    where = tree.find(exp.Where)
    if where:
        for cond in where.find_all(exp.EQ, exp.GT, exp.LT, exp.GTE, exp.LTE, exp.In):
            col = cond.find(exp.Column)
            if col is None:
                continue
            op_key = cond.key.lower() if hasattr(cond, "key") and cond.key else "eq"
            val = None
            if hasattr(cond, "expression") and cond.expression is not None:
                val = cond.expression.sql()
            elif hasattr(cond, "this") and cond.this is not None and cond.this != col:
                val = cond.this.sql()

            # Clean quotes if present
            if val and (val.startswith("'") and val.endswith("'")):
                val = val[1:-1]

            predicates.append({
                "column": col.name,
                "operator": op_key,
                "value": val,
            })
    return tables, predicates


def extract_metrics(semantic_columns: list[dict[str, Any]]) -> list[str]:
    """Column names classified as metrics by ResultColumnSemantic inference."""
    return [c["name"] for c in semantic_columns if c.get("role") == "metric"]
