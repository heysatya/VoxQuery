"""
Phase 5.1 — Snowflake tenant/workspace wiring tests.

Verifies:
  1. connector receives tenant DSN, not hardcoded dummy
  2. role passthrough reaches the connector connect() call
  3. non-SELECT is rejected before connector call (sql_policy + connector)
  4. timeout returns structured warehouse timeout error (DSN redacted)
  5. DSN credentials are redacted in errors/logs
  6. Empty DSN is rejected at construction
  7. Canonical SQL is enforced before connection opens
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import snowflake.connector as sf_connector

from app.models.contracts import SchemaTable, ColumnInfo
from app.warehouse.sql_policy import SqlPolicyError, canonicalize_readonly_sql, build_allowlist, SchemaAllowlist
from app.warehouse.snowflake import SnowflakeWarehouseConnector, _redact_dsn


# ── sql_policy tests ──────────────────────────────────────────────────────────

def test_canonicalize_readonly_sql_applies_row_limit_policy():
    no_limit = canonicalize_readonly_sql("SELECT * FROM test")
    assert no_limit.sql == "SELECT * FROM test LIMIT 10000"
    assert no_limit.limit_added is True
    assert no_limit.limit_clamped is False

    small_limit = canonicalize_readonly_sql("SELECT * FROM test LIMIT 50")
    assert small_limit.sql == "SELECT * FROM test LIMIT 50"
    assert small_limit.limit_added is False
    assert small_limit.limit_clamped is False

    oversized_limit = canonicalize_readonly_sql("SELECT * FROM test LIMIT 15000")
    assert oversized_limit.sql == "SELECT * FROM test LIMIT 10000"
    assert oversized_limit.limit_added is False
    assert oversized_limit.limit_clamped is True

    cte = canonicalize_readonly_sql("WITH t AS (SELECT * FROM a LIMIT 15000) SELECT * FROM t")
    assert cte.sql == "WITH t AS (SELECT * FROM a LIMIT 15000) SELECT * FROM t LIMIT 10000"
    assert cte.limit_added is True


def test_schema_allowlist_validation_success():
    schema = [
        SchemaTable(table_name="orders", columns=[ColumnInfo(name="id", data_type="int"), ColumnInfo(name="amount", data_type="float")])
    ]
    allowlist = build_allowlist(schema)
    
    # Valid query
    sql = "SELECT id, amount FROM orders"
    res = canonicalize_readonly_sql(sql, allowlist=allowlist)
    assert res.sql.startswith("SELECT id, amount FROM orders")

def test_schema_allowlist_unknown_table():
    schema = [SchemaTable(table_name="orders", columns=[ColumnInfo(name="id", data_type="int")])]
    allowlist = build_allowlist(schema)
    
    with pytest.raises(SqlPolicyError, match="isn't part of the connected schema"):
        canonicalize_readonly_sql("SELECT id FROM users", allowlist=allowlist)

def test_schema_allowlist_unknown_column():
    schema = [SchemaTable(table_name="orders", columns=[ColumnInfo(name="id", data_type="int")])]
    allowlist = build_allowlist(schema)
    
    with pytest.raises(SqlPolicyError, match="doesn't exist in the connected schema"):
        canonicalize_readonly_sql("SELECT fake_col FROM orders", allowlist=allowlist)


def test_canonicalize_readonly_sql_allows_set_operations():
    # Union
    res = canonicalize_readonly_sql("SELECT id FROM a UNION SELECT id FROM b")
    assert "LIMIT 10000" in res.sql
    assert "UNION" in res.sql
    
    # Intersect
    res = canonicalize_readonly_sql("SELECT id FROM a INTERSECT SELECT id FROM b")
    assert "INTERSECT" in res.sql

    # Except
    res = canonicalize_readonly_sql("SELECT id FROM a EXCEPT SELECT id FROM b")
    assert "EXCEPT" in res.sql


def test_canonicalize_readonly_sql_rejects_non_select():
    with pytest.raises(SqlPolicyError):
        canonicalize_readonly_sql("DELETE FROM test")
    
    with pytest.raises(SqlPolicyError):
        canonicalize_readonly_sql("SELECT id FROM a UNION DELETE FROM b")


def test_canonicalize_readonly_sql_rejects_explicit_cross_join():
    with pytest.raises(SqlPolicyError, match="CROSS JOIN"):
        canonicalize_readonly_sql("SELECT * FROM orders CROSS JOIN customers")


def test_canonicalize_readonly_sql_rejects_join_without_condition():
    with pytest.raises(SqlPolicyError, match="without an ON or USING"):
        canonicalize_readonly_sql("SELECT * FROM orders JOIN customers")


# ── Phase 5.1: DSN redaction ──────────────────────────────────────────────────

def test_redact_dsn_hides_password():
    """5. DSN credentials are redacted in errors/logs."""
    dsn = "snowflake://myuser:supersecretpassword@account123/mydb/myschema"
    redacted = _redact_dsn(dsn)
    assert "supersecretpassword" not in redacted
    assert "myuser" in redacted
    assert "account123" in redacted


def test_redact_dsn_dsn_without_password():
    dsn = "snowflake://myuser@account123"
    redacted = _redact_dsn(dsn)
    assert "myuser" in redacted


# ── Phase 5.1: Empty DSN rejected at construction ────────────────────────────

def test_snowflake_connector_rejects_empty_dsn():
    """6. Connector must not accept an empty or None DSN."""
    with pytest.raises(ValueError, match="must not be empty"):
        SnowflakeWarehouseConnector(dsn="")


def test_snowflake_connector_parses_dsn_with_complex_password():
    connector = SnowflakeWarehouseConnector(dsn="snowflake://myuser:complex@pass@word@myaccount/mydb/myschema")
    parsed = connector._parse_dsn()
    assert parsed["user"] == "myuser"
    assert parsed["password"] == "complex@pass@word"
    assert parsed["account"] == "myaccount"
    assert parsed["database"] == "mydb"
    assert parsed["schema"] == "myschema"


# ── Phase 5.1: Non-SELECT rejected before connector call ─────────────────────

@pytest.mark.asyncio
@patch("app.warehouse.snowflake.snowflake.connector.connect")
async def test_snowflake_warehouse_connector_rejects_noncanonical_sql(mock_connect):
    """3 (original) + 7. Canonical SQL enforced; connector never opens for noncanonical SQL."""
    connector = SnowflakeWarehouseConnector(dsn="snowflake://user:pass@account/db")

    with pytest.raises(SqlPolicyError):
        await connector.execute_readonly("SELECT * FROM test", snowflake_role="test")

    mock_connect.assert_not_called()


# ── Phase 5.1: Role passthrough + real query execution ──────────────────────

@pytest.mark.asyncio
@patch("app.warehouse.snowflake.snowflake.connector.connect")
async def test_snowflake_warehouse_connector_passes_role_to_connect(mock_connect):
    """2. Role passthrough reaches connector."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_connect.return_value.__enter__ = lambda s: mock_conn
    mock_connect.return_value.__exit__ = MagicMock(return_value=False)
    mock_conn.cursor.return_value.__enter__ = lambda s: mock_cursor
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

    mock_cursor.description = [("REGION",), ("REVENUE",)]
    mock_cursor.fetchall.return_value = [("North America", 1000)]
    mock_cursor.rowcount = 1

    dsn = "snowflake://user:pass@account/db/schema"
    connector = SnowflakeWarehouseConnector(dsn=dsn)

    result_payload, result_shape = await connector.execute_readonly(
        "SELECT region, revenue FROM sales LIMIT 10000",
        snowflake_role="analyst_role"
    )

    mock_connect.assert_called_once()
    kwargs = mock_connect.call_args.kwargs
    # 2. Role passthrough verified
    assert kwargs.get("role") == "analyst_role"
    # 1. Tenant DSN fields used, not a hardcoded dummy
    assert kwargs.get("user") == "user"
    assert kwargs.get("account") == "account"
    assert kwargs.get("database") == "db"
    assert kwargs.get("schema") == "schema"
    # Timeout params present
    assert "login_timeout" in kwargs
    assert "network_timeout" in kwargs

    assert result_payload.columns == ["region", "revenue"]
    assert result_payload.rows == [["North America", 1000]]
    assert result_payload.row_count == 1


