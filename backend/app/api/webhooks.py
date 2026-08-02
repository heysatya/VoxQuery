import json
import logging
import os

from fastapi import APIRouter, Depends, Header, HTTPException, Request
import asyncpg
from svix.webhooks import Webhook, WebhookVerificationError

from app.config import get_settings
from app.rag.glossary_defaults import DEFAULT_METRIC_SYNONYMS, DEFAULT_TABLE_SYNONYMS

router = APIRouter()
logger = logging.getLogger(__name__)


async def get_db_pool(request: Request) -> asyncpg.Pool:
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        settings = get_settings()
        if not settings.supabase_database_url:
            raise HTTPException(status_code=500, detail="Database not configured")
        pool = await asyncpg.create_pool(settings.supabase_database_url)
        request.app.state.db_pool = pool
    return pool


def _normalize_role(role_val: str | None) -> str:
    if not role_val:
        return "viewer"
    r = str(role_val).lower()
    if r in {"admin", "org:admin"}:
        return "admin"
    return "viewer"


def _extract_user_id(data: dict) -> str | None:
    pub = data.get("public_user_data")
    if isinstance(pub, dict):
        uid = pub.get("user_id") or pub.get("userId") or pub.get("id")
        if uid:
            return str(uid)
    uid = data.get("user_id") or data.get("userId") or data.get("id")
    return str(uid) if uid else None


