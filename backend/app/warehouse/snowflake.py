import asyncio
import logging
import re

import snowflake.connector
from app.models.contracts import ChartType, ResultPayload, ResultShape, SchemaTable, ColumnInfo
from app.warehouse.connector import WarehouseConnector
from app.warehouse.sql_policy import SqlPolicyError, canonicalize_readonly_sql

logger = logging.getLogger(__name__)

# Default query timeout in seconds. Configurable via constructor.
_DEFAULT_TIMEOUT_SECONDS = 30


def _redact_dsn(dsn: str) -> str:
    """Redact credentials from a DSN string for safe logging."""
    # Replace user:password@... with user:***@...
    return re.sub(r"(snowflake://[^:]+:)[^@]+(@)", r"\1***\2", dsn)


class SnowflakeWarehouseConnector(WarehouseConnector):
    def __init__(self, dsn: str, timeout_seconds: int = _DEFAULT_TIMEOUT_SECONDS) -> None:
        if not dsn:
            raise ValueError("Snowflake DSN must not be empty.")
        self.dsn = dsn
        self.timeout_seconds = timeout_seconds
        self.last_sql: str | None = None

    def _parse_dsn(self) -> dict:
        dsn = self.dsn.replace("snowflake://", "")
        parts = dsn.split("@")
        if len(parts) != 2:
            return {"user": "", "password": "", "account": dsn, "database": None, "schema": None}
        user_pass, rest = parts
        up_parts = user_pass.split(":")
        user = up_parts[0]
        password = up_parts[1] if len(up_parts) > 1 else ""

        # Strip query parameters if any
        if "?" in rest:
            rest = rest.split("?")[0]

        path_parts = rest.split("/")
        account = path_parts[0]
        database = path_parts[1] if len(path_parts) > 1 else None
        schema = path_parts[2] if len(path_parts) > 2 else None

        return {
            "user": user,
            "password": password,
            "account": account,
            "database": database,
            "schema": schema,
        }

    def _execute_sync(self, sql: str, snowflake_role: str):
        conn_params = self._parse_dsn()
        kwargs = {
            "user": conn_params["user"],
            "password": conn_params["password"],
            "account": conn_params["account"],
            "role": snowflake_role,
            "login_timeout": self.timeout_seconds,
            "network_timeout": self.timeout_seconds,
        }
        if conn_params["database"]:
            kwargs["database"] = conn_params["database"]
        if conn_params["schema"]:
            kwargs["schema"] = conn_params["schema"]

        try:
            with snowflake.connector.connect(**kwargs) as conn:
                with conn.cursor() as cur:
                    cur.execute(sql)
                    rows = cur.fetchall()
                    columns = [desc[0].lower() for desc in cur.description] if cur.description else []
                    row_count = cur.rowcount
                    return rows, columns, row_count
        except snowflake.connector.errors.OperationalError as e:
            # Re-raise as structured timeout / warehouse error — never leak the DSN
            redacted = _redact_dsn(self.dsn)
            raise RuntimeError(
                f"Snowflake warehouse timeout or connection error (DSN redacted: {redacted}): {type(e).__name__}"
            ) from e
        except Exception as e:
            redacted = _redact_dsn(self.dsn)
            raise RuntimeError(
                f"Snowflake warehouse error (DSN redacted: {redacted}): {type(e).__name__}"
            ) from e

    async def execute_readonly(self, sql: str, *, snowflake_role: str) -> tuple[ResultPayload, ResultShape]:
        canonical = canonicalize_readonly_sql(sql)
        if canonical.sql != sql:
            raise SqlPolicyError("Warehouse received SQL that was not canonicalized by the pipeline.")

        self.last_sql = sql

        # Execute in thread to avoid blocking event loop; enforce timeout
        try:
            rows, columns, row_count = await asyncio.wait_for(
                asyncio.to_thread(self._execute_sync, sql, snowflake_role),
                timeout=self.timeout_seconds,
            )
        except asyncio.TimeoutError:
            redacted = _redact_dsn(self.dsn)
            raise RuntimeError(
                f"Snowflake query timed out after {self.timeout_seconds}s (DSN redacted: {redacted})."
            )

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

    def fetch_schema_snapshot(self) -> list[SchemaTable]:
        conn_params = self._parse_dsn()
        kwargs = {
            "user": conn_params["user"],
            "password": conn_params["password"],
            "account": conn_params["account"],
            "login_timeout": self.timeout_seconds,
            "network_timeout": self.timeout_seconds,
        }
        if conn_params["database"]:
            kwargs["database"] = conn_params["database"]
        if conn_params["schema"]:
            kwargs["schema"] = conn_params["schema"]

        try:
            with snowflake.connector.connect(**kwargs) as conn:
                with conn.cursor() as cur:
                    target_schema = conn_params["schema"].upper() if conn_params["schema"] else 'PUBLIC'
                    cur.execute(
                        f"""SELECT table_name, column_name, data_type FROM information_schema.columns
                           WHERE table_schema = '{target_schema}' ORDER BY table_name, ordinal_position"""
                    )
                    by_table: dict[str, SchemaTable] = {}
                    for table_name, column_name, data_type in cur.fetchall():
                        if table_name not in by_table:
                            by_table[table_name] = SchemaTable(table_name=table_name)
                        by_table[table_name].columns.append(ColumnInfo(name=column_name, data_type=str(data_type)))
                    return list(by_table.values())
        except snowflake.connector.errors.OperationalError as e:
            redacted = _redact_dsn(self.dsn)
            raise RuntimeError(
                f"Snowflake schema fetch timeout or connection error (DSN redacted: {redacted}): {type(e).__name__}"
            ) from e
        except Exception as e:
            redacted = _redact_dsn(self.dsn)
            raise RuntimeError(
                f"Snowflake schema fetch error (DSN redacted: {redacted}): {type(e).__name__}"
            ) from e
