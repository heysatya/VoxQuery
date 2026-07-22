import json
import logging
import os
import uuid

from app.rag.glossary_defaults import DEFAULT_METRIC_SYNONYMS, DEFAULT_TABLE_SYNONYMS

from fastapi import APIRouter, Depends, Header, HTTPException, Request
import asyncpg

# Clerk specific imports
from svix.webhooks import Webhook, WebhookVerificationError
from clerk_backend_api import Clerk

from app.config import get_settings

router = APIRouter()
logger = logging.getLogger(__name__)


async def get_db_pool(request: Request) -> asyncpg.Pool:
    # Ensure the app state has a DB pool. In tests, we might mock this.
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        # Fallback for when the router is accessed but pool isn't attached to state (e.g. tests)
        settings = get_settings()
        if not settings.supabase_database_url:
            raise HTTPException(status_code=500, detail="Database not configured")
        pool = await asyncpg.create_pool(settings.supabase_database_url)
        request.app.state.db_pool = pool
    return pool


@router.post("/api/webhooks/clerk")
async def clerk_webhook(
    request: Request,
    svix_id: str = Header(None),
    svix_timestamp: str = Header(None),
    svix_signature: str = Header(None),
    db_pool: asyncpg.Pool = Depends(get_db_pool),
):
    if not svix_id or not svix_timestamp or not svix_signature:
        raise HTTPException(status_code=400, detail="Missing Svix headers")

    settings = get_settings()
    webhook_secret = os.getenv("CLERK_WEBHOOK_SECRET")
    
    if not webhook_secret:
        # In test mode we might not have it configured, fail gracefully or bypass if in test
        # but for production it's mandatory
        logger.error("CLERK_WEBHOOK_SECRET is not configured.")
        raise HTTPException(status_code=500, detail="Webhook secret not configured")

    payload = await request.body()
    headers = {
        "svix-id": svix_id,
        "svix-timestamp": svix_timestamp,
        "svix-signature": svix_signature,
    }

    try:
        wh = Webhook(webhook_secret)
        evt = wh.verify(payload, headers)
    except WebhookVerificationError as e:
        logger.error(f"Webhook verification failed: {e}")
        raise HTTPException(status_code=400, detail="Invalid signature")

    event_type = evt.get("type")
    data = evt.get("data", {})
    
    clerk_client = Clerk(bearer_auth=os.getenv("CLERK_SECRET_KEY", ""))

    try:
        async with db_pool.acquire() as conn:
            if event_type == "organization.created":
                org_id = data.get("id")
                name = data.get("name", "Unknown Organization")
                
                # Generate a UUID for the tenant
                new_tenant_id = uuid.uuid4()
                
                # Insert into our DB
                await conn.execute(
                    "INSERT INTO tenants (id, name) VALUES ($1, $2) ON CONFLICT (id) DO NOTHING",
                    new_tenant_id, name
                )
                
                # Patch Clerk Metadata
                if os.getenv("CLERK_SECRET_KEY"):
                    import httpx
                    async with httpx.AsyncClient() as client:
                        await client.patch(
                            f"https://api.clerk.com/v1/organizations/{org_id}",
                            headers={"Authorization": f"Bearer {os.getenv('CLERK_SECRET_KEY')}"},
                            json={"public_metadata": {"vox_tenant_id": str(new_tenant_id)}}
                        )
                # Seed the default glossary so the Admin UI shows data immediately
                # and the query rewriter has a DB row to customise rather than
                # falling back to hardcoded Python-side defaults.
                await conn.execute(
                    """
                    INSERT INTO tenant_glossary (tenant_id, metric_synonyms, table_synonyms)
                    VALUES ($1, $2::jsonb, $3::jsonb)
                    ON CONFLICT (tenant_id) DO NOTHING
                    """,
                    new_tenant_id,
                    json.dumps(DEFAULT_METRIC_SYNONYMS),
                    json.dumps(DEFAULT_TABLE_SYNONYMS),
                )
                
                if settings.snowflake_dsn and settings.fernet_key:
                    try:
                        from cryptography.fernet import Fernet
                        f = Fernet(settings.fernet_key.encode())
                        encrypted_dsn = f.encrypt(settings.snowflake_dsn.encode()).decode()
                        await conn.execute("""
                            INSERT INTO tenant_connections (tenant_id, snowflake_dsn)
                            VALUES ($1, $2)
                            ON CONFLICT (tenant_id) DO NOTHING
                        """, new_tenant_id, encrypted_dsn)
                    except Exception as e:
                        logger.error(f"Failed to seed tenant connection for {new_tenant_id}: {e}")
                logger.info(f"Provisioned new tenant: {new_tenant_id} for Clerk Org: {org_id}")

            elif event_type == "user.created":
                clerk_user_id = data.get("id")
                email_addresses = data.get("email_addresses", [])
                primary_email = f"unknown_{clerk_user_id}@example.com"
                if email_addresses:
                    primary_email = email_addresses[0].get("email_address", f"unknown_{clerk_user_id}@example.com")
                
                # Wait, what is their tenant? Users usually join orgs.
                # If they don't have an org yet, they might get a personal tenant.
                # Let's check if the user already exists by email (e.g. from a previous test run)
                existing_user = await conn.fetchrow(
                    "SELECT id, tenant_id FROM users WHERE email = $1", primary_email
                )

                if existing_user:
                    new_user_id = existing_user["id"]
                    new_tenant_id = existing_user["tenant_id"]
                    logger.info(f"User {primary_email} already exists, reusing IDs")
                else:
                    new_user_id = uuid.uuid4()
                    new_tenant_id = uuid.uuid4()
                    
                    # Insert a personal tenant
                    await conn.execute(
                        "INSERT INTO tenants (id, name) VALUES ($1, $2) ON CONFLICT (id) DO NOTHING",
                        new_tenant_id, f"Personal Tenant - {primary_email}"
                    )
                    
                    # Seed the default glossary for this personal tenant
                    await conn.execute(
                        """
                        INSERT INTO tenant_glossary (tenant_id, metric_synonyms, table_synonyms)
                        VALUES ($1, $2::jsonb, $3::jsonb)
                        ON CONFLICT (tenant_id) DO NOTHING
                        """,
                        new_tenant_id,
                        json.dumps(DEFAULT_METRIC_SYNONYMS),
                        json.dumps(DEFAULT_TABLE_SYNONYMS),
                    )
                    
                    if settings.snowflake_dsn and settings.fernet_key:
                        try:
                            from cryptography.fernet import Fernet
                            f = Fernet(settings.fernet_key.encode())
                            encrypted_dsn = f.encrypt(settings.snowflake_dsn.encode()).decode()
                            await conn.execute("""
                                INSERT INTO tenant_connections (tenant_id, snowflake_dsn)
                                VALUES ($1, $2)
                                ON CONFLICT (tenant_id) DO NOTHING
                            """, new_tenant_id, encrypted_dsn)
                        except Exception as e:
                            logger.error(f"Failed to seed tenant connection for {new_tenant_id}: {e}")
                    
                    # Insert the user
                    await conn.execute(
                        "INSERT INTO users (id, tenant_id, email, role) VALUES ($1, $2, $3, 'admin') ON CONFLICT (email) DO NOTHING",
                        new_user_id, new_tenant_id, primary_email
                    )
                
                # Patch Clerk Metadata
                if os.getenv("CLERK_SECRET_KEY"):
                    import httpx
                    async with httpx.AsyncClient() as client:
                        await client.patch(
                            f"https://api.clerk.com/v1/users/{clerk_user_id}/metadata",
                            headers={"Authorization": f"Bearer {os.getenv('CLERK_SECRET_KEY')}"},
                            json={"public_metadata": {"vox_user_id": str(new_user_id), "vox_tenant_id": str(new_tenant_id)}}
                        )
                logger.info(f"Provisioned new user: {new_user_id} for Clerk User: {clerk_user_id}")

    except Exception:
        logger.exception("Error processing webhook")
        raise HTTPException(status_code=500, detail="Internal processing error")

    return {"status": "success"}
