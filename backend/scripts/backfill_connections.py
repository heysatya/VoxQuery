import asyncio
import os
import asyncpg
from cryptography.fernet import Fernet
from dotenv import load_dotenv


async def main():
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

    db_url = os.getenv("SUPABASE_DATABASE_URL")
    dsn = os.getenv("SNOWFLAKE_DSN")
    fernet_key = os.getenv("FERNET_KEY")

    if not db_url or not dsn or not fernet_key:
        print(
            "Missing required environment variables (SUPABASE_DATABASE_URL, SNOWFLAKE_DSN, FERNET_KEY)"
        )
        return

    f = Fernet(fernet_key.encode())
    encrypted_dsn = f.encrypt(dsn.encode()).decode()

    conn = await asyncpg.connect(db_url, statement_cache_size=0)
    try:
        # Get all tenants
        tenants = await conn.fetch("SELECT id FROM tenants")

        inserted = 0
        for tenant in tenants:
            tenant_id = tenant["id"]

            # Check if they have a connection
            has_conn = await conn.fetchrow(
                "SELECT 1 FROM tenant_connections WHERE tenant_id = $1", tenant_id
            )
            if not has_conn:
                await conn.execute(
                    """
                    INSERT INTO tenant_connections (tenant_id, snowflake_dsn)
                    VALUES ($1, $2)
                    ON CONFLICT (tenant_id) DO NOTHING
                """,
                    tenant_id,
                    encrypted_dsn,
                )
                print(f"Provisioned connection for tenant {tenant_id}")
                inserted += 1

        print(f"Successfully provisioned connections for {inserted} tenants.")

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
