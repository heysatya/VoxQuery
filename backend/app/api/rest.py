from uuid import UUID

from fastapi import APIRouter, Depends, Request

from app.config import get_settings
from app.core.session import InMemorySessionStore
from app.core.rate_limit import RateLimiter
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
    SessionCreateRequest,
    SessionCreateResponse,
    StatusResponse,
    valid_visualizations_for_result,
)
from app.services.pipeline import PipelineOrchestrator
from app.services.result_contracts import build_result_trust, confidence_reasons_for_turn

router = APIRouter()


def get_sessions(request: Request) -> InMemorySessionStore:
    return request.app.state.sessions


def get_pipeline(request: Request) -> PipelineOrchestrator:
    return request.app.state.pipeline


def get_rate_limiter(request: Request) -> RateLimiter:
    return request.app.state.rate_limiter


@router.post("/api/session", response_model=SessionCreateResponse, status_code=201)
async def create_session(
    request: SessionCreateRequest,
    claims: AuthClaims = Depends(get_current_user),
    sessions: InMemorySessionStore = Depends(get_sessions),
    pipeline: PipelineOrchestrator = Depends(get_pipeline),
) -> SessionCreateResponse:
    if request.tenant_id and request.tenant_id != claims.tenant_id:
        raise ApiError(ErrorCode.auth_invalid, status_code=401, detail="Requested tenant_id does not match authorization claims")
    # ensure it always uses claims.tenant_id going forward if omitted
    request.tenant_id = claims.tenant_id

    is_provisioned = getattr(pipeline.warehouse, "is_provisioned", None)
    if is_provisioned is not None and not await is_provisioned(claims.tenant_id):
        raise ApiError(
            ErrorCode.tenant_not_provisioned,
            status_code=403,
            detail=f"No warehouse connection configured for tenant {claims.tenant_id}",
        )

    session, expires_at = await sessions.create(claims)
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
    session = await sessions.get_for_claims(claims, session_id)
    if not session:
        raise ApiError(ErrorCode.session_not_found, status_code=404)
    await sessions.delete(claims.tenant_id, session_id)
    return StatusResponse(status="ok")


@router.post("/api/query", response_model=QueryAcceptedResponse, status_code=202)
async def submit_query(
    request: QueryRequest,
    claims: AuthClaims = Depends(get_current_user),
    pipeline: PipelineOrchestrator = Depends(get_pipeline),
    rate_limiter: RateLimiter = Depends(get_rate_limiter),
) -> QueryAcceptedResponse:
    limit = await rate_limiter.check_rate_limit(str(claims.user_id))
    if not limit.ok:
        raise ApiError(ErrorCode.rate_limit_exceeded, status_code=429, detail=f"Retry after {limit.retry_after_seconds}s")
        
    turn = await pipeline.submit_query(request, claims)
    return QueryAcceptedResponse(turn_id=turn.turn_id)


