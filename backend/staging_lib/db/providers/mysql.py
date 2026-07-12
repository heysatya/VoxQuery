import time
import pymysql
import pymysql.cursors
from lib.db.types import DBAdapter, QueryExecutionResult, SchemaTable, ColumnInfo


class MySQLAdapter(DBAdapter):
    """Illustrative third provider. Same interface, same guardrail obligations."""

    provider_name = "mysql"
    validator_dialect = "mysql"

    def __init__(self, connection_string: str):
        # Expected format: "host=...;user=...;password=...;database=..."
        self._params = dict(part.split("=", 1) for part in connection_string.split(";") if part)

    def execute_select(self, sql: str, statement_timeout_ms: int) -> QueryExecutionResult:
        start = time.time()
        conn = pymysql.connect(
            host=self._params.get("host"),
            user=self._params.get("user"),
            password=self._params.get("password"),
            database=self._params.get("database"),
            cursorclass=pymysql.cursors.DictCursor,
        )
        try:
            with conn.cursor() as cur:
                cur.execute(f"SET SESSION MAX_EXECUTION_TIME={int(statement_timeout_ms)}")
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
        conn = pymysql.connect(
            host=self._params.get("host"),
            user=self._params.get("user"),
            password=self._params.get("password"),
            database=self._params.get("database"),
        )
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT table_name, column_name, data_type FROM information_schema.columns
                       WHERE table_schema = DATABASE() ORDER BY table_name, ordinal_position"""
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
