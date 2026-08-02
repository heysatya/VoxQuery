import asyncio
import pytest
from uuid import uuid4
from cryptography.fernet import Fernet
from unittest.mock import patch, MagicMock, AsyncMock

from app.config import get_settings
from app.warehouse.routing import TenantRoutingWarehouseConnector
from app.warehouse.snowflake import SnowflakeWarehouseConnector


# Dummy settings to avoid side effects
class DummySettings:
    fernet_key = Fernet.generate_key().decode()
    snowflake_dsn = None
    postgres_dsn = "postgresql://postgres:postgres@localhost:5432/voxquery_test"


@pytest.fixture
def mock_db_pool():
    pool = MagicMock()
    # Mocks will be set per test
    return pool


@pytest.mark.asyncio
async def test_sec_1_dsn_encrypted_at_rest(mock_db_pool):
    """SEC-1: DSN is encrypted at rest and decryptable by the app layer."""
    settings = DummySettings()
    fernet = Fernet(settings.fernet_key.encode())

    tenant_id = uuid4()
    plaintext_dsn = "snowflake://user:pass@account/db/schema"

    # 1. Write the DSN through the app layer (simulate sync_schema behavior)
    encrypted_dsn = fernet.encrypt(plaintext_dsn.encode()).decode()

    # Assert it does NOT match plaintext
    assert encrypted_dsn != plaintext_dsn
    assert "snowflake://" not in encrypted_dsn

    # Mock the DB returning the encrypted DSN
    mock_conn = AsyncMock()
    mock_conn.fetchrow.return_value = {"snowflake_dsn": encrypted_dsn}

    class MockAcquireContext:
        async def __aenter__(self):
            return mock_conn

        async def __aexit__(self, exc_type, exc, tb):
            pass

    mock_db_pool.acquire.return_value = MockAcquireContext()

    # 3. Read it back through the app layer and assert it matches (round-trip correctness)
    routing_connector = TenantRoutingWarehouseConnector(settings=settings, db_pool=mock_db_pool)
    resolved_connector = await routing_connector._get_connector(tenant_id)

    assert isinstance(resolved_connector, SnowflakeWarehouseConnector)
    assert resolved_connector.dsn == plaintext_dsn

    # Verify the SQL was called correctly
    mock_conn.fetchrow.assert_called_once_with(
        "SELECT snowflake_dsn FROM tenant_connections WHERE tenant_id = $1", tenant_id
    )


@pytest.mark.asyncio
async def test_sec_2_per_tenant_routing(mock_db_pool):
    """SEC-2: Wire per-tenant DSN routing. Two tenants get correct DSNs."""
    settings = DummySettings()
    fernet = Fernet(settings.fernet_key.encode())

    tenant1_id = uuid4()
    tenant2_id = uuid4()

    dsn1 = "snowflake://tenant1:pass1@account1/db1/schema1"
    dsn2 = "snowflake://tenant2:pass2@account2/db2/schema2"

    enc1 = fernet.encrypt(dsn1.encode()).decode()
    enc2 = fernet.encrypt(dsn2.encode()).decode()

    # We will mock fetchrow to return based on tenant_id
    async def mock_fetchrow(query, tenant_id):
        if tenant_id == tenant1_id:
            return {"snowflake_dsn": enc1}
        elif tenant_id == tenant2_id:
            return {"snowflake_dsn": enc2}
        return None

    mock_conn = AsyncMock()
    mock_conn.fetchrow.side_effect = mock_fetchrow

    class MockAcquireContext:
        async def __aenter__(self):
            return mock_conn

        async def __aexit__(self, exc_type, exc, tb):
            pass

    mock_db_pool.acquire.return_value = MockAcquireContext()

    routing_connector = TenantRoutingWarehouseConnector(settings=settings, db_pool=mock_db_pool)

    # Run pipeline for tenant 1
    connector1 = await routing_connector._get_connector(tenant1_id)
    assert connector1.dsn == dsn1

    # Run pipeline for tenant 2
    connector2 = await routing_connector._get_connector(tenant2_id)
    assert connector2.dsn == dsn2

    # Assert cache is hit next time (acquire not called again for the same tenant)
    mock_db_pool.acquire.reset_mock()
    connector1_cached = await routing_connector._get_connector(tenant1_id)
    assert connector1_cached is connector1
    mock_db_pool.acquire.assert_not_called()


