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
    UserPreferences,
    PriorSessionSummaryResponse,
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


def get_db_pool(request: Request):
    return getattr(request.app.state, "db_pool", None)


async def _check_rate_limit(rate_limiter: RateLimiter, claims: AuthClaims) -> None:
    result = await rate_limiter.check_rate_limit(str(claims.user_id), str(claims.tenant_id))
    if not result.available:
        raise ApiError(
            ErrorCode.service_unavailable,
            status_code=503,
            detail="Request protection is temporarily unavailable.",
        )
    if not result.ok:
        raise ApiError(
            ErrorCode.rate_limit_exceeded,
            status_code=429,
            detail=f"Retry after {result.retry_after_seconds}s",
        )


async def _get_turn_for_user(
    turn_id: UUID,
    claims: AuthClaims,
    pipeline: PipelineOrchestrator,
    db_pool,
):
    try:
        return pipeline.get_turn_for_user(turn_id, claims)
    except ApiError as exc:
        if exc.code != ErrorCode.turn_not_found or db_pool is None:
            raise

    from app.repositories.turn_repository import TurnRepository

    row = await TurnRepository(db_pool).get_turn(turn_id, claims)
    if row is None:
        raise ApiError(ErrorCode.turn_not_found, status_code=404)
    return TurnRepository.to_model(row)


@router.post("/api/session", response_model=SessionCreateResponse, status_code=201)
async def create_session(
    request: SessionCreateRequest,
    claims: AuthClaims = Depends(get_current_user),
    sessions: InMemorySessionStore = Depends(get_sessions),
    pipeline: PipelineOrchestrator = Depends(get_pipeline),
) -> SessionCreateResponse:
    if request.tenant_id and request.tenant_id != claims.tenant_id:
        raise ApiError(
            ErrorCode.auth_invalid,
            status_code=401,
            detail="Requested tenant_id does not match authorization claims",
        )
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


@router.get("/api/memory/prior-session-summary", response_model=PriorSessionSummaryResponse)
async def get_prior_session_summary(
    current_session_id: UUID | None = None,
    claims: AuthClaims = Depends(get_current_user),
    db_pool=Depends(get_db_pool),
) -> PriorSessionSummaryResponse:
    """
    Retrieve 2-3 most recent distinct questions from the user's prior session.
    """
    if not db_pool:
        return PriorSessionSummaryResponse(questions=[])
    from app.repositories.turn_repository import TurnRepository

    repo = TurnRepository(db_pool)
    questions = await repo.get_prior_session_questions(
        claims, current_session_id=current_session_id, limit=3
    )
    return PriorSessionSummaryResponse(questions=questions)


@router.post("/api/query", response_model=QueryAcceptedResponse, status_code=202)
async def submit_query(
    request: QueryRequest,
    claims: AuthClaims = Depends(get_current_user),
    pipeline: PipelineOrchestrator = Depends(get_pipeline),
    rate_limiter: RateLimiter = Depends(get_rate_limiter),
) -> QueryAcceptedResponse:
    await _check_rate_limit(rate_limiter, claims)

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
    await _check_rate_limit(rate_limiter, claims)

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
    db_pool=Depends(get_db_pool),
) -> ResultResponse:
    turn = await _get_turn_for_user(turn_id, claims, pipeline, db_pool)
    if not turn.completed:
        raise ApiError(ErrorCode.turn_processing, status_code=202)
    if not turn.full_result or not turn.chart_type or not turn.confidence_tier:
        raise ApiError(ErrorCode.turn_processing, status_code=202)
    confidence_reasons = confidence_reasons_for_turn(turn)
    from app.services.anomaly_detector import check_turn_anomaly

    anomaly = check_turn_anomaly(turn.full_result)
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
        anomaly=anomaly,
        from_cache=turn.from_cache,
    )


@router.post("/api/feedback", response_model=StatusResponse)
async def submit_feedback(
    request: FeedbackRequest,
    claims: AuthClaims = Depends(get_current_user),
    pipeline: PipelineOrchestrator = Depends(get_pipeline),
    sessions: InMemorySessionStore = Depends(get_sessions),
    db_pool=Depends(get_db_pool),
) -> StatusResponse:
    turn = await _get_turn_for_user(request.turn_id, claims, pipeline, db_pool)
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
    if db_pool:
        from app.repositories.turn_repository import TurnRepository

        feedback_status = await TurnRepository(db_pool).record_feedback(
            request.turn_id,
            claims,
            quality_flag,
        )
        if feedback_status == "duplicate":
            raise ApiError(ErrorCode.feedback_duplicate, status_code=409)
        if feedback_status == "not_found":
            pipeline.audit.enqueue_feedback(str(request.turn_id), quality_flag)
    else:
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
        option_selected,
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
    audit=Depends(get_audit),
):
    # Enforce admin role for this route
    if claims.role != "admin":
        raise ApiError(ErrorCode.auth_invalid, status_code=403, detail="Admin access required")

    feedback = await audit.get_low_quality_feedback(
        limit=limit, offset=offset, tenant_id=claims.tenant_id
    )
    return {"data": feedback}


