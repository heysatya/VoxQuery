"""
Secure share-link repository.

Design principles:
- Raw tokens are never stored; only their SHA-256 hash is persisted.
- Lookup uses hmac.compare_digest for constant-time comparison where feasible.
- Expiration and revocation are enforced in the database query, not only in Python.
- All operations are scoped to tenant_id to prevent cross-tenant access.
- Shared results are snapshots of the turn result — no new warehouse queries.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import asyncpg

from app.models.contracts import AuthClaims

logger = logging.getLogger("voxquery.repositories.share")

# Default TTL for share links
DEFAULT_TTL_HOURS = 168  # 7 days
MAX_TTL_HOURS = 720  # 30 days
MIN_TTL_HOURS = 1


def _generate_token() -> str:
    """Generate a cryptographically secure opaque token."""
    return secrets.token_urlsafe(32)


def _hash_token(token: str) -> str:
    """SHA-256 hex digest of the token. Only this is stored."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _tokens_equal(token: str, stored_hash: str) -> bool:
    """Constant-time comparison between a presented token and its stored hash."""
    presented_hash = _hash_token(token)
    return hmac.compare_digest(presented_hash, stored_hash)


class ShareRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def create_share_link(
        self,
        claims: AuthClaims,
        turn_id: UUID,
        *,
        label: str | None = None,
        ttl_hours: int = DEFAULT_TTL_HOURS,
    ) -> dict[str, Any] | None:
        """
        Create a share link for a completed turn result.

        Validates:
        - The turn belongs to the caller's tenant.
        - The turn is completed (has a result).
        - TTL is within acceptable bounds.

        Returns dict with: link_id, token (raw, shown once), expires_at
        Returns None if the turn is not found or not completed.
        """
        ttl_hours = max(MIN_TTL_HOURS, min(MAX_TTL_HOURS, ttl_hours))
        expires_at = datetime.now(UTC) + timedelta(hours=ttl_hours)

        # Validate the turn belongs to this tenant and is completed
        try:
            async with self._pool.acquire() as conn:
                turn_row = await conn.fetchrow(
                    """
                    SELECT turn_id, full_result, completed
                    FROM turns
                    WHERE turn_id   = $1
                      AND tenant_id = $2
                      AND completed = TRUE
                    """,
                    turn_id,
                    claims.tenant_id,
                )
        except Exception as exc:
            logger.warning("create_share_link: turn lookup failed: %s", exc)
            return None

        if turn_row is None:
            return None

        token = _generate_token()
        token_hash = _hash_token(token)

        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    INSERT INTO share_links
                        (tenant_id, creator_user_id, turn_id, token_hash, label, expires_at)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    RETURNING id, expires_at
                    """,
                    claims.tenant_id,
                    claims.user_id,
                    turn_id,
                    token_hash,
                    label[:200] if label else None,
                    expires_at,
                )
        except Exception as exc:
            logger.warning("create_share_link: insert failed: %s", exc)
            return None

        if row is None:
            return None

        return {
            "link_id": str(row["id"]),
            "token": token,  # returned once; never stored
            "expires_at": row["expires_at"].isoformat(),
        }

    async def get_share_by_token(
        self,
        token: str,
        requesting_tenant_id: str,
    ) -> dict[str, Any] | None:
        """
        Look up a share link by its raw token.

        Enforces:
        - Token matches stored hash (constant-time comparison).
        - Link is not expired.
        - Link is not revoked.
        - Turn belongs to the requesting tenant (no cross-tenant access).

        Returns a safe result snapshot (no raw SQL credentials, no DSNs).
        Updates last_accessed_at and access_count as a side-effect.
        """
        if not token or len(token) > 512:
            return None

        token_hash = _hash_token(token)

        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT
                        sl.id, sl.tenant_id, sl.creator_user_id, sl.turn_id,
                        sl.token_hash, sl.label, sl.created_at, sl.expires_at,
                        sl.revoked_at, sl.access_count,
                        t.full_result, t.user_input, t.chart_type,
                        t.confidence_tier, t.completed
                    FROM share_links sl
                    JOIN turns t ON t.turn_id = sl.turn_id
                    WHERE sl.token_hash = $1
                    """,
                    token_hash,
                )
        except Exception as exc:
            logger.warning("get_share_by_token: lookup failed: %s", exc)
            return None

        if row is None:
            return None  # token not found

        # Constant-time comparison (belt-and-suspenders — DB already matched hash)
        if not _tokens_equal(token, row["token_hash"]):
            return None

        # Check tenant boundary
        if str(row["tenant_id"]) != requesting_tenant_id:
            logger.warning("cross-tenant share link access attempt tenant=%s", requesting_tenant_id)
            return None

        # Check revocation
        if row["revoked_at"] is not None:
            return {"_error": "revoked"}

        # Check expiration
        expires_at = row["expires_at"]
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if datetime.now(UTC) > expires_at:
            return {"_error": "expired"}

        # Check turn is still valid and completed
        if not row["completed"]:
            return {"_error": "not_found"}

        # Record access (best-effort)
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE share_links
                    SET last_accessed_at = NOW(),
                        access_count     = access_count + 1
                    WHERE id = $1
                    """,
                    row["id"],
                )
        except Exception:
            pass

        # Build safe snapshot — no raw warehouse credentials, no DSNs
        import json

        full_result = row["full_result"]
        if isinstance(full_result, str):
            try:
                full_result = json.loads(full_result)
            except Exception:
                full_result = None

        return {
            "link_id": str(row["id"]),
            "turn_id": str(row["turn_id"]),
            "label": row["label"],
            "created_at": row["created_at"].isoformat(),
            "expires_at": row["expires_at"].isoformat(),
            "user_input": str(row["user_input"] or ""),
            "chart_type": row["chart_type"],
            "confidence_tier": row["confidence_tier"],
            "full_result": full_result,
        }

    async def revoke_share_link(
        self,
        claims: AuthClaims,
        link_id: str,
    ) -> bool:
        """
        Revoke a share link. Only the creator (within the same tenant) can revoke.
        Returns True if revoked, False if not found or already revoked.
        """
        try:
            async with self._pool.acquire() as conn:
                result = await conn.fetchval(
                    """
                    UPDATE share_links
                    SET revoked_at = NOW()
                    WHERE id               = $1::uuid
                      AND tenant_id        = $2
                      AND creator_user_id  = $3
                      AND revoked_at IS NULL
                    RETURNING id
                    """,
                    link_id,
                    claims.tenant_id,
                    claims.user_id,
                )
            return result is not None
        except Exception as exc:
            logger.warning("revoke_share_link failed: %s", exc)
            return False

    async def list_active_share_links(
        self,
        claims: AuthClaims,
        *,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """List non-expired, non-revoked share links created by the authenticated user."""
        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT sl.id, sl.turn_id, sl.label, sl.created_at, sl.expires_at,
                           sl.access_count, t.user_input
                    FROM share_links sl
                    JOIN turns t ON t.turn_id = sl.turn_id
                    WHERE sl.tenant_id       = $1
                      AND sl.creator_user_id = $2
                      AND sl.revoked_at IS NULL
                      AND sl.expires_at > NOW()
                    ORDER BY sl.created_at DESC
                    LIMIT $3
                    """,
                    claims.tenant_id,
                    claims.user_id,
                    limit,
                )
            return [
                {
                    "link_id": str(r["id"]),
                    "turn_id": str(r["turn_id"]),
                    "label": r["label"],
                    "user_input": str(r["user_input"] or ""),
                    "created_at": r["created_at"].isoformat(),
                    "expires_at": r["expires_at"].isoformat(),
                    "access_count": r["access_count"],
                }
                for r in rows
            ]
        except Exception as exc:
            logger.warning("list_active_share_links failed: %s", exc)
            return []
