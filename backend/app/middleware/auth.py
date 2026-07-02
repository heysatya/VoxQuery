from uuid import UUID

from fastapi import Depends, Header, Query, WebSocket

from app.config import Settings, get_settings
from app.models.contracts import ApiError, AuthClaims, ErrorCode

LOCAL_USER_ID = UUID("00000000-0000-0000-0000-000000000001")
LOCAL_TENANT_ID = UUID("00000000-0000-0000-0000-000000000101")


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
    raise ApiError(ErrorCode.auth_invalid, status_code=401, detail="Clerk adapter is not wired yet.")


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
    await websocket.close(code=4001)
    return None
