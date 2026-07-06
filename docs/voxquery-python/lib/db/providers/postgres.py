import time
import psycopg2
import psycopg2.extras
from lib.db.types import DBAdapter, QueryExecutionResult, SchemaTable, ColumnInfo


class PostgresAdapter(DBAdapter):
    """
    Works for Supabase Postgres AND any vanilla Postgres warehouse — the only
    difference between "supabase_postgres" and "generic_postgres" in
    config/db_config.json is which env var holds the connection string.

    IMPORTANT: the connection string used here must point at a role that:
      - only has GRANT SELECT on the tables/views executives should see
      - is NOT the Supabase service_role key (that bypasses RLS entirely)
      - ideally goes through Supabase's Supavisor pooler in transaction mode
    """

    provider_name = "postgres"
    validator_dialect = "postgres"

    def __init__(self, connection_string: str):
        self._connection_string = connection_string

    def execute_select(self, sql: str, statement_timeout_ms: int) -> QueryExecutionResult:
        start = time.time()
        conn = psycopg2.connect(self._connection_string)
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                # Session-level timeout — second guardrail layer independent
                # of the application-level row cap already injected by the validator.
                cur.execute(f"SET statement_timeout = {int(statement_timeout_ms)}")
                # Read-only transaction — third guardrail layer.
                cur.execute("SET TRANSACTION READ ONLY")
                cur.execute(sql)
                rows = cur.fetchall()
                columns = [ColumnInfo(name=d.name, data_type=str(d.type_code)) for d in cur.description]
                execution_ms = (time.time() - start) * 1000

                return QueryExecutionResult(
                    columns=columns,
                    rows=[dict(r) for r in rows],
                    row_count=len(rows),
                    truncated=False,  # validator already injected LIMIT; executor doesn't re-cap
                    execution_ms=execution_ms,
                )
        finally:
            conn.close()

    def fetch_schema_snapshot(self) -> list[SchemaTable]:
        conn = psycopg2.connect(self._connection_string)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT table_name, column_name, data_type
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                    ORDER BY table_name, ordinal_position
                    """
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
        pass  # no pooled connections to close in this simple synchronous version
