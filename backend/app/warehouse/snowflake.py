import logging
from app.models.contracts import ChartType, ResultPayload, ResultShape
from app.warehouse.connector import WarehouseConnector

logger = logging.getLogger(__name__)

class SnowflakeWarehouseConnector(WarehouseConnector):
    def __init__(self, dsn: str):
        self.dsn = dsn

    async def execute_readonly(self, sql: str, *, snowflake_role: str) -> tuple[ResultPayload, ResultShape]:
        # Connect to Snowflake using self.dsn and snowflake_role
        # For MVP we will stub the connection but validate the query limit requirement is met
        
        if "LIMIT" not in sql.upper():
            sql += " LIMIT 10000"
            
        # Dynamically extract the first column after SELECT to fix the UI data binding anomaly
        # e.g. "SELECT REGION, SUM(REVENUE)..." -> "REGION"
        import re
        dimension = "customer_segment"
        match = re.search(r'SELECT\s+([a-zA-Z0-9_]+)', sql, re.IGNORECASE)
        if match:
            dimension = match.group(1).lower()

        rows = [["Enterprise", 1240000], ["Consumer", 830000], ["Small Business", 410000]]
        # We replace the stubbed string values with something that fits the dimension
        if dimension == "region":
             rows = [["North America", 1240000], ["EMEA", 830000], ["APAC", 410000]]
        elif "date" in dimension or "time" in dimension:
             rows = [["2025-Q1", 1240000], ["2025-Q2", 830000], ["2025-Q3", 410000]]
             
        result = ResultPayload(
            columns=[dimension.lower(), "total_net_revenue"],
            rows=rows,
            row_count=len(rows),
        )
        return result, ResultShape(
            columns=result.columns,
            chart_type=ChartType.bar,
            row_count=result.row_count,
            aggregate_summary=f"{rows[0][0]} leads net revenue in the stubbed e-commerce result set.",
        )
