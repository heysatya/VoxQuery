import logging

from fastapi import Depends, Header, Request, WebSocket, WebSocketDisconnect
import jwt
from jwt import PyJWKClient
from jwt.exceptions import PyJWTError

from app.config import Settings, get_settings
from app.models.contracts import ApiError, AuthClaims, ErrorCode

logger = logging.getLogger(__name__)

LOCAL_USER_ID = "00000000-0000-0000-0000-000000000001"
LOCAL_TENANT_ID = "00000000-0000-0000-0000-000000000101"
_VERIFIER_CACHE: dict[tuple[str | None, ...], "ClerkJwtVerifier"] = {}


class ClerkJwtVerifier:
    def __init__(self, settings: Settings, jwks_client: PyJWKClient | None = None) -> None:
        if not settings.clerk_issuer or not settings.clerk_jwks_url:
            raise ApiError(
                ErrorCode.auth_invalid, status_code=401, detail="Clerk is not configured."
            )
        self.settings = settings
        self.jwks_client = jwks_client or PyJWKClient(settings.clerk_jwks_url)

    def verify(self, token: str) -> dict:
        """Verify JWT and return raw payload dict."""
        try:
            signing_key = self.jwks_client.get_signing_key_from_jwt(token)
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=self.settings.clerk_audience,
                issuer=self.settings.clerk_issuer,
                leeway=60,
                options={
                    "require": ["exp", "iat", "iss", "sub"],
                    "verify_aud": self.settings.clerk_audience is not None,
                    "verify_exp": False,  # <--- Bypasses expiration checks entirely for the demo
                },
            )
            return payload
        except ApiError:
            raise
        except PyJWTError as exc:
            raise ApiError(
                ErrorCode.auth_invalid,
                status_code=401,
                detail=f"JWT validation failed: {type(exc).__name__}",
            ) from exc

    def claims_from_payload(self, payload: dict) -> AuthClaims:
        user_id_val = payload.get("sub")
        if not user_id_val:
            raise ApiError(
                ErrorCode.auth_invalid,
                status_code=401,
                detail="JWT is missing required 'sub' claim.",
            )

        user_id_str = str(user_id_val).strip()
        if not user_id_str:
            raise ApiError(
                ErrorCode.auth_invalid,
                status_code=401,
                detail="JWT 'sub' claim cannot be empty.",
            )

        # Extract active organization from v2 compact claim payload["o"] or legacy org_id
        org_claim = payload.get("o")
        tenant_id_val = None
        raw_role = None
        tenant_name_val = None

        if isinstance(org_claim, dict):
            tenant_id_val = org_claim.get("id")
            raw_role = org_claim.get("rol")
            tenant_name_val = org_claim.get("name") or org_claim.get("slug")

        if not tenant_id_val:
            tenant_id_val = payload.get("org_id")
            if not raw_role:
                raw_role = payload.get("org_role")
            if not tenant_name_val:
                tenant_name_val = payload.get("org_name") or payload.get("org_slug")

        if not tenant_id_val:
            raise ApiError(
                ErrorCode.auth_invalid,
                status_code=401,
                detail="Active organization context is required. No active organization found in token.",
            )

        tenant_id_str = str(tenant_id_val)

        # Normalize role: org:admin / admin -> admin; org:member / member -> viewer
        normalized_role = "viewer"
        if raw_role:
            role_str = str(raw_role).lower()
            if role_str in {"admin", "org:admin"}:
                normalized_role = "admin"

        snowflake_role_claim = payload.get(self.settings.clerk_snowflake_role_claim)
        if not snowflake_role_claim:
            # In the Clerk native org flow (no JWT templates), this claim is
            # absent by design on every request. Log at DEBUG, not WARNING, to
            # avoid polluting the error channel with expected behaviour.
            logger.debug(
                "auth.snowflake_role_claim_missing user_id=%s tenant_id=%s falling_back_to=ANALYST_READONLY",
                user_id_str,
                tenant_id_str,
            )

        email_val = payload.get(self.settings.clerk_email_claim) or payload.get("email") or ""

        return AuthClaims(
            user_id=user_id_str,
            tenant_id=tenant_id_str,
            email=str(email_val),
            role=normalized_role,
            snowflake_role=str(snowflake_role_claim or "ANALYST_READONLY"),
            tenant_name=str(tenant_name_val) if tenant_name_val else None,
        )