@router.get("/api/admin/glossary")
async def get_glossary(
    claims: AuthClaims = Depends(get_current_user),
    pool=Depends(get_db_pool),
):
    if claims.role != "admin":
        raise ApiError(ErrorCode.auth_invalid, status_code=403, detail="Admin access required")
    if not pool:
        return {"data": []}

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT tenant_id, workspace_name, metric_synonyms, table_synonyms, synonym_hits, total_hits, updated_at FROM admin_glossary_view WHERE tenant_id = $1 ORDER BY updated_at DESC",
            claims.tenant_id,
        )

    import json

    results = []
    for r in rows:
        results.append(
            {
                "tenant_id": str(r["tenant_id"]),
                "workspace_name": str(r["workspace_name"]),
                "metric_synonyms": json.loads(r["metric_synonyms"])
                if isinstance(r["metric_synonyms"], str)
                else r["metric_synonyms"],
                "table_synonyms": json.loads(r["table_synonyms"])
                if isinstance(r["table_synonyms"], str)
                else r["table_synonyms"],
                "synonym_hits": json.loads(r["synonym_hits"])
                if isinstance(r["synonym_hits"], str)
                else r["synonym_hits"],
                "total_hits": r["total_hits"],
                "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
            }
        )
    return {"data": results}


@router.get("/api/admin/glossary/preview")
async def preview_glossary(
    text: str,
    tenant_id: str | None = None,
    claims: AuthClaims = Depends(get_current_user),
    pool=Depends(get_db_pool),
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
                effective_tenant_id,
            )
            if row:
                metric_synonyms = (
                    json.loads(row["metric_synonyms"])
                    if isinstance(row["metric_synonyms"], str)
                    else row["metric_synonyms"]
                )
                table_synonyms = (
                    json.loads(row["table_synonyms"])
                    if isinstance(row["table_synonyms"], str)
                    else row["table_synonyms"]
                )

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
    pool=Depends(get_db_pool),
):
    if claims.role != "admin":
        raise ApiError(ErrorCode.auth_invalid, status_code=403, detail="Admin access required")
    if not pool:
        return {"data": []}

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id::text, workspace_name, has_glossary, total_turns, last_active_at FROM admin_workspaces_view WHERE id = $1 ORDER BY last_active_at DESC NULLS LAST",
            claims.tenant_id,
        )
    return {"data": [dict(r) for r in rows]}


@router.get("/api/admin/stats")
async def get_stats(
    claims: AuthClaims = Depends(get_current_user),
    pool=Depends(get_db_pool),
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
        row = await conn.fetchrow(
            """
            SELECT 
              (SELECT COUNT(*) FROM tenants WHERE id = $1) AS total_workspaces,
              (SELECT COUNT(*) FROM tenant_glossary WHERE tenant_id = $1) AS total_glossaries,
              COUNT(*) AS total_turns,
              AVG(latency_ms) AS avg_latency,
              COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '24 hours') AS queries_today,
              ROUND(100.0 * COUNT(*) FILTER (WHERE quality_flag = 'low') / NULLIF(COUNT(*), 0), 1) AS error_rate_pct
            FROM turns
            WHERE tenant_id = $1
        """,
            claims.tenant_id,
        )

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
    pool=Depends(get_db_pool),
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
            json.dumps(table_synonyms),
        )

    return StatusResponse(status="recorded")


@router.get("/api/preferences", response_model=UserPreferences)
async def get_preferences(
    claims: AuthClaims = Depends(get_current_user),
    db_pool=Depends(get_db_pool),
) -> UserPreferences:
    """
    Get user preferences.
    """
    from app.services.preferences import get_user_preferences

    if db_pool is None:
        raise ApiError(
            ErrorCode.service_unavailable, status_code=501, detail="Database pool unavailable"
        )
    return await get_user_preferences(claims.user_id, db_pool)


