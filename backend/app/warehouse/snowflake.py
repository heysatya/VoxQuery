import logging
import asyncio
import snowflake.connector
import sqlglot
from app.models.contracts import ChartType, ResultPayload, ResultShape
from app.warehouse.connector import WarehouseConnector

logger = logging.getLogger(__name__)

class SnowflakeWarehouseConnector(WarehouseConnector):
    def __init__(self, dsn: str):
        self.dsn = dsn
        self.last_sql: str | None = None

    def _parse_dsn(self):
        dsn = self.dsn.replace("snowflake://", "")
        parts = dsn.split("@")
        if len(parts) != 2:
            return {"user": "", "password": "", "account": dsn, "database": None, "schema": None}
        user_pass, rest = parts
        up_parts = user_pass.split(":")
        user = up_parts[0]
        password = up_parts[1] if len(up_parts) > 1 else ""
        
        path_parts = rest.split("/")
        account = path_parts[0]
        database = path_parts[1] if len(path_parts) > 1 else None
        schema = path_parts[2] if len(path_parts) > 2 else None
        
        return {
            "user": user,
            "password": password,
            "account": account,
            "database": database,
            "schema": schema
        }

    def _execute_sync(self, sql: str, snowflake_role: str):
        if self.dsn == "dummy_dsn":
            return (
                [("North America", 1500000.00), ("Europe", 1200000.00), ("Asia", 900000.00)],
                ["region", "net_revenue"],
                3
            )
            
        conn_params = self._parse_dsn()
        kwargs = {
            "user": conn_params["user"],
            "password": conn_params["password"],
            "account": conn_params["account"],
            "role": snowflake_role
        }
        if conn_params["database"]:
            kwargs["database"] = conn_params["database"]
        if conn_params["schema"]:
            kwargs["schema"] = conn_params["schema"]
            
        with snowflake.connector.connect(**kwargs) as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                rows = cur.fetchall()
                columns = [desc[0].lower() for desc in cur.description] if cur.description else []
                row_count = cur.rowcount
                return rows, columns, row_count

    async def execute_readonly(self, sql: str, *, snowflake_role: str) -> tuple[ResultPayload, ResultShape]:
        try:
            parsed = sqlglot.parse_one(sql, read="snowflake")
            limit_exp = parsed.args.get("limit")
            if not limit_exp:
                parsed = parsed.limit(10000)
            else:
                try:
                    limit_val = int(limit_exp.expression.name)
                    if limit_val > 10000:
                        parsed.args["limit"].set("expression", sqlglot.exp.Literal.number(10000))
                except Exception:
                    parsed.args["limit"].set("expression", sqlglot.exp.Literal.number(10000))
            sql = parsed.sql(dialect="snowflake")
        except Exception as e:
            logger.warning(f"Failed to parse SQL for limit enforcement, applying naive limit: {e}")
            if "LIMIT" not in sql.upper():
                sql += " LIMIT 10000"
                
        self.last_sql = sql
        
        # Execute in thread to avoid blocking event loop
        rows, columns, row_count = await asyncio.to_thread(self._execute_sync, sql, snowflake_role)
        
        list_rows = [list(r) for r in rows]
        
        chart_type = ChartType.table
        if len(columns) == 2:
            chart_type = ChartType.bar
            
        summary = f"Result returned {row_count} rows."
        if list_rows and len(columns) >= 1:
            summary = f"Returned {row_count} rows, first row {columns[0]} is {list_rows[0][0]}."

        result = ResultPayload(
            columns=columns,
            rows=list_rows,
            row_count=row_count,
        )
        return result, ResultShape(
            columns=result.columns,
            chart_type=chart_type,
            row_count=result.row_count,
            aggregate_summary=summary,
        )