@pytest.mark.asyncio
@patch("app.warehouse.snowflake.snowflake.connector.connect")
async def test_snowflake_warehouse_connector_executes_real_query(mock_connect):
    """1. Connector receives tenant DSN, not hardcoded dummy DSN."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_connect.return_value.__enter__ = lambda s: mock_conn
    mock_connect.return_value.__exit__ = MagicMock(return_value=False)
    mock_conn.cursor.return_value.__enter__ = lambda s: mock_cursor
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

    mock_cursor.description = [("REGION",), ("REVENUE",)]
    mock_cursor.fetchall.return_value = [("North America", 1000)]
    mock_cursor.rowcount = 1

    dsn = "snowflake://user:pass@account/db/schema"
    connector = SnowflakeWarehouseConnector(dsn=dsn)

    result_payload, _ = await connector.execute_readonly(
        "SELECT region, revenue FROM sales LIMIT 10000",
        snowflake_role="test_role"
    )

    mock_connect.assert_called_once()
    kwargs = mock_connect.call_args.kwargs
    assert kwargs.get("role") == "test_role"
    mock_cursor.execute.assert_called_once()
    assert mock_cursor.execute.call_args.args[0] == "SELECT region, revenue FROM sales LIMIT 10000"
    assert result_payload.columns == ["region", "revenue"]
    assert result_payload.rows == [["North America", 1000]]
    assert result_payload.row_count == 1


# ── Phase 5.1: Timeout returns structured error with redacted DSN ─────────────

@pytest.mark.asyncio
async def test_snowflake_connector_timeout_returns_structured_error():
    """4. Timeout returns structured warehouse timeout error (DSN redacted)."""
    connector = SnowflakeWarehouseConnector(
        dsn="snowflake://admin:topsecret@acme-account/production/public",
        timeout_seconds=1
    )

    # Simulate a blocking call that exceeds the timeout
    async def slow_execute(*args, **kwargs):
        await asyncio.sleep(10)

    with patch("asyncio.to_thread", new=AsyncMock(side_effect=asyncio.TimeoutError())):
        with pytest.raises(RuntimeError) as exc_info:
            await connector.execute_readonly(
                "SELECT region, revenue FROM sales LIMIT 10000",
                snowflake_role="analyst"
            )

    error_msg = str(exc_info.value)
    # Error message must mention timeout
    assert "timed out" in error_msg.lower()
    # Error message must NOT contain the raw password
    assert "topsecret" not in error_msg


# ── Phase 5.1: DSN redacted in connector error output ─────────────────────────

@pytest.mark.asyncio
@patch("app.warehouse.snowflake.snowflake.connector.connect")
async def test_snowflake_connector_dsn_redacted_in_errors(mock_connect):
    """5. DSN is redacted in errors/logs (password not in error message)."""
    mock_connect.side_effect = sf_connector.errors.OperationalError("network error")

    connector = SnowflakeWarehouseConnector(
        dsn="snowflake://prod_user:highly_secret_pw@acme.snowflakecomputing.com/prod/analytics"
    )

    with pytest.raises(RuntimeError) as exc_info:
        await connector.execute_readonly(
            "SELECT * FROM orders LIMIT 10000",
            snowflake_role="readonly_role"
        )

    error_msg = str(exc_info.value)
    assert "highly_secret_pw" not in error_msg
    assert "prod_user" in error_msg  # user prefix is preserved for debugging

@patch("app.warehouse.snowflake.snowflake.connector.connect")
def test_snowflake_connector_fetch_schema_snapshot(mock_connect):
    """Test that schema fetching parses results correctly."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_connect.return_value.__enter__ = lambda s: mock_conn
    mock_connect.return_value.__exit__ = MagicMock(return_value=False)
    mock_conn.cursor.return_value.__enter__ = lambda s: mock_cursor
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

    # Return mock information_schema.columns data
    mock_cursor.fetchall.return_value = [
        ("ORDERS", "ID", "NUMBER"),
        ("ORDERS", "AMOUNT", "FLOAT"),
        ("USERS", "EMAIL", "VARCHAR")
    ]

    connector = SnowflakeWarehouseConnector(dsn="snowflake://user:pass@account/db/schema")
    schema_tables = connector.fetch_schema_snapshot()

    assert len(schema_tables) == 2
    orders_table = next(t for t in schema_tables if t.table_name == "ORDERS")
    assert len(orders_table.columns) == 2
    assert orders_table.columns[0].name == "ID"
    
    users_table = next(t for t in schema_tables if t.table_name == "USERS")
    assert len(users_table.columns) == 1
    assert users_table.columns[0].name == "EMAIL"


