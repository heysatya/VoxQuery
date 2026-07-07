import pytest
from unittest.mock import patch, MagicMock
from app.warehouse.snowflake import SnowflakeWarehouseConnector

@pytest.mark.asyncio
@patch("app.warehouse.snowflake.snowflake.connector.connect")
async def test_snowflake_warehouse_connector_enforces_limit(mock_connect):
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_connect.return_value = mock_conn
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value = mock_cursor
    mock_cursor.__enter__.return_value = mock_cursor
    
    connector = SnowflakeWarehouseConnector(dsn="dummy")

    # 1. No limit -> adds 10000
    await connector.execute_readonly("SELECT * FROM test", snowflake_role="test")
    assert "LIMIT 10000" in connector.last_sql.upper()

    # 2. Limit < 10000 -> keeps existing limit
    await connector.execute_readonly("SELECT * FROM test LIMIT 50", snowflake_role="test")
    assert "LIMIT 50" in connector.last_sql.upper()

    # 3. Limit > 10000 -> clamps to 10000
    await connector.execute_readonly("SELECT * FROM test LIMIT 15000", snowflake_role="test")
    assert "LIMIT 10000" in connector.last_sql.upper()

    # 4. CTE with limit > 10000 -> adds main limit 10000
    await connector.execute_readonly("WITH t AS (SELECT * FROM a LIMIT 15000) SELECT * FROM t", snowflake_role="test")
    assert connector.last_sql.endswith("LIMIT 10000")

@pytest.mark.asyncio
@patch("app.warehouse.snowflake.snowflake.connector.connect")
async def test_snowflake_warehouse_connector_executes_real_query(mock_connect):
    # Setup mock
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_connect.return_value = mock_conn
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value = mock_cursor
    mock_cursor.__enter__.return_value = mock_cursor
    
    # Mock row description and fetchall
    mock_cursor.description = [("REGION",), ("REVENUE",)]
    mock_cursor.fetchall.return_value = [("North America", 1000)]
    mock_cursor.rowcount = 1
    
    dsn = "user:pass@account/db/schema"
    connector = SnowflakeWarehouseConnector(dsn=dsn)
    
    result_payload, result_shape = await connector.execute_readonly("SELECT region, revenue FROM sales", snowflake_role="test_role")
    
    # Assert connection was made with right parameters
    mock_connect.assert_called_once()
    # It should pass the role, we check the kwargs
    kwargs = mock_connect.call_args.kwargs
    assert kwargs.get("role") == "test_role"
    
    # Assert query was executed and results parsed correctly
    mock_cursor.execute.assert_called_once()
    assert result_payload.columns == ["region", "revenue"]
    assert result_payload.rows == [["North America", 1000]]
    assert result_payload.row_count == 1
