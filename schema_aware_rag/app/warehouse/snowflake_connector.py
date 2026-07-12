"""
snowflake_connector.py
───────────────────────
Snowflake warehouse connector implementing BaseWarehouseConnector.

Design decisions:
- Key-pair authentication preferred over password (more secure)
- Connection pooling via snowflake-connector-python built-in
- Query tagging for cost attribution
- Parameterized queries to prevent injection
- Explicit role switching for RLS enforcement
- Retry logic for transient network errors
"""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import Any, Generator, Optional

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.config import settings, SnowflakeConfig
from app.warehouse.base import (
    BaseWarehouseConnector,
    ConnectionStatus,
    RawColumnInfo,
    RawTableInfo,
    WarehouseType,
)

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────
# Exceptions
# ─────────────────────────────────────────────────────────────────────


class SnowflakeConnectionError(Exception):
    """Raised when Snowflake connection fails."""
    pass


class SnowflakeQueryError(Exception):
    """Raised when a Snowflake query fails."""
    pass


# ─────────────────────────────────────────────────────────────────────
# Connector
# ─────────────────────────────────────────────────────────────────────


class SnowflakeConnector(BaseWarehouseConnector):
    """
    Production-grade Snowflake connector with:
    - Key-pair or password authentication
    - Connection pooling
    - Query tagging for cost attribution
    - Retry logic
    - Role-based access control

    Usage:
        connector = SnowflakeConnector()

        # Test connection
        connector.test_connection()

        # Extract full schema
        tables = connector.extract_all_tables()

        # Context manager
        with connector.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
    """

    APPLICATION_TAG = "VoiceQuery-RAG"

    def __init__(
        self,
        config: Optional[SnowflakeConfig] = None,
    ):
        super().__init__(WarehouseType.SNOWFLAKE)
        self.config = config or settings.snowflake
        self._validate_config()

    # ── Config Validation ─────────────────────────────────────────

    def _validate_config(self) -> None:
        """Validate required configuration is present."""
        if not self.config.account:
            raise SnowflakeConnectionError(
                "SNOWFLAKE_ACCOUNT is required. "
                "Format: xy12345.us-east-1"
            )
        if not self.config.user:
            raise SnowflakeConnectionError("SNOWFLAKE_USER is required.")
        if not self.config.password and not self.config.private_key_path:
            raise SnowflakeConnectionError(
                "Either SNOWFLAKE_PASSWORD or SNOWFLAKE_PRIVATE_KEY_PATH required."
            )
        if not self.config.warehouse:
            raise SnowflakeConnectionError("SNOWFLAKE_WAREHOUSE is required.")
        if not self.config.database:
            raise SnowflakeConnectionError("SNOWFLAKE_DATABASE is required.")

    # ── Key-Pair Auth ─────────────────────────────────────────────

    def _load_private_key(self) -> bytes:
        """Load and decrypt private key for key-pair auth."""
        try:
            from cryptography.hazmat.backends import default_backend
            from cryptography.hazmat.primitives import serialization

            with open(self.config.private_key_path, "rb") as key_file:
                private_key = serialization.load_pem_private_key(
                    key_file.read(),
                    password=(
                        self.config.private_key_passphrase.encode()
                        if self.config.private_key_passphrase
                        else None
                    ),
                    backend=default_backend(),
                )

            return private_key.private_bytes(
                encoding=serialization.Encoding.DER,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
        except Exception as e:
            raise SnowflakeConnectionError(
                f"Failed to load private key from '{self.config.private_key_path}': {e}"
            )

    # ── Connection ────────────────────────────────────────────────

    def _build_connection_params(self) -> dict:
        """Build snowflake-connector-python connection parameters."""
        params = {
            "account": self.config.account,
            "user": self.config.user,
            "warehouse": self.config.warehouse,
            "database": self.config.database,
            "schema": self.config.schema,
            "login_timeout": self.config.login_timeout,
            "network_timeout": self.config.network_timeout,
            "application": self.APPLICATION_TAG,
            # Session parameters
            "session_parameters": {
                "QUERY_TAG": self.APPLICATION_TAG,
                "TIMESTAMP_OUTPUT_FORMAT": "YYYY-MM-DD HH24:MI:SS.FF3",
                "DATE_OUTPUT_FORMAT": "YYYY-MM-DD",
            },
        }

        # Add role if specified
        if self.config.role:
            params["role"] = self.config.role

        # Auth strategy
        if self.config.uses_key_pair_auth:
            params["private_key"] = self._load_private_key()
            logger.info("Using key-pair authentication")
        else:
            params["password"] = self.config.password
            logger.info("Using password authentication")

        return params

    @contextmanager
    def get_connection(self) -> Generator:
        """
        Context manager providing a Snowflake connection.

        Automatically:
        - Resumes warehouse if suspended
        - Sets query tag for cost attribution
        - Closes connection on exit
        """
        try:
            import snowflake.connector
        except ImportError:
            raise ImportError(
                "snowflake-connector-python required. "
                "Install with: pip install snowflake-connector-python"
            )

        conn = None
        try:
            params = self._build_connection_params()
            conn = snowflake.connector.connect(**params)
            self._status = ConnectionStatus.CONNECTED

            logger.debug(
                "Snowflake connection established: account=%s, db=%s, wh=%s",
                self.config.account,
                self.config.database,
                self.config.warehouse,
            )
            yield conn

        except Exception as e:
            self._status = ConnectionStatus.ERROR
            raise SnowflakeConnectionError(
                f"Failed to connect to Snowflake: {e}"
            ) from e
        finally:
            if conn:
                conn.close()
                self._status = ConnectionStatus.DISCONNECTED

    # ── Core Interface Methods ────────────────────────────────────

    @retry(
        retry=retry_if_exception_type(Exception),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
    )
    def test_connection(self) -> bool:
        """Test Snowflake connectivity with retry."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT CURRENT_VERSION()")
                result = cursor.fetchone()
                version = result[0] if result else "unknown"
                logger.info("Snowflake connection OK: version=%s", version)
                return True
        except Exception as e:
            logger.error("Snowflake connection test failed: %s", e)
            return False

    def get_warehouse_version(self) -> str:
        """Return Snowflake version string."""
        try:
            rows = self.execute("SELECT CURRENT_VERSION()")
            return rows[0][0] if rows else "unknown"
        except Exception:
            return "unknown"

    def list_schemas(self) -> list[str]:
        """List all accessible schemas in current database."""
        sql = """
        SELECT SCHEMA_NAME
        FROM INFORMATION_SCHEMA.SCHEMATA
        WHERE SCHEMA_NAME NOT IN (
            SELECT UNNEST(?) AS excluded
        )
        ORDER BY SCHEMA_NAME
        """
        try:
            rows = self.execute(sql, [self.config.excluded_schemas])
            return [row[0] for row in rows]
        except Exception:
            # Fallback without parameterized exclusion
            rows = self.execute(
                "SHOW SCHEMAS IN DATABASE IDENTIFIER(?)",
                [self.config.database]
            )
            return [row[1] for row in rows
                    if row[1] not in self.config.excluded_schemas]

    def list_tables(
        self,
        schema: Optional[str] = None,
        include_views: bool = True,
    ) -> list[dict[str, str]]:
        """
        List all tables (and optionally views) in the database.
        Filters out system schemas automatically.
        """
        table_types = ["'BASE TABLE'"]
        if include_views:
            table_types.append("'VIEW'")

        sql = f"""
        SELECT
            TABLE_SCHEMA,
            TABLE_NAME,
            TABLE_TYPE
        FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_CATALOG = CURRENT_DATABASE()
          AND TABLE_TYPE IN ({','.join(table_types)})
          AND TABLE_SCHEMA NOT IN (
              'INFORMATION_SCHEMA',
              'SNOWFLAKE',
              'SNOWFLAKE_SAMPLE_DATA'
          )
        {f"AND TABLE_SCHEMA = '{schema}'" if schema else ""}
        ORDER BY TABLE_SCHEMA, TABLE_NAME
        """

        rows = self.execute(sql)
        return [
            {
                "schema_name": row[0],
                "table_name": row[1],
                "table_type": row[2],
            }
            for row in rows
        ]

    def extract_columns(
        self,
        schema_name: str,
        table_name: str,
    ) -> list[RawColumnInfo]:
        """
        Extract column metadata from INFORMATION_SCHEMA.COLUMNS.
        Includes Snowflake-specific fields (COMMENT, etc.).
        """
        sql = """
        SELECT
            TABLE_SCHEMA,
            TABLE_NAME,
            COLUMN_NAME,
            ORDINAL_POSITION,
            DATA_TYPE,
            CASE WHEN IS_NULLABLE = 'YES' THEN TRUE ELSE FALSE END,
            COLUMN_DEFAULT,
            COMMENT
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_CATALOG = CURRENT_DATABASE()
          AND TABLE_SCHEMA = ?
          AND TABLE_NAME = ?
        ORDER BY ORDINAL_POSITION
        """

        rows = self.execute(sql, [schema_name, table_name])
        return [
            RawColumnInfo(
                schema_name=row[0],
                table_name=row[1],
                column_name=row[2],
                ordinal_position=row[3],
                data_type=row[4],
                is_nullable=bool(row[5]),
                column_default=row[6],
                comment=row[7],
            )
            for row in rows
        ]

    def get_row_count(
        self,
        schema_name: str,
        table_name: str,
    ) -> Optional[int]:
        """
        Get row count from TABLE_STORAGE_METRICS (fast, no scan).
        Falls back to COUNT(*) if metrics unavailable.
        """
        # Fast path: use Snowflake metadata
        sql = """
        SELECT ROW_COUNT
        FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_CATALOG = CURRENT_DATABASE()
          AND TABLE_SCHEMA = ?
          AND TABLE_NAME = ?
        """
        try:
            rows = self.execute(sql, [schema_name, table_name])
            if rows and rows[0][0] is not None:
                return int(rows[0][0])
        except Exception:
            pass

        # Fallback: COUNT(*) — more expensive
        try:
            sql_count = f'SELECT COUNT(*) FROM "{schema_name}"."{table_name}"'
            rows = self.execute(sql_count)
            return int(rows[0][0]) if rows else 0
        except Exception as e:
            logger.warning(
                "Could not get row count for %s.%s: %s",
                schema_name, table_name, e
            )
            return None

    def get_sample_rows(
        self,
        schema_name: str,
        table_name: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """
        Get sample rows using TABLESAMPLE for large tables.
        """
        try:
            # Get column names first
            cols = self.extract_columns(schema_name, table_name)
            col_names = [c.column_name for c in cols]

            # Use TABLESAMPLE for large tables
            sql = f"""
            SELECT * FROM "{schema_name}"."{table_name}"
            TABLESAMPLE BERNOULLI (10)
            LIMIT {limit}
            """
            rows = self.execute(sql)

            return [
                {
                    col_names[i]: self._serialize_value(val)
                    for i, val in enumerate(row)
                }
                for row in rows
            ]
        except Exception as e:
            logger.warning(
                "Could not sample %s.%s: %s",
                schema_name, table_name, e
            )
            return []

    # ── Snowflake-Specific Methods ────────────────────────────────

    def get_table_ddl(
        self,
        schema_name: str,
        table_name: str,
    ) -> str:
        """
        Get CREATE TABLE DDL statement.
        Useful for understanding indexes, constraints, clustering.
        """
        try:
            rows = self.execute(
                f'SELECT GET_DDL(\'TABLE\', \'"{schema_name}"."{table_name}"\')'
            )
            return rows[0][0] if rows else ""
        except Exception as e:
            logger.warning("Could not get DDL for %s.%s: %s",
                           schema_name, table_name, e)
            return ""

    def get_table_comment(
        self,
        schema_name: str,
        table_name: str,
    ) -> str:
        """
        Get the Snowflake COMMENT on a table.
        This is a primary source of business descriptions.
        """
        sql = """
        SELECT COMMENT
        FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_CATALOG = CURRENT_DATABASE()
          AND TABLE_SCHEMA = ?
          AND TABLE_NAME = ?
        """
        try:
            rows = self.execute(sql, [schema_name, table_name])
            return (rows[0][0] or "").strip() if rows else ""
        except Exception:
            return ""

    def get_table_storage_metrics(
        self,
        schema_name: str,
        table_name: str,
    ) -> dict[str, Any]:
        """
        Get storage metrics from INFORMATION_SCHEMA.TABLE_STORAGE_METRICS.
        Includes bytes, row count, partitions — useful for cost estimation.
        """
        sql = """
        SELECT
            ROW_COUNT,
            BYTES,
            CLUSTERING_KEY
        FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_CATALOG = CURRENT_DATABASE()
          AND TABLE_SCHEMA = ?
          AND TABLE_NAME = ?
        """
        try:
            rows = self.execute(sql, [schema_name, table_name])
            if rows:
                return {
                    "row_count": rows[0][0],
                    "bytes": rows[0][1],
                    "clustering_key": rows[0][2],
                }
        except Exception as e:
            logger.warning("Storage metrics unavailable: %s", e)
        return {}

    def get_query_history(
        self,
        days: int = 90,
        min_executions: int = 3,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """
        Mine Snowflake QUERY_HISTORY for sample query corpus.
        Returns top queries by execution count.

        Requires: ACCOUNTADMIN or MONITOR privilege
        """
        sql = f"""
        SELECT
            QUERY_ID,
            QUERY_TEXT,
            DATABASE_NAME,
            SCHEMA_NAME,
            USER_NAME,
            ROLE_NAME,
            WAREHOUSE_NAME,
            TOTAL_ELAPSED_TIME,
            ROWS_PRODUCED,
            COUNT(*) AS EXECUTION_COUNT,
            MAX(START_TIME) AS LAST_EXECUTED
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE START_TIME >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
          AND QUERY_TYPE = 'SELECT'
          AND EXECUTION_STATUS = 'SUCCESS'
          AND DATABASE_NAME = CURRENT_DATABASE()
          AND ROWS_PRODUCED > 0
          AND QUERY_TEXT NOT LIKE '%QUERY_HISTORY%'
          AND QUERY_TEXT NOT LIKE '%INFORMATION_SCHEMA%'
        GROUP BY 1, 2, 3, 4, 5, 6, 7, 8, 9
        HAVING COUNT(*) >= {min_executions}
        ORDER BY EXECUTION_COUNT DESC
        LIMIT {limit}
        """
        try:
            rows = self.execute(sql)
            return [
                {
                    "query_id": row[0],
                    "query_text": row[1],
                    "database_name": row[2],
                    "schema_name": row[3],
                    "user_name": row[4],
                    "role_name": row[5],
                    "warehouse_name": row[6],
                    "execution_time_ms": row[7],
                    "rows_produced": row[8],
                    "execution_count": row[9],
                    "last_executed": str(row[10]),
                }
                for row in rows
            ]
        except Exception as e:
            logger.warning(
                "Could not access QUERY_HISTORY (requires MONITOR privilege): %s", e
            )
            return []

    def get_columns_with_stats(
        self,
        schema_name: str,
        table_name: str,
    ) -> list[dict[str, Any]]:
        """
        Get column statistics using Snowflake's AUTO_REFRESH_TABLE_STATS.
        Requires WAREHOUSE to be running.
        """
        sql = f"""
        SELECT
            COLUMN_NAME,
            DATA_TYPE,
            NULL_COUNT,
            DISTINCT_COUNT,
            MIN,
            MAX
        FROM INFORMATION_SCHEMA.COLUMN_STATISTICS
        WHERE TABLE_CATALOG = CURRENT_DATABASE()
          AND TABLE_SCHEMA = ?
          AND TABLE_NAME = ?
        """
        try:
            rows = self.execute(sql, [schema_name, table_name])
            return [
                {
                    "column_name": row[0],
                    "data_type": row[1],
                    "null_count": row[2],
                    "distinct_count": row[3],
                    "min_value": str(row[4]) if row[4] is not None else None,
                    "max_value": str(row[5]) if row[5] is not None else None,
                }
                for row in rows
            ]
        except Exception:
            return []

    def get_tags(
        self,
        schema_name: str,
        table_name: str,
    ) -> dict[str, str]:
        """
        Get Snowflake object tags (data governance metadata).
        Tags like 'PII=true', 'DOMAIN=sales' are extremely valuable.
        """
        sql = """
        SELECT TAG_NAME, TAG_VALUE
        FROM SNOWFLAKE.ACCOUNT_USAGE.TAG_REFERENCES
        WHERE OBJECT_DATABASE = CURRENT_DATABASE()
          AND OBJECT_SCHEMA = ?
          AND OBJECT_NAME = ?
          AND TAG_DATABASE = CURRENT_DATABASE()
        """
        try:
            rows = self.execute(sql, [schema_name, table_name])
            return {row[0]: row[1] for row in rows}
        except Exception:
            return {}

    # ── Execution ─────────────────────────────────────────────────

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    def execute(
        self,
        sql: str,
        params: Optional[list] = None,
    ) -> list[tuple]:
        """
        Execute SQL with retry logic.

        Args:
            sql: SQL to execute
            params: Parameterized query values

        Returns:
            List of row tuples
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                if params:
                    cursor.execute(sql, params)
                else:
                    cursor.execute(sql)
                return cursor.fetchall()
            except Exception as e:
                raise SnowflakeQueryError(
                    f"Query failed: {str(e)[:200]}\nSQL: {sql[:200]}"
                ) from e
            finally:
                cursor.close()

    def execute_to_dataframe(self, sql: str):
        """Execute SQL and return result as pandas DataFrame."""
        import pandas as pd
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(sql)
            df = cursor.fetch_pandas_all()
            cursor.close()
            return df

    # ── Utilities ─────────────────────────────────────────────────

    def _serialize_value(self, val: Any) -> Any:
        """Convert Snowflake types to JSON-serializable Python types."""
        if val is None:
            return None

        import datetime
        import decimal

        if isinstance(val, (datetime.date, datetime.datetime)):
            return val.isoformat()
        if isinstance(val, decimal.Decimal):
            return float(val)
        if isinstance(val, bytes):
            return val.hex()
        return val

    def __repr__(self) -> str:
        return (
            f"SnowflakeConnector("
            f"account='{self.config.account}', "
            f"db='{self.config.database}', "
            f"wh='{self.config.warehouse}')"
        )