def _extract_email(data: dict) -> str:
    pub = data.get("public_user_data")
    if isinstance(pub, dict):
        email = pub.get("identifier") or pub.get("email_address")
        if email:
            return str(email)
    emails = data.get("email_addresses", [])
    if isinstance(emails, list) and emails:
        primary = emails[0]
        if isinstance(primary, dict):
            email_addr = primary.get("email_address")
            if email_addr:
                return str(email_addr)
    user_id = _extract_user_id(data) or "unknown"
    return f"unknown_{user_id}@example.com"


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

    try:
        async with db_pool.acquire() as conn:
            # 1. organization.created
            if event_type == "organization.created":
                org_id = data.get("id")
                if not org_id:
                    return {"status": "ignored", "reason": "missing_org_id"}
                name = data.get("name", "Unknown Organization")

                await conn.execute(
                    """
                    INSERT INTO tenants (id, name) VALUES ($1, $2)
                    ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name
                    """,
                    org_id,
                    name,
                )

                await conn.execute(
                    """
                    INSERT INTO tenant_glossary (tenant_id, metric_synonyms, table_synonyms)
                    VALUES ($1, $2::jsonb, $3::jsonb)
                    ON CONFLICT (tenant_id) DO NOTHING
                    """,
                    org_id,
                    json.dumps(DEFAULT_METRIC_SYNONYMS),
                    json.dumps(DEFAULT_TABLE_SYNONYMS),
                )

                if settings.snowflake_dsn and settings.fernet_key:
                    try:
                        from cryptography.fernet import Fernet

                        f = Fernet(settings.fernet_key.encode())
                        encrypted_dsn = f.encrypt(settings.snowflake_dsn.encode()).decode()
                        await conn.execute(
                            """
                            INSERT INTO tenant_connections (tenant_id, snowflake_dsn)
                            VALUES ($1, $2)
                            ON CONFLICT (tenant_id) DO NOTHING
                            """,
                            org_id,
                            encrypted_dsn,
                        )
                    except Exception as e:
                        logger.error(f"Failed to seed tenant connection for org {org_id}: {e}")

                logger.info(f"Provisioned Clerk Org: {org_id} ({name})")

            # 2. organization.updated
            elif event_type == "organization.updated":
                org_id = data.get("id")
                if org_id:
                    name = data.get("name", "Unknown Organization")
                    await conn.execute(
                        """
                        INSERT INTO tenants (id, name) VALUES ($1, $2)
                        ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, deleted_at = NULL
                        """,
                        org_id,
                        name,
                    )
                    logger.info(f"Updated Clerk Org: {org_id}")

            # 3. organization.deleted
            elif event_type == "organization.deleted":
                org_id = data.get("id")
                if org_id:
                    # Soft-delete memberships and remove connection
                    await conn.execute(
                        "UPDATE tenant_memberships SET deleted_at = NOW() WHERE tenant_id = $1",
                        org_id,
                    )
                    await conn.execute(
                        "DELETE FROM tenant_connections WHERE tenant_id = $1", org_id
                    )
                    logger.info(f"Deactivated Clerk Org: {org_id}")

            # 4. organizationMembership.created
            elif event_type == "organizationMembership.created":
                org = data.get("organization", {})
                tenant_id = org.get("id") or data.get("organization_id")
                user_id = _extract_user_id(data)
                role = _normalize_role(data.get("role"))
                permissions = data.get("permissions", [])

                if tenant_id and user_id:
                    email = _extract_email(data)
                    # Upsert user
                    await conn.execute(
                        """
                        INSERT INTO users (id, email) VALUES ($1, $2)
                        ON CONFLICT (id) DO UPDATE SET email = EXCLUDED.email, deleted_at = NULL
                        """,
                        user_id,
                        email,
                    )
                    # Upsert membership
                    await conn.execute(
                        """
                        INSERT INTO tenant_memberships (tenant_id, user_id, role, permissions, deleted_at)
                        VALUES ($1, $2, $3, $4::jsonb, NULL)
                        ON CONFLICT (tenant_id, user_id) DO UPDATE
                        SET role = EXCLUDED.role, permissions = EXCLUDED.permissions, updated_at = NOW(), deleted_at = NULL
                        """,
                        tenant_id,
                        user_id,
                        role,
                        json.dumps(permissions),
                    )
                    logger.info(
                        f"Upserted membership user={user_id} tenant={tenant_id} role={role}"
                    )

            # 5. organizationMembership.updated
            elif event_type == "organizationMembership.updated":
                org = data.get("organization", {})
                tenant_id = org.get("id") or data.get("organization_id")
                user_id = _extract_user_id(data)
                role = _normalize_role(data.get("role"))
                permissions = data.get("permissions", [])

                if tenant_id and user_id:
                    await conn.execute(
                        """
                        INSERT INTO tenant_memberships (tenant_id, user_id, role, permissions, deleted_at)
                        VALUES ($1, $2, $3, $4::jsonb, NULL)
                        ON CONFLICT (tenant_id, user_id) DO UPDATE
                        SET role = EXCLUDED.role, permissions = EXCLUDED.permissions, updated_at = NOW(), deleted_at = NULL
                        """,
                        tenant_id,
                        user_id,
                        role,
                        json.dumps(permissions),
                    )
                    logger.info(f"Updated membership user={user_id} tenant={tenant_id} role={role}")

            # 6. organizationMembership.deleted
            elif event_type == "organizationMembership.deleted":
                org = data.get("organization", {})
                tenant_id = org.get("id") or data.get("organization_id")
                user_id = _extract_user_id(data)

                if tenant_id and user_id:
                    await conn.execute(
                        "UPDATE tenant_memberships SET deleted_at = NOW() WHERE tenant_id = $1 AND user_id = $2",
                        tenant_id,
                        user_id,
                    )
                    logger.info(f"Soft-deleted membership user={user_id} tenant={tenant_id}")

            # 7. user.created
            elif event_type == "user.created":
                user_id = data.get("id")
                if user_id:
                    email = _extract_email(data)
                    await conn.execute(
                        """
                        INSERT INTO users (id, email) VALUES ($1, $2)
                        ON CONFLICT (id) DO UPDATE SET email = EXCLUDED.email, deleted_at = NULL
                        """,
                        user_id,
                        email,
                    )
                    logger.info(f"Upserted user profile: {user_id} ({email})")

            # 8. user.updated
            elif event_type == "user.updated":
                user_id = data.get("id")
                if user_id:
                    email = _extract_email(data)
                    await conn.execute(
                        """
                        INSERT INTO users (id, email, updated_at, deleted_at) VALUES ($1, $2, NOW(), NULL)
                        ON CONFLICT (id) DO UPDATE SET email = EXCLUDED.email, updated_at = NOW(), deleted_at = NULL
                        """,
                        user_id,
                        email,
                    )
                    logger.info(f"Updated user profile: {user_id}")

            # 9. user.deleted
            elif event_type == "user.deleted":
                user_id = data.get("id")
                if user_id:
                    await conn.execute("UPDATE users SET deleted_at = NOW() WHERE id = $1", user_id)
                    await conn.execute(
                        "UPDATE tenant_memberships SET deleted_at = NOW() WHERE user_id = $1",
                        user_id,
                    )
                    logger.info(f"Soft-deleted user: {user_id}")

    except Exception:
        logger.exception("Error processing Clerk webhook")
        raise HTTPException(status_code=500, detail="Internal processing error")

    return {"status": "success"}
