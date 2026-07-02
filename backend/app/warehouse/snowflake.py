from app.models.contracts import ChartType, ResultPayload, ResultShape
from app.warehouse.connector import WarehouseConnector


class FakeSnowflakeConnector(WarehouseConnector):
    """Local connector stub; real Snowflake credentials are not needed for the first slice."""

    async def execute_readonly(self, sql: str, *, snowflake_role: str) -> tuple[ResultPayload, ResultShape]:
        rows = [["Enterprise", 1240000], ["Consumer", 830000], ["Small Business", 410000]]
        result = ResultPayload(
            columns=["customer_segment", "total_net_revenue"],
            rows=rows,
            row_count=len(rows),
        )
        return result, ResultShape(
            columns=result.columns,
            chart_type=ChartType.bar,
            row_count=result.row_count,
            aggregate_summary="Enterprise leads net revenue in the stubbed e-commerce result set.",
        )