@router.patch("/api/preferences", response_model=UserPreferences)
async def patch_preferences(
    request: Request,
    claims: AuthClaims = Depends(get_current_user),
    db_pool=Depends(get_db_pool),
) -> UserPreferences:
    """
    Update user preferences.
    """
    from app.services.preferences import update_user_preferences

    if db_pool is None:
        raise ApiError(
            ErrorCode.service_unavailable, status_code=501, detail="Database pool unavailable"
        )
    data = await request.json()
    return await update_user_preferences(
        claims.user_id,
        db_pool,
        email_briefing_enabled=data.get("email_briefing_enabled", False),
        email=data.get("email"),
        delivery_time=data.get("delivery_time", "09:00"),
        timezone=data.get("timezone", "UTC"),
    )


@router.get("/api/drilldown/{turn_id}")
async def get_drilldown(
    turn_id: UUID,
    claims: AuthClaims = Depends(get_current_user),
    settings=Depends(get_settings),
    pipeline: PipelineOrchestrator = Depends(get_pipeline),
    db_pool=Depends(get_db_pool),
) -> list[dict]:
    """
    Fetch top 10 raw transaction rows for a given turn scoped to tenant claims.
    """
    from app.services.drilldown import get_row_drilldown
    from app.repositories.turn_repository import TurnRepository

    turn_repo = TurnRepository(db_pool) if db_pool else None
    return await get_row_drilldown(
        turn_id,
        claims=claims,
        settings=settings,
        turn_repo=turn_repo,
        warehouse=pipeline.warehouse,
        pipeline_turns=pipeline.turns,
    )


# ── Admin: real query history ─────────────────────────────────────────────────


@router.get("/api/admin/history")
async def get_admin_history(
    request: Request,
    claims: AuthClaims = Depends(get_current_user),
    pool=Depends(get_db_pool),
    page: int = 1,
    page_size: int = 50,
    search: str = "",
    quality_flag: str = "",
    confidence_tier: str = "",
    completed_only: bool = False,
):
    """
    Paginated, tenant-scoped query history for admin inspection.
    Returns typed QueryHistoryPage — no raw warehouse rows, no cross-tenant data.
    """
    settings = get_settings()
    is_fake_mode = settings.auth_mode == "fake"
    if claims.role != "admin" and not is_fake_mode:
        raise ApiError(ErrorCode.auth_invalid, status_code=403, detail="Admin access required")

    if not pool:
        from app.models.contracts import QueryHistoryPage

        return QueryHistoryPage(
            items=[], total_count=0, page=page, page_size=page_size, has_more=False
        )

    from app.repositories.turn_repository import TurnRepository
    from app.models.contracts import QueryHistoryPage

    repo = TurnRepository(pool)
    page_size = max(1, min(page_size, 100))
    page = max(1, page)
    result = await repo.get_query_history(
        claims,
        limit=page_size,
        offset=(page - 1) * page_size,
        search=search or None,
        quality_flag=quality_flag or None,
        confidence_tier=confidence_tier or None,
        completed_only=completed_only,
    )
    return result


@router.get("/api/admin/history/{turn_id}")
async def get_admin_history_detail(
    turn_id: UUID,
    claims: AuthClaims = Depends(get_current_user),
    pool=Depends(get_db_pool),
):
    """
    Detail view of a single turn for admin. Includes generated_sql (admin-visible).
    """
    settings = get_settings()
    is_fake_mode = settings.auth_mode == "fake"
    if claims.role != "admin" and not is_fake_mode:
        raise ApiError(ErrorCode.auth_invalid, status_code=403, detail="Admin access required")

    if not pool:
        raise ApiError(
            ErrorCode.service_unavailable, status_code=503, detail="Database unavailable"
        )

    from app.repositories.turn_repository import TurnRepository
    from app.models.contracts import QueryHistoryDetail
    import json

    repo = TurnRepository(pool)
    row = await repo.get_turn(turn_id, claims)
    if row is None:
        raise ApiError(ErrorCode.turn_not_found, status_code=404)

    user_hash = str(row.get("user_id", ""))[:8].upper() + "..."
    result_json = row.get("result_json") or {}
    if isinstance(result_json, str):
        try:
            result_json = json.loads(result_json)
        except Exception:
            result_json = {}

    return QueryHistoryDetail(
        turn_id=str(row["turn_id"]),
        user_display=f"USER-{user_hash}",
        user_input=str(row.get("user_input") or ""),
        generated_sql=str(row.get("generated_sql") or ""),
        chart_type=row.get("chart_type"),
        confidence_tier=row.get("confidence_tier"),
        quality_flag=str(row.get("quality_flag") or "ok"),
        latency_ms=int(row.get("latency_ms") or 0),
        row_count=result_json.get("row_count"),
        created_at=row["created_at"].isoformat()
        if hasattr(row.get("created_at"), "isoformat")
        else str(row.get("created_at", "")),
        completed=bool(row.get("completed", False)),
        clarification_triggered=bool(row.get("clarification_triggered", False)),
        input_modality=str(row.get("input_modality") or "text"),
        result_columns=result_json.get("columns") or [],
    )