@router.post("/api/clarification", response_model=ClarificationResponse)
async def submit_clarification(
    request: ClarificationRequest,
    claims: AuthClaims = Depends(get_current_user),
    pipeline: PipelineOrchestrator = Depends(get_pipeline),
    rate_limiter: RateLimiter = Depends(get_rate_limiter),
    sessions: InMemorySessionStore = Depends(get_sessions),
) -> ClarificationResponse:
    limit = await rate_limiter.check_rate_limit(str(claims.user_id))
    if not limit.ok:
        raise ApiError(ErrorCode.rate_limit_exceeded, status_code=429, detail=f"Retry after {limit.retry_after_seconds}s")
        
    session = await sessions.get_for_claims(claims, request.session_id)
    if session and session.clarification_state and session.clarification_state.pending:
        from datetime import UTC, datetime, timedelta
        if datetime.now(UTC) - session.clarification_state.issued_at > timedelta(minutes=10):
            await sessions.clear_pending_clarification(session)
            pipeline.turns.pop(request.turn_id, None)
            return ClarificationResponse(turn_id=request.turn_id)

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
    confidence_reasons = confidence_reasons_for_turn(turn)
    return ResultResponse(
        turn_id=turn.turn_id,
        chart_type=turn.chart_type,
        chart_rationale=turn.chart_rationale,
        confidence_tier=turn.confidence_tier,
        confidence_reasons=confidence_reasons,
        generated_sql=turn.generated_sql,
        result=turn.full_result,
        tts_text=turn.tts_text,
        proactive_questions=turn.proactive_questions,
        warnings=turn.result_warnings,
        valid_visualizations=valid_visualizations_for_result(turn.full_result),
        trust=build_result_trust(turn, turn.full_result),
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
    session = await sessions.get_for_claims(claims, request.session_id)
    if session is None:
        raise ApiError(ErrorCode.session_not_found, status_code=404)
    from app.observability.langfuse import tracer
    
    quality_flag = "low" if request.rating == -1 else "ok"
    if request.rating == -1:
        await sessions.mark_low_quality(session, request.turn_id)
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


def get_audit(request: Request):
    return request.app.state.audit


def get_db_pool(request: Request):
    return getattr(request.app.state, "db_pool", None)


@router.get("/api/admin/feedback")
async def get_feedback(
    limit: int = 50,
    offset: int = 0,
    claims: AuthClaims = Depends(get_current_user),
    audit = Depends(get_audit),
):
    # Enforce admin role for this route
    if claims.role != "admin":
        raise ApiError(ErrorCode.auth_invalid, status_code=403, detail="Admin access required")
        
    feedback = await audit.get_low_quality_feedback(limit=limit, offset=offset, tenant_id=claims.tenant_id)
    return {"data": feedback}


@router.get("/api/admin/glossary")
async def get_glossary(
    claims: AuthClaims = Depends(get_current_user),
    pool = Depends(get_db_pool),
):
    if claims.role != "admin":
        raise ApiError(ErrorCode.auth_invalid, status_code=403, detail="Admin access required")
    if not pool:
        return {"data": []}
        
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT tenant_id, workspace_name, metric_synonyms, table_synonyms, synonym_hits, total_hits, updated_at FROM admin_glossary_view WHERE tenant_id = $1 ORDER BY updated_at DESC",
            claims.tenant_id
        )
        
    import json
    results = []
    for r in rows:
        results.append({
            "tenant_id": str(r["tenant_id"]),
            "workspace_name": str(r["workspace_name"]),
            "metric_synonyms": json.loads(r["metric_synonyms"]) if isinstance(r["metric_synonyms"], str) else r["metric_synonyms"],
            "table_synonyms": json.loads(r["table_synonyms"]) if isinstance(r["table_synonyms"], str) else r["table_synonyms"],
            "synonym_hits": json.loads(r["synonym_hits"]) if isinstance(r["synonym_hits"], str) else r["synonym_hits"],
            "total_hits": r["total_hits"],
            "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None
        })
    return {"data": results}


@router.get("/api/admin/glossary/preview")
async def preview_glossary(
    text: str,
    tenant_id: str | None = None,
    claims: AuthClaims = Depends(get_current_user),
    pool = Depends(get_db_pool),
):
    """Run QueryRewriter with active tenant's glossary and return the enriched result."""
    if claims.role != "admin":
        raise ApiError(ErrorCode.auth_invalid, status_code=403, detail="Admin access required")
    if tenant_id and tenant_id != claims.tenant_id:
        raise ApiError(ErrorCode.auth_invalid, status_code=403, detail="Tenant ID mismatch")
    
    effective_tenant_id = claims.tenant_id

    import json
    from app.rag.query_rewriter import QueryRewriter
    
    metric_synonyms, table_synonyms = None, None
    if pool:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT metric_synonyms, table_synonyms FROM tenant_glossary WHERE tenant_id = $1",
                effective_tenant_id
            )
            if row:
                metric_synonyms = json.loads(row["metric_synonyms"]) if isinstance(row["metric_synonyms"], str) else row["metric_synonyms"]
                table_synonyms = json.loads(row["table_synonyms"]) if isinstance(row["table_synonyms"], str) else row["table_synonyms"]
    
    rewriter = QueryRewriter(metric_synonyms=metric_synonyms, table_synonyms=table_synonyms)
    result = rewriter.rewrite(text)
    
    return {
        "original": text,
        "rewritten": result.rewritten,
        "detected_metrics": result.detected_metrics,
        "detected_tables": result.detected_tables,
        "expanded_terms": result.expanded_terms[:10],
    }


