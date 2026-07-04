from fastapi import APIRouter, Depends
from app.models.contracts import AuthClaims, StatusResponse, TelemetryRequest
from app.middleware.auth import get_current_user

router = APIRouter()

def get_telemetry_logger():
    from app.main import app
    return app.state.telemetry

@router.post("/api/telemetry", response_model=StatusResponse)
async def post_telemetry(
    request: TelemetryRequest,
    claims: AuthClaims = Depends(get_current_user),
    telemetry = Depends(get_telemetry_logger)
) -> StatusResponse:
    # Build payload ensuring it only contains properties from the request
    # and explicitly binds tenant_id from AuthClaims to prevent injection.
    payload = {
        "event": request.event,
        "tenant_id": str(claims.tenant_id),
        "user_id": str(claims.user_id),
    }
    
    if request.session_id:
        payload["session_id"] = str(request.session_id)
    if request.outcome:
        payload["outcome"] = request.outcome
    if request.latency_ms is not None:
        payload["latency_ms"] = request.latency_ms
    if request.error_code:
        payload["error_code"] = request.error_code

    telemetry.info(f"Frontend telemetry: {request.event}", **payload)
    return StatusResponse(status="recorded")
