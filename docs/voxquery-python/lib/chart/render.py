import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from lib.chart.selector import ChartSelection
from lib.db.types import QueryExecutionResult


def build_chart_html(chart: ChartSelection, result: QueryExecutionResult) -> str:
    df = pd.DataFrame(result.rows)

    if chart.chart_type == "line" and chart.x_field and chart.y_field:
        fig = px.line(df, x=chart.x_field, y=chart.y_field)
        return fig.to_html(full_html=False, include_plotlyjs="cdn")

    if chart.chart_type == "bar" and chart.x_field and chart.y_field:
        fig = px.bar(df, x=chart.x_field, y=chart.y_field)
        return fig.to_html(full_html=False, include_plotlyjs="cdn")

    if chart.chart_type == "stat_card" and chart.y_field:
        value = df[chart.y_field].iloc[0] if not df.empty else None
        fig = go.Figure(go.Indicator(mode="number", value=value, title={"text": chart.y_field}))
        fig.update_layout(height=220)
        return fig.to_html(full_html=False, include_plotlyjs="cdn")

    # table fallback — plain HTML, no charting library needed
    return df.to_html(index=False, classes="result-table", border=0)