@router.get("/api/admin/workspaces")
async def get_workspaces(
    claims: AuthClaims = Depends(get_current_user),
    pool = Depends(get_db_pool),
):
    if claims.role != "admin":
        raise ApiError(ErrorCode.auth_invalid, status_code=403, detail="Admin access required")
    if not pool:
        return {"data": []}
    
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id::text, workspace_name, has_glossary, total_turns, last_active_at FROM admin_workspaces_view WHERE id = $1 ORDER BY last_active_at DESC NULLS LAST",
            claims.tenant_id
        )
    return {"data": [dict(r) for r in rows]}


@router.get("/api/admin/stats")
async def get_stats(
    claims: AuthClaims = Depends(get_current_user),
    pool = Depends(get_db_pool),
):
    settings = get_settings()
    is_fake_mode = settings.auth_mode == "fake"
    
    if claims.role != "admin" and not is_fake_mode:
        raise ApiError(ErrorCode.auth_invalid, status_code=403, detail="Admin access required")
    if not pool:
        return {
            "total_workspaces": 0,
            "total_glossaries": 0,
            "total_turns": 0,
            "avg_latency": 0,
            "queries_today": 0,
            "error_rate_pct": 0.0,
        }
    
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT 
              (SELECT COUNT(*) FROM tenants WHERE id = $1) AS total_workspaces,
              (SELECT COUNT(*) FROM tenant_glossary WHERE tenant_id = $1) AS total_glossaries,
              COUNT(*) AS total_turns,
              AVG(latency_ms) AS avg_latency,
              COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '24 hours') AS queries_today,
              ROUND(100.0 * COUNT(*) FILTER (WHERE quality_flag = 'low') / NULLIF(COUNT(*), 0), 1) AS error_rate_pct
            FROM turns
            WHERE tenant_id = $1
        """, claims.tenant_id)
        
    return {
        "total_workspaces": row["total_workspaces"] or 0,
        "total_glossaries": row["total_glossaries"] or 0,
        "total_turns": row["total_turns"] or 0,
        "avg_latency": round(row["avg_latency"] or 0, 0),
        "queries_today": row["queries_today"] or 0,
        "error_rate_pct": float(row["error_rate_pct"] or 0.0),
    }


@router.post("/api/admin/glossary")
async def update_glossary(
    request: Request,
    claims: AuthClaims = Depends(get_current_user),
    pool = Depends(get_db_pool),
):
    if claims.role != "admin":
        raise ApiError(ErrorCode.auth_invalid, status_code=403, detail="Admin access required")
    if not pool:
        raise ApiError(ErrorCode.internal_error, status_code=500, detail="Database not configured")
        
    import json
    data = await request.json()
    req_tenant_id = data.get("tenant_id")
    if req_tenant_id and req_tenant_id != claims.tenant_id:
        raise ApiError(ErrorCode.auth_invalid, status_code=403, detail="Tenant ID mismatch")

    effective_tenant_id = claims.tenant_id
    metric_synonyms = data.get("metric_synonyms", {})
    table_synonyms = data.get("table_synonyms", {})
    
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO tenant_glossary (tenant_id, metric_synonyms, table_synonyms)
            VALUES ($1, $2, $3)
            ON CONFLICT (tenant_id) DO UPDATE 
            SET metric_synonyms = EXCLUDED.metric_synonyms,
                table_synonyms = EXCLUDED.table_synonyms,
                updated_at = NOW()
            """,
            effective_tenant_id,
            json.dumps(metric_synonyms),
            json.dumps(table_synonyms)
        )
        
    return StatusResponse(status="recorded")

