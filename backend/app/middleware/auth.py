from uuid import UUID

import asyncpg
from fastapi import Depends, Header, WebSocket
import jwt
from jwt import PyJWKClient
from jwt.exceptions import PyJWTError

from app.config import Settings, get_settings
from app.models.contracts import ApiError, AuthClaims, ErrorCode

LOCAL_USER_ID = UUID("00000000-0000-0000-0000-000000000001")
LOCAL_TENANT_ID = UUID("00000000-0000-0000-0000-000000000101")
_VERIFIER_CACHE: dict[tuple[str | None, ...], "ClerkJwtVerifier"] = {}

# Simple in-process role cache to avoid hitting DB on every request.
# Key: user_id (str), Value: role (str)
_ROLE_CACHE: dict[str, str] = {}


class ClerkJwtVerifier:
    def __init__(self, settings: Settings, jwks_client: PyJWKClient | None = None) -> None:
        if not settings.clerk_issuer or not settings.clerk_jwks_url:
            raise ApiError(ErrorCode.auth_invalid, status_code=401, detail="Clerk is not configured.")
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

    def claims_from_payload(self, payload: dict, role: str = "viewer") -> AuthClaims:
        try:
            user_id_str = str(payload[self.settings.clerk_user_id_claim])
            return AuthClaims(
                user_id=UUID(user_id_str),
                tenant_id=UUID(str(payload[self.settings.clerk_tenant_id_claim])),
                email=str(payload.get(self.settings.clerk_email_claim, f"unknown_{user_id_str}@voxquery.test")),
                role=role,
                snowflake_role=str(
                    payload.get(self.settings.clerk_snowflake_role_claim, "ANALYST_READONLY")
                ),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ApiError(
                ErrorCode.auth_invalid,
                status_code=401,
                detail="JWT is missing required VoxQuery authorization claims.",
            ) from exc


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


async def _lookup_role_from_db(user_id: str, settings: Settings) -> str:
    """Look up the user's role from Supabase. Falls back to 'viewer' on any error."""
    if user_id in _ROLE_CACHE:
        return _ROLE_CACHE[user_id]
    if not settings.supabase_database_url:
        return "viewer"
    try:
        conn = await asyncpg.connect(settings.supabase_database_url, statement_cache_size=0)
        try:
            row = await conn.fetchrow(
                "SELECT role FROM users WHERE id = $1::uuid",
                user_id,
            )
            role = row["role"] if row and row["role"] else "viewer"
        finally:
            await conn.close()
        _ROLE_CACHE[user_id] = role
        return role
    except Exception:
        return "viewer"


async def get_current_user(
    authorization: str | None = Header(default=None),
    x_fake_user_id: str | None = Header(default=None),
    x_fake_tenant_id: str | None = Header(default=None),
    x_fake_role: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> AuthClaims:
    if settings.auth_mode == "fake":
        return AuthClaims(
            user_id=UUID(x_fake_user_id) if x_fake_user_id else LOCAL_USER_ID,
            tenant_id=UUID(x_fake_tenant_id) if x_fake_tenant_id else LOCAL_TENANT_ID,
            role=x_fake_role if x_fake_role else "admin",
        )
    if not authorization:
        raise ApiError(ErrorCode.auth_missing, status_code=401)
    if not authorization.startswith("Bearer "):
        raise ApiError(ErrorCode.auth_invalid, status_code=401, detail=f"Invalid Authorization header format: {authorization[:20]}")
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise ApiError(ErrorCode.auth_missing, status_code=401)

    verifier = get_clerk_verifier(settings)
    payload = verifier.verify(token)

    # The Clerk JWT does not include a `role` claim unless explicitly configured
    # in a Clerk session token template. We resolve the role from the DB instead,
    # using the vox_user_id embedded in the JWT. This makes the DB the single
    # source of truth for authorization.
    user_id_str = str(payload.get(settings.clerk_user_id_claim, ""))
    role_from_jwt = str(payload.get(settings.clerk_role_claim, ""))

    if role_from_jwt and role_from_jwt in {"admin", "viewer", "editor"}:
        # If Clerk session template is configured and provides the role, use it.
        role = role_from_jwt
    elif user_id_str:
        # Fall back to DB lookup.
        role = await _lookup_role_from_db(user_id_str, settings)
    else:
        role = "viewer"

    return verifier.claims_from_payload(payload, role=role)


async def authenticate_websocket_message(
    websocket: WebSocket,
    settings: Settings,
) -> AuthClaims | None:
    if settings.auth_mode == "fake":
        return AuthClaims(user_id=LOCAL_USER_ID, tenant_id=LOCAL_TENANT_ID, role="admin")
    try:
        message = await websocket.receive_json()
        if message.get("event") != "auth" or not message.get("token"):
            await websocket.close(code=4001)
            return None
        token = message["token"]
        verifier = get_clerk_verifier(settings)
        payload = verifier.verify(token)
        user_id_str = str(payload.get(settings.clerk_user_id_claim, ""))
        role = await _lookup_role_from_db(user_id_str, settings) if user_id_str else "viewer"
        return verifier.claims_from_payload(payload, role=role)
    except ApiError:
        await websocket.close(code=4001)
        return None
    except Exception:
        await websocket.close(code=4001)
        return None