@pytest.mark.asyncio
async def test_sec_3_cache_ttl_expiry(mock_db_pool):
    """SEC-3: Connector cache expires after 1 hour."""
    from datetime import datetime, UTC, timedelta

    settings = DummySettings()
    fernet = Fernet(settings.fernet_key.encode())

    tenant_id = uuid4()
    dsn = "snowflake://tenant:pass@account/db/schema"
    encrypted_dsn = fernet.encrypt(dsn.encode()).decode()

    mock_conn = AsyncMock()
    mock_conn.fetchrow.return_value = {"snowflake_dsn": encrypted_dsn}

    class MockAcquireContext:
        async def __aenter__(self):
            return mock_conn

        async def __aexit__(self, exc_type, exc, tb):
            pass

    mock_db_pool.acquire.return_value = MockAcquireContext()

    routing_connector = TenantRoutingWarehouseConnector(settings=settings, db_pool=mock_db_pool)

    # 1. Initial fetch
    await routing_connector._get_connector(tenant_id)
    assert mock_conn.fetchrow.call_count == 1

    # 2. Cached fetch (within TTL)
    await routing_connector._get_connector(tenant_id)
    assert mock_conn.fetchrow.call_count == 1

    # 3. Simulate expiry by modifying the cache timestamp
    connector, cached_at = routing_connector._cache[tenant_id]
    routing_connector._cache[tenant_id] = (connector, cached_at - timedelta(hours=2))

    # 4. Fetch after expiry
    await routing_connector._get_connector(tenant_id)
    assert mock_conn.fetchrow.call_count == 2


@pytest.mark.asyncio
async def test_is_provisioned_true_for_valid_dsn(mock_db_pool):
    """is_provisioned() returns True when a tenant has a valid, decryptable DSN."""
    settings = DummySettings()
    fernet = Fernet(settings.fernet_key.encode())

    tenant_id = uuid4()
    encrypted_dsn = fernet.encrypt(b"snowflake://user:pass@account/db/schema").decode()

    mock_conn = AsyncMock()
    mock_conn.fetchrow.return_value = {"snowflake_dsn": encrypted_dsn}

    class MockAcquireContext:
        async def __aenter__(self):
            return mock_conn

        async def __aexit__(self, exc_type, exc, tb):
            pass

    mock_db_pool.acquire.return_value = MockAcquireContext()

    routing_connector = TenantRoutingWarehouseConnector(settings=settings, db_pool=mock_db_pool)
    assert await routing_connector.is_provisioned(tenant_id) is True


@pytest.mark.asyncio
async def test_is_provisioned_false_when_no_row(mock_db_pool):
    """is_provisioned() returns False for a tenant with no tenant_connections row —
    this is the exact bug class that produced 'No warehouse connection configured'."""
    settings = DummySettings()

    mock_conn = AsyncMock()
    mock_conn.fetchrow.return_value = None

    class MockAcquireContext:
        async def __aenter__(self):
            return mock_conn

        async def __aexit__(self, exc_type, exc, tb):
            pass

    mock_db_pool.acquire.return_value = MockAcquireContext()

    routing_connector = TenantRoutingWarehouseConnector(settings=settings, db_pool=mock_db_pool)
    assert await routing_connector.is_provisioned(uuid4()) is False


@pytest.mark.asyncio
async def test_is_provisioned_false_on_decrypt_failure(mock_db_pool):
    """is_provisioned() returns False when the stored DSN fails to decrypt under
    the currently-configured FERNET_KEY (e.g. a key rotation, or a DSN encrypted
    with a different key) — not just when the row is entirely missing."""
    settings = DummySettings()
    # Encrypt with a DIFFERENT key than the one the connector will use to decrypt.
    other_key_fernet = Fernet(Fernet.generate_key())
    encrypted_with_wrong_key = other_key_fernet.encrypt(
        b"snowflake://user:pass@account/db/schema"
    ).decode()

    mock_conn = AsyncMock()
    mock_conn.fetchrow.return_value = {"snowflake_dsn": encrypted_with_wrong_key}

    class MockAcquireContext:
        async def __aenter__(self):
            return mock_conn

        async def __aexit__(self, exc_type, exc, tb):
            pass

    mock_db_pool.acquire.return_value = MockAcquireContext()

    routing_connector = TenantRoutingWarehouseConnector(settings=settings, db_pool=mock_db_pool)
    assert await routing_connector.is_provisioned(uuid4()) is False


@pytest.mark.asyncio
async def test_is_provisioned_true_in_dev_fallback_mode(mock_db_pool):
    """When no FERNET_KEY is configured (dev/test fallback), a shared
    snowflake_dsn on settings counts as provisioned for any tenant."""

    class DevSettings:
        fernet_key = None
        snowflake_dsn = "snowflake://dev:dev@account/db/schema"
        postgres_dsn = "postgresql://postgres:postgres@localhost:5432/voxquery_test"

    routing_connector = TenantRoutingWarehouseConnector(
        settings=DevSettings(), db_pool=mock_db_pool
    )
    assert await routing_connector.is_provisioned(uuid4()) is True
    mock_db_pool.acquire.assert_not_called()