def test_snowflake_pool_reuses_connection():
    """Pool returns the same connection object on repeated calls from same thread."""
    from unittest.mock import MagicMock, patch
    from app.warehouse.snowflake import SnowflakeConnectionPool

    params = {"user": "u", "password": "p", "account": "a"}
    pool = SnowflakeConnectionPool(conn_params=params, pool_size=1)

    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__ = lambda s: s
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    mock_conn.cursor.return_value.execute.return_value = None

    with patch("snowflake.connector.connect", return_value=mock_conn) as mock_connect:
        conn1 = pool._get_connection()
        conn2 = pool._get_connection()  # second call — must NOT reconnect
        assert conn1 is conn2
        assert mock_connect.call_count == 1  # connected once only


def test_snowflake_pool_reconnects_on_heartbeat_failure():
    """Pool creates a new connection when the heartbeat SELECT 1 fails."""
    from unittest.mock import MagicMock, patch, call
    from app.warehouse.snowflake import SnowflakeConnectionPool

    params = {"user": "u", "password": "p", "account": "a"}
    pool = SnowflakeConnectionPool(conn_params=params, pool_size=1)

    bad_conn = MagicMock()
    bad_cursor = MagicMock()
    bad_cursor.execute.side_effect = Exception("session expired")
    bad_conn.cursor.return_value = bad_cursor

    good_conn = MagicMock()
    good_cursor = MagicMock()
    good_cursor.execute.return_value = None
    good_conn.cursor.return_value = good_cursor

    with patch("snowflake.connector.connect", return_value=good_conn) as mock_connect:
        # Force bad_conn into the thread-local
        pool._local.conn = bad_conn
        # Next call should detect heartbeat failure and reconnect
        result = pool._get_connection()
        assert result is good_conn
        assert mock_connect.call_count == 1  # reconnect triggered once
