"""
connection.py
─────────────
DuckDB connection manager.

Design decisions:
- Context manager pattern for safe resource cleanup
- Configurable read-only mode for production safety
- Thread-local connections for concurrent usage
- Automatic memory and thread configuration
"""

import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Optional

import duckdb

from app.config import settings


class DuckDBConnectionError(Exception):
    """Raised when DuckDB connection fails."""
    pass


class DuckDBConnectionManager:
    """
    Manages DuckDB connections with thread safety.

    Usage:
        manager = DuckDBConnectionManager()

        # Context manager (recommended)
        with manager.get_connection() as conn:
            result = conn.execute("SELECT 1").fetchall()

        # Direct execute helper
        rows = manager.execute("SELECT COUNT(*) FROM orders")
        df = manager.query_df("SELECT * FROM orders LIMIT 10")
    """

    def __init__(
        self,
        db_path: Optional[str] = None,
        read_only: bool = False,
    ):
        self.db_path = db_path or settings.duckdb_path
        self.read_only = read_only or settings.duckdb_read_only
        self._local = threading.local()
        self._lock = threading.Lock()

        # Ensure the database file directory exists
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

    def _create_connection(self) -> duckdb.DuckDBPyConnection:
        """Create a new configured DuckDB connection."""
        try:
            conn = duckdb.connect(
                database=self.db_path,
                read_only=self.read_only,
            )

            # Configure memory and threading
            conn.execute(f"SET memory_limit='{settings.duckdb_max_memory}'")
            conn.execute(f"SET threads={settings.duckdb_threads}")

            return conn

        except Exception as e:
            raise DuckDBConnectionError(
                f"Failed to connect to DuckDB at '{self.db_path}': {e}"
            ) from e

    @contextmanager
    def get_connection(self) -> Generator[duckdb.DuckDBPyConnection, None, None]:
        """
        Context manager that provides a DuckDB connection.
        Creates a new connection each time (DuckDB is lightweight).

        Example:
            with manager.get_connection() as conn:
                rows = conn.execute("SELECT 1").fetchall()
        """
        conn = self._create_connection()
        try:
            yield conn
        finally:
            conn.close()

    def execute(self, sql: str, params: Optional[list] = None) -> list:
        """
        Execute a SQL query and return all rows as a list of tuples.

        Args:
            sql: SQL query string
            params: Optional list of parameters for parameterized queries

        Returns:
            List of row tuples
        """
        with self.get_connection() as conn:
            if params:
                return conn.execute(sql, params).fetchall()
            return conn.execute(sql).fetchall()

    def execute_one(self, sql: str, params: Optional[list] = None):
        """Execute and return the first row, or None."""
        with self.get_connection() as conn:
            if params:
                result = conn.execute(sql, params).fetchone()
            else:
                result = conn.execute(sql).fetchone()
            return result

    def query_df(self, sql: str):
        """
        Execute a SQL query and return result as pandas DataFrame.

        Returns:
            pandas.DataFrame
        """
        with self.get_connection() as conn:
            return conn.execute(sql).df()

    def test_connection(self) -> bool:
        """
        Test that the connection works.

        Returns:
            True if connection is healthy
        """
        try:
            result = self.execute("SELECT 1 AS test")
            return result[0][0] == 1
        except Exception:
            return False

    def get_duckdb_version(self) -> str:
        """Get the DuckDB version string."""
        result = self.execute_one("SELECT version()")
        return result[0] if result else "unknown"

    def __repr__(self) -> str:
        return (
            f"DuckDBConnectionManager("
            f"db_path='{self.db_path}', "
            f"read_only={self.read_only})"
        )