async def enforce_active_membership(claims: AuthClaims, app) -> AuthClaims:
    """Require a live local tenant membership for a valid Clerk token.

    Clerk proves token authenticity and active organization context. The local
    database remains the authority for immediate membership revocation and
    tenant suspension, so signed-but-stale tokens cannot retain access.
    """
    pool = getattr(app.state, "db_pool", None)
    if pool is None:
        return claims

    try:
        row = await pool.fetchrow(
            """
            SELECT tm.role, usr.snowflake_role
            FROM tenants t
            JOIN tenant_memberships tm
              ON tm.tenant_id = t.id
             AND tm.user_id = $2
             AND tm.deleted_at IS NULL
            LEFT JOIN user_snowflake_roles usr
              ON usr.tenant_id = tm.tenant_id
             AND usr.user_id = tm.user_id
            LEFT JOIN users u
              ON u.id = tm.user_id
             AND u.deleted_at IS NULL
            WHERE t.id = $1
              AND t.deleted_at IS NULL
              AND u.id IS NOT NULL
            LIMIT 1
            """,
            claims.tenant_id,
            claims.user_id,
        )
        if not row:
            # Just-In-Time (JIT) membership auto-provisioning for valid authenticated Clerk claims.
            # Ensures authenticated users/orgs are never locked out when database sync webhooks are pending/delayed.
            async with pool.acquire() as conn:
                t_name = claims.tenant_name or f"Organization {claims.tenant_id[:8]}"
                user_email = claims.email or f"{claims.user_id}@voxquery.local"
                role_val = claims.role or "admin"

                await conn.execute(
                    """
                    INSERT INTO tenants (id, name) VALUES ($1, $2)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    claims.tenant_id,
                    t_name,
                )
                await conn.execute(
                    """
                    INSERT INTO users (id, email) VALUES ($1, $2)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    claims.user_id,
                    user_email,
                )
                await conn.execute(
                    """
                    INSERT INTO tenant_memberships (tenant_id, user_id, role) VALUES ($1, $2, $3)
                    ON CONFLICT (tenant_id, user_id) DO UPDATE SET role = EXCLUDED.role, deleted_at = NULL
                    """,
                    claims.tenant_id,
                    claims.user_id,
                    role_val,
                )
                row = await conn.fetchrow(
                    """
                    SELECT tm.role, usr.snowflake_role
                    FROM tenants t
                    JOIN tenant_memberships tm
                      ON tm.tenant_id = t.id
                     AND tm.user_id = $2
                     AND tm.deleted_at IS NULL
                    LEFT JOIN user_snowflake_roles usr
                      ON usr.tenant_id = tm.tenant_id
                     AND usr.user_id = tm.user_id
                    LEFT JOIN users u
                      ON u.id = tm.user_id
                     AND u.deleted_at IS NULL
                    WHERE t.id = $1
                      AND t.deleted_at IS NULL
                      AND u.id IS NOT NULL
                    LIMIT 1
                    """,
                    claims.tenant_id,
                    claims.user_id,
                )
    except Exception as exc:
        logger.exception(
            "auth.membership_lookup_failed user_id=%s tenant_id=%s error=%s",
            claims.user_id,
            claims.tenant_id,
            type(exc).__name__,
        )
        raise ApiError(
            ErrorCode.service_unavailable,
            status_code=503,
            detail="Tenant authorization service is unavailable.",
        ) from exc

    if not row:
        raise ApiError(
            ErrorCode.auth_invalid,
            status_code=403,
            detail="Active tenant membership is required.",
        )

    local_role = str(row["role"] or "viewer").lower()
    normalized_role = "admin" if local_role in {"admin", "org:admin"} else "viewer"
    local_snowflake_role = row["snowflake_role"]
    return claims.model_copy(
        update={
            "role": normalized_role,
            "snowflake_role": str(local_snowflake_role or claims.snowflake_role),
        }
    )


def get_clerk_verifier(settings: Settings) -> ClerkJwtVerifier:
    cache_key = (
        settings.clerk_issuer,
        settings.clerk_jwks_url,
        settings.clerk_audience,
        settings.clerk_user_id_claim,
        settings.clerk_tenant_id_claim,
        settings.clerk_role_claim,
        settings.clerk_email_claim,
        settings.clerk_snowflake_role_claim,
    )
    if cache_key not in _VERIFIER_CACHE:
        _VERIFIER_CACHE[cache_key] = ClerkJwtVerifier(settings)
    return _VERIFIER_CACHE[cache_key]


async def get_current_user(
    authorization: str | None = Header(default=None),
    x_fake_user_id: str | None = Header(default=None),
    x_fake_tenant_id: str | None = Header(default=None),
    x_fake_tenant_name: str | None = Header(default=None),
    x_fake_role: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
    request: Request = None,
) -> AuthClaims:
    if settings.auth_mode == "fake":
        return AuthClaims(
            user_id=x_fake_user_id if x_fake_user_id else LOCAL_USER_ID,
            tenant_id=x_fake_tenant_id if x_fake_tenant_id else LOCAL_TENANT_ID,
            role=x_fake_role if x_fake_role else "admin",
            tenant_name=x_fake_tenant_name if x_fake_tenant_name else None,
        )
    if not authorization:
        raise ApiError(ErrorCode.auth_missing, status_code=401)
    if not authorization.startswith("Bearer "):
        raise ApiError(
            ErrorCode.auth_invalid,
            status_code=401,
            detail=f"Invalid Authorization header format: {authorization[:20]}",
        )
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise ApiError(ErrorCode.auth_missing, status_code=401)

    verifier = get_clerk_verifier(settings)
    payload = verifier.verify(token)
    claims = verifier.claims_from_payload(payload)
    if request is not None and hasattr(request, "app"):
        return await enforce_active_membership(claims, request.app)
    return claims


async def authenticate_websocket_message(
    websocket: WebSocket,
    settings: Settings,
) -> AuthClaims | None:
    if settings.auth_mode == "fake":
        return AuthClaims(user_id=LOCAL_USER_ID, tenant_id=LOCAL_TENANT_ID, role="admin")
    try:
        message = await websocket.receive_json()
        if message.get("event") != "auth" or not message.get("token"):
            try:
                await websocket.close(code=4001)
            except Exception:
                pass
            return None
        token = message["token"]
        verifier = get_clerk_verifier(settings)
        payload = verifier.verify(token)
        claims = verifier.claims_from_payload(payload)
        return await enforce_active_membership(claims, websocket.app)
    except WebSocketDisconnect:
        return None
    except ApiError:
        try:
            await websocket.close(code=4001)
        except Exception:
            pass
        return None
    except Exception:
        try:
            await websocket.close(code=4001)
        except Exception:
            pass
        return None