# ── Admin: real tenant analytics ──────────────────────────────────────────────


@router.get("/api/admin/analytics")
async def get_admin_analytics(
    claims: AuthClaims = Depends(get_current_user),
    pool=Depends(get_db_pool),
    days: int = 30,
):
    """
    Aggregated, tenant-scoped analytics. Bounded by days parameter (max 90).
    All aggregation is done server-side in SQL — never loads full turns table in Python.
    """
    settings = get_settings()
    is_fake_mode = settings.auth_mode == "fake"
    if claims.role != "admin" and not is_fake_mode:
        raise ApiError(ErrorCode.auth_invalid, status_code=403, detail="Admin access required")

    days = max(1, min(days, 90))

    if not pool:
        from app.models.contracts import (
            TenantAnalytics,
            ConfidenceDistribution,
            FeedbackDistribution,
        )

        return TenantAnalytics(
            period_days=days,
            total_queries=0,
            completed_queries=0,
            failed_queries=0,
            success_rate_pct=0.0,
            avg_latency_ms=0.0,
            queries_per_day=[],
            top_questions=[],
            confidence_distribution=ConfidenceDistribution(),
            clarification_rate_pct=0.0,
            feedback_distribution=FeedbackDistribution(),
            low_quality_rate_pct=0.0,
            active_users=0,
            saved_analyses_count=0,
        )

    from app.repositories.turn_repository import TurnRepository

    repo = TurnRepository(pool)
    return await repo.get_tenant_analytics(claims, days=days)


# ── Admin: real system health ─────────────────────────────────────────────────


@router.get("/api/admin/health")
async def get_admin_health(
    request: Request,
    claims: AuthClaims = Depends(get_current_user),
    pool=Depends(get_db_pool),
):
    """
    Real system health check for admin dashboard.
    Checks: api, postgres, redis, warehouse config, llm config, stt, tts, scheduler.
    No secrets, DSNs, or JWTs are included in the response.
    Each check has a 2-second timeout max.
    """
    import asyncio
    from datetime import UTC, datetime
    from app.models.contracts import SystemHealthResponse, HealthCheckItem

    settings = get_settings()
    is_fake_mode = settings.auth_mode == "fake"
    if claims.role != "admin" and not is_fake_mode:
        raise ApiError(ErrorCode.auth_invalid, status_code=403, detail="Admin access required")

    now_iso = datetime.now(UTC).isoformat()
    checks: list[HealthCheckItem] = []

    # API: always healthy (we're responding)
    checks.append(
        HealthCheckItem(
            name="API", status="healthy", detail="Accepting requests", checked_at=now_iso
        )
    )

    # PostgreSQL
    postgres_status: str = "not_configured"
    if pool:
        try:
            async with asyncio.timeout(2.0):
                async with pool.acquire() as conn:
                    await conn.fetchval("SELECT 1")
            postgres_status = "healthy"
        except asyncio.TimeoutError:
            postgres_status = "degraded"
        except Exception:
            postgres_status = "unavailable"
    checks.append(HealthCheckItem(name="PostgreSQL", status=postgres_status, checked_at=now_iso))

    # Redis
    redis_status: str = "not_configured"
    try:
        sessions = request.app.state.sessions
        client = getattr(sessions, "client", None)
        if client is not None:
            async with asyncio.timeout(1.0):
                await client.ping()
            redis_status = "healthy"
    except asyncio.TimeoutError:
        redis_status = "degraded"
    except Exception:
        redis_status = "unavailable"
    checks.append(HealthCheckItem(name="Redis", status=redis_status, checked_at=now_iso))

    # Warehouse config
    warehouse_status: str = "not_configured"
    warehouse_detail: str | None = None
    try:
        sf_account = getattr(settings, "snowflake_account", None) or ""
        sf_db = getattr(settings, "snowflake_database", None) or ""
        if sf_account and sf_db:
            warehouse_status = "healthy"
            warehouse_detail = "Snowflake configured"
        else:
            warehouse_detail = "Snowflake account or database not set"
    except Exception:
        warehouse_status = "unavailable"
    checks.append(
        HealthCheckItem(
            name="Data Warehouse",
            status=warehouse_status,
            detail=warehouse_detail,
            checked_at=now_iso,
        )
    )

    # LLM config
    llm_status: str = "not_configured"
    try:
        openai_key = getattr(settings, "openai_api_key", None) or ""
        anthropic_key = getattr(settings, "anthropic_api_key", None) or ""
        if openai_key or anthropic_key:
            llm_status = "healthy"
    except Exception:
        pass
    checks.append(HealthCheckItem(name="LLM", status=llm_status, checked_at=now_iso))

    # STT (Deepgram)
    stt_status: str = "not_configured"
    try:
        dg_key = getattr(settings, "deepgram_api_key", None) or ""
        if dg_key:
            stt_status = "healthy"
    except Exception:
        pass
    checks.append(HealthCheckItem(name="Speech-to-Text", status=stt_status, checked_at=now_iso))

    # TTS
    tts_status: str = "not_configured"
    try:
        tts_key = (
            getattr(settings, "elevenlabs_api_key", None)
            or getattr(settings, "openai_api_key", None)
            or ""
        )
        if tts_key:
            tts_status = "healthy"
    except Exception:
        pass
    checks.append(HealthCheckItem(name="Text-to-Speech", status=tts_status, checked_at=now_iso))

    # Last briefing
    last_briefing_at: str | None = None
    if pool:
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT sent_at FROM briefing_send_log WHERE tenant_id = $1 ORDER BY sent_at DESC LIMIT 1",
                    claims.tenant_id,
                )
            if row:
                last_briefing_at = row["sent_at"].isoformat()
        except Exception:
            pass

    # Version
    version: str | None = None
    try:
        from app.api.version import _read_version

        version = _read_version()
    except Exception:
        pass

    # Overall status
    statuses = {c.status for c in checks}
    if "unavailable" in statuses:
        overall = "degraded"
    elif "degraded" in statuses:
        overall = "degraded"
    else:
        overall = "healthy"

    return SystemHealthResponse(
        overall=overall,
        checks=checks,
        last_briefing_at=last_briefing_at,
        version=version,
        checked_at=now_iso,
    )


