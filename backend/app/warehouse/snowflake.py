import asyncio
import logging
import re
from uuid import UUID
import concurrent.futures
from threading import local as _ThreadLocal

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


class SnowflakeConnectionPool:
    """
    A bounded pool of pre-authenticated, long-lived Snowflake connections.

    Design: One connection per worker thread, stored in threading.local().
    This eliminates the 1-3 second TLS handshake cost that occurs when
    snowflake.connector.connect() is called on every query.

    Heartbeat: Before reusing a connection, we execute SELECT 1. If the
    session has expired, we reconnect transparently.

    Thread safety: Each thread owns its own connection. No locking needed.
    """

    def __init__(
        self,
        conn_params: dict,
        pool_size: int = 5,
        timeout_seconds: int = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._params = conn_params
        self._timeout = timeout_seconds
        self._local = _ThreadLocal()  # one Snowflake connection per thread
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=pool_size,
            thread_name_prefix="sf-pool",
        )

    def _get_connection(self):
        """Return the calling thread's connection, creating or reconnecting as needed."""
        conn = getattr(self._local, "conn", None)
        if conn is None:
            # First call on this thread — authenticate and cache
            conn = snowflake.connector.connect(**self._params)
            self._local.conn = conn
        else:
            # Reuse existing connection; verify it is still alive
            try:
                conn.cursor().execute("SELECT 1")
            except Exception:
                # Session expired or network error — reconnect
                conn = snowflake.connector.connect(**self._params)
                self._local.conn = conn
        return conn

    def _execute_sync(self, sql: str, snowflake_role: str) -> tuple:
        """Synchronous execution — called inside ThreadPoolExecutor."""
        conn = self._get_connection()
        try:
            with conn.cursor() as cur:
                if snowflake_role:
                    cur.execute(f"USE ROLE IDENTIFIER('{snowflake_role}')")
                cur.execute(sql)
                rows = cur.fetchall()
                columns = [d[0].lower() for d in cur.description] if cur.description else []
                return rows, columns, cur.rowcount
        except snowflake.connector.errors.OperationalError as e:
            raise RuntimeError(
                f"Snowflake warehouse error: {type(e).__name__}"
            ) from e

    async def execute(self, sql: str, snowflake_role: str) -> tuple:
        """Async entry point — dispatches to the pre-warmed thread pool."""
        loop = asyncio.get_event_loop()
        return await asyncio.wait_for(
            loop.run_in_executor(self._executor, self._execute_sync, sql, snowflake_role),
            timeout=self._timeout,
        )

    async def close(self) -> None:
        """Graceful shutdown — waits for in-flight queries to complete."""
        self._executor.shutdown(wait=True)


class SnowflakeWarehouseConnector(WarehouseConnector):
    def __init__(
        self,
        dsn: str,
        timeout_seconds: int = _DEFAULT_TIMEOUT_SECONDS,
        pool: SnowflakeConnectionPool | None = None,
    ) -> None:
        if not dsn:
            raise ValueError("Snowflake DSN must not be empty.")
        self.dsn = dsn
        self.timeout_seconds = timeout_seconds
        self.last_sql: str | None = None
        # If a pre-warmed pool is injected, use it for execute_readonly.
        # If None, fall back to creating a new connection per query (test/fallback mode).
        self._pool = pool

    def _parse_dsn(self) -> dict:
        from urllib.parse import urlparse, unquote
        parsed = urlparse(self.dsn)
        
        path = parsed.path.strip("/")
        path_parts = path.split("/") if path else []
        database = path_parts[0] if len(path_parts) > 0 else None
        schema = path_parts[1] if len(path_parts) > 1 else None
        
        return {
            "user": unquote(parsed.username) if parsed.username else "",
            "password": unquote(parsed.password) if parsed.password else "",
            "account": parsed.hostname or "",
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
                f"Snowflake warehouse error (DSN redacted: {redacted}): {type(e).__name__} - {str(e)}"
            ) from e

    async def execute_readonly(self, sql: str, *, snowflake_role: str, tenant_id: UUID | None = None) -> tuple[ResultPayload, ResultShape]:
        canonical = canonicalize_readonly_sql(sql)
        if canonical.sql != sql:
            raise SqlPolicyError("Warehouse received SQL that was not canonicalized by the pipeline.")

        self.last_sql = sql

        try:
            if self._pool is not None:
                # Fast path: use pre-warmed connection pool
                rows, columns, row_count = await self._pool.execute(sql, snowflake_role)
            else:
                # Slow path (tests / fallback): new connection per query
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
