from fastapi import APIRouter, Depends, Request
from app.models.contracts import AuthClaims, StatusResponse, TelemetryRequest
from app.middleware.auth import get_current_user

router = APIRouter()


def get_telemetry_logger(http_request: Request):
    return http_request.app.state.telemetry


@router.post("/api/telemetry", response_model=StatusResponse)
async def post_telemetry(
    request: TelemetryRequest,
    http_request: Request,
    claims: AuthClaims = Depends(get_current_user),
    telemetry=Depends(get_telemetry_logger),
) -> StatusResponse:
    payload = {
        "event": "stt.mic.permission",
        "tenant_id": str(claims.tenant_id),
        "user_id": str(claims.user_id),
    }

    if request.session_id:
        session = await http_request.app.state.sessions.get_for_claims(claims, request.session_id)
        if session is None:
            # Re-use existing session error pattern
            from app.models.contracts import ApiError, ErrorCode

            raise ApiError(ErrorCode.session_not_found, status_code=403)
        payload["session_id"] = str(request.session_id)
    else:
        payload["session_id"] = "none"

    if request.outcome:
        payload["outcome"] = request.outcome

    telemetry.emit(tier=3, **payload)
    return StatusResponse(status="recorded")
