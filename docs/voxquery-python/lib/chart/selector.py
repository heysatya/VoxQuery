from dataclasses import dataclass
from lib.db.types import QueryExecutionResult

ChartType = str  # "line" | "bar" | "stat_card" | "table"

_DATE_TYPE_HINTS = ["date", "timestamp", "time"]
_NUMERIC_TYPE_HINTS = ["int", "numeric", "decimal", "float", "double", "real"]


@dataclass
class ChartSelection:
    chart_type: ChartType
    rationale: str
    x_field: str | None = None
    y_field: str | None = None


def _is_date_column(data_type: str) -> bool:
    return any(hint in data_type.lower() for hint in _DATE_TYPE_HINTS)


def _is_numeric_column(data_type: str) -> bool:
    return any(hint in data_type.lower() for hint in _NUMERIC_TYPE_HINTS)


def select_chart(result: QueryExecutionResult) -> ChartSelection:
    """Pure function, zero API cost, zero added latency beyond result-shape
    inspection — deliberately NOT an LLM call, per 4.6."""
    columns = result.columns
    rows = result.rows

    # Single number, single row -> stat card
    if len(rows) == 1 and len(columns) <= 2:
        numeric_col = next((c for c in columns if _is_numeric_column(c.data_type)), None)
        return ChartSelection(
            chart_type="stat_card",
            rationale="Showing as a stat card — single-value result detected.",
            y_field=numeric_col.name if numeric_col else None,
        )

    date_col = next((c for c in columns if _is_date_column(c.data_type)), None)
    numeric_cols = [c for c in columns if _is_numeric_column(c.data_type)]

    # Time series -> line
    if date_col and numeric_cols:
        return ChartSelection(
            chart_type="line",
            rationale=f'Showing as a line chart — time series detected on "{date_col.name}".',
            x_field=date_col.name,
            y_field=numeric_cols[0].name,
        )

    # Categorical comparison -> bar
    categorical_col = next((c for c in columns if not _is_numeric_column(c.data_type) and not _is_date_column(c.data_type)), None)
    if categorical_col and len(numeric_cols) == 1 and len(columns) == 2:
        return ChartSelection(
            chart_type="bar",
            rationale=f'Showing as a bar chart — categorical comparison detected on "{categorical_col.name}".',
            x_field=categorical_col.name,
            y_field=numeric_cols[0].name,
        )

    # Fallback: anything wider or shaped differently -> table
    return ChartSelection(chart_type="table", rationale="Showing as a table — result shape didn't match a chart pattern.")
