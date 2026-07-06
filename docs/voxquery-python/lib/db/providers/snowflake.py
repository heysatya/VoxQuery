import time
import json
import snowflake.connector
from lib.db.types import DBAdapter, QueryExecutionResult, SchemaTable, ColumnInfo


class SnowflakeAdapter(DBAdapter):
    """Kept as a working reference so a customer running Snowflake (the
    original spec target) is a config change (active_provider -> "snowflake"
    in db_config.json), not a rewrite of the pipeline."""

    provider_name = "snowflake"
    validator_dialect = "snowflake"

    def __init__(self, connection_options_json: str):
        # SNOWFLAKE_CONN_STRING is expected to be a JSON blob:
        # {"account": "...", "user": "...", "password": "...", "warehouse": "...", "database": "...", "schema": "..."}
        self._options = json.loads(connection_options_json)

    def execute_select(self, sql: str, statement_timeout_ms: int) -> QueryExecutionResult:
        start = time.time()
        conn = snowflake.connector.connect(**self._options)
        try:
            cur = conn.cursor(snowflake.connector.DictCursor)
            cur.execute(f"ALTER SESSION SET STATEMENT_TIMEOUT_IN_SECONDS = {int(statement_timeout_ms / 1000)}")
            cur.execute(sql)
            rows = cur.fetchall()
            columns = [ColumnInfo(name=d[0], data_type=str(d[1])) for d in cur.description]
            execution_ms = (time.time() - start) * 1000
            return QueryExecutionResult(
                columns=columns,
                rows=list(rows),
                row_count=len(rows),
                truncated=False,
                execution_ms=execution_ms,
            )
        finally:
            conn.close()

    def fetch_schema_snapshot(self) -> list[SchemaTable]:
        conn = snowflake.connector.connect(**self._options)
        try:
            cur = conn.cursor()
            cur.execute(
                """SELECT table_name, column_name, data_type FROM information_schema.columns
                   WHERE table_schema = 'PUBLIC' ORDER BY table_name, ordinal_position"""
            )
            by_table: dict[str, SchemaTable] = {}
            for table_name, column_name, data_type in cur.fetchall():
                if table_name not in by_table:
                    by_table[table_name] = SchemaTable(table_name=table_name)
                by_table[table_name].columns.append(ColumnInfo(name=column_name, data_type=data_type))
            return list(by_table.values())
        finally:
            conn.close()

    def dispose(self) -> None:
        pass
