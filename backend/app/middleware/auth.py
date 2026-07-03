from uuid import UUID

from fastapi import Depends, Header, Query, WebSocket
import jwt
from jwt import PyJWKClient
from jwt.exceptions import PyJWTError

from app.config import Settings, get_settings
from app.models.contracts import ApiError, AuthClaims, ErrorCode

LOCAL_USER_ID = UUID("00000000-0000-0000-0000-000000000001")
LOCAL_TENANT_ID = UUID("00000000-0000-0000-0000-000000000101")
_VERIFIER_CACHE: dict[tuple[str | None, ...], "ClerkJwtVerifier"] = {}


class ClerkJwtVerifier:
    def __init__(self, settings: Settings, jwks_client: PyJWKClient | None = None) -> None:
        if not settings.clerk_issuer or not settings.clerk_jwks_url:
            raise ApiError(ErrorCode.auth_invalid, status_code=401, detail="Clerk is not configured.")
        self.settings = settings
        self.jwks_client = jwks_client or PyJWKClient(settings.clerk_jwks_url)

    def verify(self, token: str) -> AuthClaims:
        try:
            signing_key = self.jwks_client.get_signing_key_from_jwt(token)
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=self.settings.clerk_audience,
                issuer=self.settings.clerk_issuer,
                options={
                    "require": ["exp", "iat", "iss", "sub"],
                    "verify_aud": self.settings.clerk_audience is not None,
                },
            )
            return self._claims_from_payload(payload)
        except ApiError:
            raise
        except PyJWTError as exc:
            raise ApiError(
                ErrorCode.auth_invalid,
                status_code=401,
                detail=f"JWT validation failed: {type(exc).__name__}",
            ) from exc

    def _claims_from_payload(self, payload: dict) -> AuthClaims:
        try:
            return AuthClaims(
                user_id=UUID(str(payload[self.settings.clerk_user_id_claim])),
                tenant_id=UUID(str(payload[self.settings.clerk_tenant_id_claim])),
                email=str(payload.get(self.settings.clerk_email_claim, "unknown@voxquery.test")),
                role=str(payload.get(self.settings.clerk_role_claim, "viewer")),
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


def get_current_user(
    authorization: str | None = Header(default=None),
    x_fake_user_id: str | None = Header(default=None),
    x_fake_tenant_id: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> AuthClaims:
    if settings.auth_mode == "fake":
        return AuthClaims(
            user_id=UUID(x_fake_user_id) if x_fake_user_id else LOCAL_USER_ID,
            tenant_id=UUID(x_fake_tenant_id) if x_fake_tenant_id else LOCAL_TENANT_ID,
        )
    if not authorization:
        raise ApiError(ErrorCode.auth_missing, status_code=401)
    if not authorization.startswith("Bearer "):
        raise ApiError(ErrorCode.auth_invalid, status_code=401)
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise ApiError(ErrorCode.auth_missing, status_code=401)
    return get_clerk_verifier(settings).verify(token)


async def authenticate_websocket(
    websocket: WebSocket,
    token: str | None = Query(default=None),
    settings: Settings = Depends(get_settings),
) -> AuthClaims | None:
    if settings.auth_mode == "fake":
        return AuthClaims(user_id=LOCAL_USER_ID, tenant_id=LOCAL_TENANT_ID)
    if not token:
        await websocket.close(code=4001)
        return None
    try:
        return get_clerk_verifier(settings).verify(token)
    except ApiError:
        await websocket.close(code=4001)
        return None
