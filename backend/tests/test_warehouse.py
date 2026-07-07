import pytest
from app.warehouse.snowflake import SnowflakeWarehouseConnector

@pytest.mark.asyncio
async def test_snowflake_warehouse_connector_enforces_limit():
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

