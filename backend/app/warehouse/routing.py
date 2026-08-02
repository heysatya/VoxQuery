import logging
from datetime import UTC, datetime, timedelta

_CACHE_TTL = timedelta(hours=1)

import asyncpg
from cryptography.fernet import Fernet

from app.config import Settings
from app.models.contracts import ResultPayload, ResultShape, SchemaTable
from app.warehouse.connector import WarehouseConnector
from app.warehouse.snowflake import SnowflakeConnectionPool, SnowflakeWarehouseConnector

logger = logging.getLogger(__name__)

class TenantRoutingWarehouseConnector(WarehouseConnector):
    def __init__(self, settings: Settings, db_pool: asyncpg.Pool, sf_pool: SnowflakeConnectionPool | None = None):
        self.settings = settings
        self.db_pool = db_pool
        # A SnowflakeConnectionPool owns credentials/connection parameters and
        # therefore cannot be shared across tenant DSNs. Keep the argument for
        # compatibility with existing callers, but never use a global pool for
        # tenant-routed connections.
        self.sf_pool = None
        self.fernet = Fernet(settings.fernet_key.encode()) if settings.fernet_key else None
        self._cache: dict[str, tuple[WarehouseConnector, datetime]] = {}

    async def _get_connector(self, tenant_id: str) -> WarehouseConnector:
        if tenant_id in self._cache:
            connector, cached_at = self._cache[tenant_id]
            if datetime.now(UTC) - cached_at < _CACHE_TTL:
                return connector

        if not self.fernet:
            # Fallback for dev/test mode if no encryption configured
            if self.settings.snowflake_dsn and getattr(self.settings, "app_env", "development") in {"development", "test"}:
                connector = SnowflakeWarehouseConnector(dsn=self.settings.snowflake_dsn)
                self._cache[tenant_id] = (connector, datetime.now(UTC))
                return connector
            raise RuntimeError("FERNET_KEY is required to decrypt tenant warehouse configurations.")

        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT snowflake_dsn FROM tenant_connections WHERE tenant_id = $1",
                tenant_id,
            )

        if not row:
            raise RuntimeError(f"No warehouse connection configured for tenant {tenant_id}")

        try:
            encrypted_dsn = row["snowflake_dsn"]
            decrypted_dsn = self.fernet.decrypt(encrypted_dsn.encode()).decode()
        except Exception as e:
            logger.error(f"Failed to decrypt DSN for tenant {tenant_id}: {e}")
            raise RuntimeError("Failed to decrypt warehouse connection configuration.") from e

        # The decrypted DSN is tenant-specific. Never attach a pool created
        # from another tenant's DSN or from a global SNOWFLAKE_DSN.
        connector = SnowflakeWarehouseConnector(dsn=decrypted_dsn)
        self._cache[tenant_id] = (connector, datetime.now(UTC))
        return connector

    async def is_provisioned(self, tenant_id: str) -> bool:
        """Cheap-ish existence/validity check used as a login-time guard, so an
        unprovisioned or misconfigured tenant is rejected with a clear message
        before they reach the pipeline, rather than failing five steps deep in
        execution_node. Reuses _get_connector so it catches both a missing
        tenant_connections row AND a DSN that fails to decrypt (e.g. FERNET_KEY
        mismatch) — it does not open a network connection to Snowflake itself,
        so it stays cheap even though it exercises the full resolution path."""
        try:
            await self._get_connector(tenant_id)
            return True
        except RuntimeError:
            return False

    async def execute_readonly(
        self, sql: str, *, snowflake_role: str, tenant_id: str | None = None
    ) -> tuple[ResultPayload, ResultShape]:
        if not tenant_id:
            raise ValueError("tenant_id is required for TenantRoutingWarehouseConnector")
        connector = await self._get_connector(tenant_id)
        return await connector.execute_readonly(sql, snowflake_role=snowflake_role, tenant_id=tenant_id)

    def fetch_schema_snapshot(self, tenant_id: str | None = None) -> list[SchemaTable]:
        if not tenant_id:
            raise ValueError("tenant_id is required for TenantRoutingWarehouseConnector")
            
        # Since fetch_schema_snapshot is synchronous, we cannot easily await _get_connector here.
        # But this is only used by sync_schema.py, which uses SnowflakeWarehouseConnector directly.
        # So we can just raise NotImplementedError.
        raise NotImplementedError("fetch_schema_snapshot is not supported via routing connector.")

