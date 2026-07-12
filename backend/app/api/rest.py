from uuid import UUID

from fastapi import APIRouter, Depends

from app.config import Settings, get_settings
from app.core.session import InMemorySessionStore
from app.middleware.auth import get_current_user
from app.models.contracts import (
    ApiError,
    AuthClaims,
    ClarificationRequest,
    ClarificationResponse,
    ErrorCode,
    FeedbackRequest,
    QueryAcceptedResponse,
    QueryRequest,
    ResultResponse,
    ResultTrust,
    SessionCreateRequest,
    SessionCreateResponse,
    StatusResponse,
    valid_visualizations_for_result,
)
from app.services.pipeline import PipelineOrchestrator

router = APIRouter()


def get_sessions() -> InMemorySessionStore:
    from app.main import app

    return app.state.sessions


def get_pipeline() -> PipelineOrchestrator:
    from app.main import app

    return app.state.pipeline


@router.post("/api/session", response_model=SessionCreateResponse, status_code=201)
async def create_session(
    request: SessionCreateRequest,
    claims: AuthClaims = Depends(get_current_user),
    sessions: InMemorySessionStore = Depends(get_sessions),
) -> SessionCreateResponse:
    if request.tenant_id != claims.tenant_id:
        raise ApiError(ErrorCode.auth_invalid, status_code=401)
    session, expires_at = sessions.create(claims)
    return SessionCreateResponse(
        session_id=session.session_id,
        conversation_id=session.conversation_id,
        expires_at=expires_at,
    )


@router.delete("/api/session/{session_id}", response_model=StatusResponse)
async def delete_session(
    session_id: UUID,
    claims: AuthClaims = Depends(get_current_user),
    sessions: InMemorySessionStore = Depends(get_sessions),
) -> StatusResponse:
    session = sessions.get_for_claims(claims, session_id)
    if not session:
        raise ApiError(ErrorCode.session_not_found, status_code=404)
    sessions.delete(claims.tenant_id, session_id)
    return StatusResponse(status="ok")


@router.post("/api/query", response_model=QueryAcceptedResponse, status_code=202)
async def submit_query(
    request: QueryRequest,
    claims: AuthClaims = Depends(get_current_user),
    pipeline: PipelineOrchestrator = Depends(get_pipeline),
) -> QueryAcceptedResponse:
    turn = await pipeline.submit_query(request, claims)
    return QueryAcceptedResponse(turn_id=turn.turn_id)


@router.post("/api/clarification", response_model=ClarificationResponse)
async def submit_clarification(
    request: ClarificationRequest,
    claims: AuthClaims = Depends(get_current_user),
    pipeline: PipelineOrchestrator = Depends(get_pipeline),
) -> ClarificationResponse:
    await pipeline.resolve_clarification(
        session_id=request.session_id,
        turn_id=request.turn_id,
        selection=request.selection,
        resolution_type=request.resolution_type,
        claims=claims,
    )
    return ClarificationResponse(turn_id=request.turn_id)




@router.get("/api/result/{turn_id}", response_model=ResultResponse)
async def get_result(
    turn_id: UUID,
    claims: AuthClaims = Depends(get_current_user),
    pipeline: PipelineOrchestrator = Depends(get_pipeline),
) -> ResultResponse:
    turn = pipeline.get_turn_for_user(turn_id, claims)
    if not turn.completed:
        raise ApiError(ErrorCode.turn_processing, status_code=202)
    if not turn.full_result or not turn.chart_type or not turn.confidence_tier:
        raise ApiError(ErrorCode.turn_processing, status_code=202)
    return ResultResponse(
        turn_id=turn.turn_id,
        chart_type=turn.chart_type,
        chart_rationale=turn.chart_rationale,
        confidence_tier=turn.confidence_tier,
        generated_sql=turn.generated_sql,
        result=turn.full_result,
        tts_text=turn.tts_text,
        proactive_questions=[],
        warnings=turn.result_warnings,
        valid_visualizations=valid_visualizations_for_result(turn.full_result),
        trust=ResultTrust(
            confidence_tier=turn.confidence_tier,
            row_count=turn.full_result.row_count,
            warning_count=len(turn.result_warnings),
            generated_sql_present=bool(turn.generated_sql),
            semantic_columns_present=bool(turn.full_result.semantic_columns),
        ),
        from_cache=turn.from_cache,
    )


@router.post("/api/feedback", response_model=StatusResponse)
async def submit_feedback(
    request: FeedbackRequest,
    claims: AuthClaims = Depends(get_current_user),
    pipeline: PipelineOrchestrator = Depends(get_pipeline),
    sessions: InMemorySessionStore = Depends(get_sessions),
) -> StatusResponse:
    turn = pipeline.get_turn_for_user(request.turn_id, claims)
    if turn.feedback_submitted:
        raise ApiError(ErrorCode.feedback_duplicate, status_code=409)
    session = sessions.get_for_claims(claims, request.session_id)
    if session is None:
        raise ApiError(ErrorCode.session_not_found, status_code=404)
    from app.observability.langfuse import tracer
    
    quality_flag = "low" if request.rating == -1 else "ok"
    if request.rating == -1:
        sessions.mark_low_quality(session, request.turn_id)
    turn.feedback_submitted = True
    turn.quality_flag = quality_flag
    pipeline.audit.enqueue_feedback(str(request.turn_id), quality_flag)
    
    # Optional option_selected resolution for the metadata
    option_selected = None
    if turn.clarification_triggered:
        for entity_value in session.resolved_entities.values():
            if hasattr(entity_value, "option_selected") and entity_value.option_selected:
                option_selected = entity_value.option_selected
                break
    
    tracer.score_feedback(
        request.turn_id,
        request.rating,
        turn.composite_score,
        turn.confidence_tier,
        turn.clarification_triggered,
        option_selected
    )
    
    return StatusResponse(status="recorded")
