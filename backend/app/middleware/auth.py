import logging

from fastapi import Depends, Header, WebSocket, WebSocketDisconnect
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

        if isinstance(org_claim, dict):
            tenant_id_val = org_claim.get("id")
            raw_role = org_claim.get("rol")
        
        if not tenant_id_val:
            tenant_id_val = payload.get("org_id")
            if not raw_role:
                raw_role = payload.get("org_role")

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
    x_fake_role: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> AuthClaims:
    if settings.auth_mode == "fake":
        return AuthClaims(
            user_id=x_fake_user_id if x_fake_user_id else LOCAL_USER_ID,
            tenant_id=x_fake_tenant_id if x_fake_tenant_id else LOCAL_TENANT_ID,
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
    return verifier.claims_from_payload(payload)


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
        return verifier.claims_from_payload(payload)
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