# ── Admin: typed workspace detail ─────────────────────────────────────────────


@router.get("/api/admin/workspaces")
async def get_workspaces(
    claims: AuthClaims = Depends(get_current_user),
    pool=Depends(get_db_pool),
):
    """
    Return typed workspace detail for the current tenant.
    Scoped to claims.tenant_id — no cross-tenant inventory.
    """
    from app.models.contracts import WorkspaceDetail

    settings = get_settings()
    is_fake_mode = settings.auth_mode == "fake"
    if claims.role != "admin" and not is_fake_mode:
        raise ApiError(ErrorCode.auth_invalid, status_code=403, detail="Admin access required")

    if not pool:
        return {
            "data": [
                WorkspaceDetail(
                    workspace_name="Your Workspace",
                    tenant_status="unknown",
                    provisioning_status="unknown",
                    connection_health="not_configured",
                    has_glossary=False,
                    recent_query_count_7d=0,
                    total_queries=0,
                )
            ]
        }

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                t.id,
                t.name AS workspace_name,
                COALESCE(wv.has_glossary, FALSE) AS has_glossary,
                COALESCE(wv.total_turns, 0) AS total_turns,
                wv.last_active_at,
                (
                    SELECT COUNT(*) FROM turns
                    WHERE tenant_id = $1
                      AND created_at > NOW() - INTERVAL '7 days'
                ) AS recent_7d
            FROM tenants t
            LEFT JOIN admin_workspaces_view wv ON wv.id = t.id
            WHERE t.id = $1
            """,
            claims.tenant_id,
        )

    if not row:
        return {"data": []}

    workspace = WorkspaceDetail(
        workspace_name=str(row["workspace_name"] or "Your Workspace"),
        tenant_status="active",
        provisioning_status="provisioned",
        connection_health="healthy" if row.get("total_turns", 0) > 0 else "not_configured",
        last_query_at=row["last_active_at"].isoformat() if row.get("last_active_at") else None,
        has_glossary=bool(row.get("has_glossary", False)),
        recent_query_count_7d=int(row.get("recent_7d") or 0),
        total_queries=int(row.get("total_turns") or 0),
    )
    return {"data": [workspace]}
