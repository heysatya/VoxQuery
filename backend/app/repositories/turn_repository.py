"""Durable turn persistence repository. Replaces in-memory PipelineOrchestrator.turns."""

from __future__ import annotations
import json
import logging
from typing import Any
from uuid import UUID
import asyncpg

from app.models.contracts import (
    AuthClaims,
    ChartType,
    ConfidenceTier,
    InputModality,
    QualityFlag,
    ResultPayload,
    ResultShape,
    TurnRecord,
)

logger = logging.getLogger(__name__)


class TurnRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def save(
        self,
        turn: TurnRecord,
        *,
        tenant_name: str | None = None,
        source_tables: list[str] | None = None,
        filter_predicates: list[dict[str, Any]] | None = None,
    ) -> None:
        """Persists a TurnRecord to Postgres with multi-tenant scoping and row capping."""
        source_tables = source_tables or []
        filter_predicates = filter_predicates or []

        # Cap full_result rows to 500 max per turn to bound storage payload
        full_result_json = None
        if turn.full_result:
            capped_result = turn.full_result.model_copy()
            if len(capped_result.rows) > 500:
                capped_result.rows = capped_result.rows[:500]
                capped_result.preview_row_count = 500
                capped_result.is_truncated = True
            full_result_json = capped_result.model_dump_json()

        result_json_str = turn.result_json.model_dump_json() if turn.result_json else "{}"
        modality_str = (
            turn.input_modality.value
            if hasattr(turn.input_modality, "value")
            else str(turn.input_modality)
        )
        chart_type_str = turn.chart_type.value if turn.chart_type else None
        confidence_tier_str = turn.confidence_tier.value if turn.confidence_tier else None

        async with self._pool.acquire() as conn:
            # Ensure tenant, user, session, and conversation records exist for foreign key constraints
            tenant_display = tenant_name or f"Tenant {turn.tenant_id[:8]}"
            await conn.execute(
                "INSERT INTO tenants (id, name) VALUES ($1, $2) ON CONFLICT (id) DO NOTHING",
                turn.tenant_id,
                tenant_display,
            )
            await conn.execute(
                """
                INSERT INTO users (id, email)
                VALUES ($1, $2)
                ON CONFLICT (id) DO NOTHING
                """,
                turn.user_id,
                f"user-{turn.user_id}@system.local",
            )
            await conn.execute(
                """
                INSERT INTO sessions (session_id, tenant_id, user_id, last_active_at)
                VALUES ($1, $2, $3, NOW())
                ON CONFLICT (session_id) DO UPDATE SET last_active_at = NOW()
                """,
                turn.session_id,
                turn.tenant_id,
                turn.user_id,
            )
            await conn.execute(
                """
                INSERT INTO conversations (id, user_id, tenant_id, title)
                VALUES ($1, $2, $3, 'Voice Session')
                ON CONFLICT (id) DO NOTHING
                """,
                turn.conversation_id,
                turn.user_id,
                turn.tenant_id,
            )

            await conn.execute(
                """
                INSERT INTO turns (
                    turn_id, session_id, conversation_id, parent_turn_id, tenant_id, user_id,
                    user_input, input_modality, generated_sql, source_tables, filter_predicates,
                    chart_type, chart_rationale, confidence_tier, composite_score,
                    result_json, full_result, anomalies, proactive_questions,
                    quality_flag, latency_ms, created_at, completed, feedback_submitted
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21,$22,$23,$24)
                ON CONFLICT (turn_id) DO UPDATE SET
                    input_modality = EXCLUDED.input_modality,
                    generated_sql = EXCLUDED.generated_sql,
                    source_tables = EXCLUDED.source_tables,
                    filter_predicates = EXCLUDED.filter_predicates,
                    chart_type = EXCLUDED.chart_type,
                    chart_rationale = EXCLUDED.chart_rationale,
                    confidence_tier = EXCLUDED.confidence_tier,
                    composite_score = EXCLUDED.composite_score,
                    result_json = EXCLUDED.result_json,
                    full_result = EXCLUDED.full_result,
                    anomalies = EXCLUDED.anomalies,
                    proactive_questions = EXCLUDED.proactive_questions,
                    quality_flag = EXCLUDED.quality_flag,
                    latency_ms = EXCLUDED.latency_ms,
                    completed = EXCLUDED.completed
                """,
                turn.turn_id,
                turn.session_id,
                turn.conversation_id,
                turn.parent_turn_id,
                turn.tenant_id,
                turn.user_id,
                turn.user_input,
                modality_str,
                turn.generated_sql,
                source_tables,
                json.dumps(filter_predicates),
                chart_type_str,
                turn.chart_rationale or "",
                confidence_tier_str,
                turn.composite_score or 1.0,
                result_json_str,
                full_result_json,
                json.dumps([]),
                json.dumps(turn.proactive_questions),
                turn.quality_flag.value
                if hasattr(turn.quality_flag, "value")
                else str(turn.quality_flag),
                turn.latency_ms,
                turn.created_at,
                turn.completed,
                turn.feedback_submitted,
            )

    async def get_session_turns(
        self, session_id: UUID, claims: AuthClaims, *, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Tenant-scoped turn fetch — enforces tenant_id = claims.tenant_id."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM turns
                WHERE session_id = $1 AND tenant_id = $2
                ORDER BY created_at ASC
                LIMIT $3
                """,
                session_id,
                claims.tenant_id,
                limit,
            )
        return [self._parse_row(r) for r in rows]

    async def get_turn(self, turn_id: UUID, claims: AuthClaims) -> dict[str, Any] | None:
        """Tenant-scoped single turn fetch."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM turns WHERE turn_id = $1 AND tenant_id = $2",
                turn_id,
                claims.tenant_id,
            )
        return self._parse_row(row) if row else None

    async def update_anomalies(self, turn_id: UUID, anomalies: list[dict[str, Any]]) -> None:
        """Update anomalies JSONB column for a completed turn."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE turns SET anomalies = $2 WHERE turn_id = $1",
                turn_id,
                json.dumps(anomalies),
            )

    async def record_feedback(
        self,
        turn_id: UUID,
        claims: AuthClaims,
        quality_flag: str,
    ) -> str:
        """Atomically record one feedback decision within the caller's tenant."""
        async with self._pool.acquire() as conn:
            updated = await conn.fetchval(
                """
                UPDATE turns
                SET quality_flag = $3, feedback_submitted = TRUE
                WHERE turn_id = $1
                  AND tenant_id = $2
                  AND user_id = $4
                  AND feedback_submitted = FALSE
                RETURNING turn_id
                """,
                turn_id,
                claims.tenant_id,
                quality_flag,
                claims.user_id,
            )
            if updated is not None:
                return "recorded"

            exists = await conn.fetchval(
                """
                SELECT feedback_submitted
                FROM turns
                WHERE turn_id = $1 AND tenant_id = $2 AND user_id = $3
                """,
                turn_id,
                claims.tenant_id,
                claims.user_id,
            )
            if exists is True:
                return "duplicate"
            return "not_found"

    async def get_prior_session_questions(
        self,
        claims: AuthClaims,
        current_session_id: UUID | None = None,
        limit: int = 3,
    ) -> list[str]:
        """
        Retrieves the 2-3 most recent distinct user questions from the authenticated user's
        most recent prior session.
        """
        async with self._pool.acquire() as conn:
            prior_session_row = await conn.fetchrow(
                """
                SELECT session_id
                FROM sessions
                WHERE tenant_id = $1 AND user_id = $2
                  AND ($3::uuid IS NULL OR session_id != $3)
                ORDER BY last_active_at DESC
                LIMIT 1
                """,
                claims.tenant_id,
                claims.user_id,
                current_session_id,
            )
            if not prior_session_row:
                return []

            prior_sid = prior_session_row["session_id"]
            rows = await conn.fetch(
                """
                SELECT user_input
                FROM turns
                WHERE session_id = $1 AND tenant_id = $2
                ORDER BY created_at DESC
                """,
                prior_sid,
                claims.tenant_id,
            )

        seen: set[str] = set()
        distinct_questions: list[str] = []
        for r in rows:
            q = str(r["user_input"]).strip()
            if q and q not in seen:
                seen.add(q)
                distinct_questions.append(q)
                if len(distinct_questions) >= limit:
                    break
        return distinct_questions

    def _parse_row(self, row: asyncpg.Record | None) -> dict[str, Any] | None:
        if row is None:
            return None
        d = dict(row)
        if isinstance(d.get("filter_predicates"), str):
            d["filter_predicates"] = json.loads(d["filter_predicates"])
        if isinstance(d.get("anomalies"), str):
            d["anomalies"] = json.loads(d["anomalies"])
        if isinstance(d.get("proactive_questions"), str):
            d["proactive_questions"] = json.loads(d["proactive_questions"])
        if isinstance(d.get("result_json"), str):
            d["result_json"] = json.loads(d["result_json"])
        if isinstance(d.get("full_result"), str):
            d["full_result"] = json.loads(d["full_result"])
        return d

    @staticmethod
    def to_model(row: dict[str, Any]) -> TurnRecord:
        """Rehydrate the API-facing turn model from a tenant-scoped DB row."""
        result_json = None
        if row.get("result_json"):
            try:
                result_json = ResultShape.model_validate(row["result_json"])
            except Exception:
                logger.warning("turn.result_shape_invalid turn_id=%s", row.get("turn_id"))

        full_result = None
        if row.get("full_result"):
            try:
                full_result = ResultPayload.model_validate(row["full_result"])
            except Exception:
                logger.warning("turn.full_result_invalid turn_id=%s", row.get("turn_id"))

        chart_type = None
        if row.get("chart_type"):
            try:
                chart_type = ChartType(str(row["chart_type"]))
            except ValueError:
                pass

        confidence_tier = None
        if row.get("confidence_tier"):
            try:
                confidence_tier = ConfidenceTier(str(row["confidence_tier"]))
            except ValueError:
                pass

        try:
            input_modality = InputModality(str(row.get("input_modality") or "text"))
        except ValueError:
            input_modality = InputModality.text

        try:
            quality_flag = QualityFlag(str(row.get("quality_flag") or "ok"))
        except ValueError:
            quality_flag = QualityFlag.ok

        return TurnRecord(
            turn_id=UUID(str(row.get("turn_id") or row.get("id"))),
            session_id=UUID(str(row["session_id"])),
            conversation_id=UUID(str(row["conversation_id"])),
            parent_turn_id=UUID(str(row["parent_turn_id"])) if row.get("parent_turn_id") else None,
            user_id=str(row["user_id"]),
            tenant_id=str(row["tenant_id"]),
            user_input=str(row.get("user_input") or ""),
            raw_transcript=row.get("raw_transcript"),
            deepgram_confidence_raw=row.get("deepgram_confidence_raw"),
            generated_sql=str(row.get("generated_sql") or ""),
            result_json=result_json,
            chart_type=chart_type,
            chart_rationale=str(row.get("chart_rationale") or ""),
            confidence_tier=confidence_tier,
            composite_score=row.get("composite_score"),
            clarification_triggered=bool(row.get("clarification_triggered", False)),
            quality_flag=quality_flag,
            source=str(row.get("source") or "user"),
            input_modality=input_modality,
            latency_ms=int(row.get("latency_ms") or 0),
            created_at=row["created_at"],
            completed=bool(row.get("completed", False)),
            feedback_submitted=bool(row.get("feedback_submitted", False)),
            full_result=full_result,
            proactive_questions=row.get("proactive_questions") or [],
        )

    async def get_query_history(
        self,
        claims: AuthClaims,
        *,
        limit: int = 50,
        offset: int = 0,
        search: str | None = None,
        quality_flag: str | None = None,
        confidence_tier: str | None = None,
        completed_only: bool = False,
    ):
        """
        Paginated, tenant-scoped query history for admin use.
        Uses bounded pagination; never loads the full turns table into Python.
        User IDs are anonymised in the response (first 8 chars + '...').
        """
        from app.models.contracts import QueryHistoryPage, QueryHistorySummary

        conditions = ["tenant_id = $1"]
        params: list[Any] = [claims.tenant_id]
        idx = 2

        if search:
            conditions.append(f"user_input ILIKE ${idx}")
            params.append(f"%{search[:200]}%")
            idx += 1

        if quality_flag:
            conditions.append(f"quality_flag = ${idx}")
            params.append(quality_flag)
            idx += 1

        if confidence_tier:
            conditions.append(f"confidence_tier = ${idx}")
            params.append(confidence_tier)
            idx += 1

        if completed_only:
            conditions.append("completed = TRUE")

        where_clause = " AND ".join(conditions)

        async with self._pool.acquire() as conn:
            total_count = await conn.fetchval(
                f"SELECT COUNT(*) FROM turns WHERE {where_clause}",
                *params,
            )
            rows = await conn.fetch(
                f"""
                SELECT
                    turn_id, user_id, user_input, chart_type, confidence_tier,
                    quality_flag, latency_ms, result_json, created_at, completed,
                    clarification_triggered, input_modality
                FROM turns
                WHERE {where_clause}
                ORDER BY created_at DESC
                LIMIT ${idx} OFFSET ${idx + 1}
                """,
                *params,
                limit,
                offset,
            )

        items = []
        for row in rows:
            user_id_str = str(row["user_id"] or "")
            user_display = f"USER-{user_id_str[:8].upper()}..."

            result_json_val = row.get("result_json") or {}
            if isinstance(result_json_val, str):
                try:
                    result_json_val = json.loads(result_json_val)
                except Exception:
                    result_json_val = {}

            row_count = (
                result_json_val.get("row_count") if isinstance(result_json_val, dict) else None
            )
            created_at = row["created_at"]
            created_at_str = (
                created_at.isoformat() if hasattr(created_at, "isoformat") else str(created_at)
            )

            items.append(
                QueryHistorySummary(
                    turn_id=str(row["turn_id"]),
                    user_display=user_display,
                    user_input=str(row.get("user_input") or ""),
                    chart_type=row.get("chart_type"),
                    confidence_tier=row.get("confidence_tier"),
                    quality_flag=str(row.get("quality_flag") or "ok"),
                    latency_ms=int(row.get("latency_ms") or 0),
                    row_count=row_count,
                    created_at=created_at_str,
                    completed=bool(row.get("completed", False)),
                    clarification_triggered=bool(row.get("clarification_triggered", False)),
                    input_modality=str(row.get("input_modality") or "text"),
                )
            )

        page_size = limit
        page = (offset // max(1, page_size)) + 1

        return QueryHistoryPage(
            items=items,
            total_count=int(total_count or 0),
            page=page,
            page_size=page_size,
            has_more=(offset + limit) < int(total_count or 0),
        )

    async def get_tenant_analytics(
        self,
        claims: AuthClaims,
        *,
        days: int = 30,
    ):
        """
        Aggregated, tenant-scoped analytics for admin.
        All aggregation is done server-side in SQL — no full table scan in Python.
        Bounded by `days` (max 90).
        """
        from app.models.contracts import (
            TenantAnalytics,
            ConfidenceDistribution,
            FeedbackDistribution,
            DailyQueryCount,
            TopQuestion,
        )

        days = max(1, min(days, 90))

        async with self._pool.acquire() as conn:
            agg = await conn.fetchrow(
                """
                SELECT
                    COUNT(*)                                                                        AS total_queries,
                    COUNT(*) FILTER (WHERE completed = TRUE)                                       AS completed_queries,
                    COUNT(*) FILTER (WHERE completed = FALSE)                                      AS failed_queries,
                    COALESCE(AVG(latency_ms), 0)                                                   AS avg_latency_ms,
                    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY latency_ms)                        AS p50_latency_ms,
                    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY latency_ms)                       AS p95_latency_ms,
                    COUNT(*) FILTER (WHERE clarification_triggered = TRUE)                         AS clarification_count,
                    COUNT(*) FILTER (WHERE quality_flag = 'low')                                   AS low_quality_count,
                    COUNT(*) FILTER (WHERE feedback_submitted = TRUE AND quality_flag != 'low')    AS positive_feedback,
                    COUNT(*) FILTER (WHERE feedback_submitted = TRUE AND quality_flag = 'low')     AS negative_feedback,
                    COUNT(*) FILTER (WHERE feedback_submitted = FALSE)                             AS unrated,
                    COUNT(DISTINCT user_id)                                                        AS active_users
                FROM turns
                WHERE tenant_id = $1
                  AND created_at > NOW() - ($2 || ' days')::INTERVAL
                """,
                claims.tenant_id,
                str(days),
            )

            conf_rows = await conn.fetch(
                """
                SELECT confidence_tier, COUNT(*) AS cnt
                FROM turns
                WHERE tenant_id = $1
                  AND created_at > NOW() - ($2 || ' days')::INTERVAL
                  AND confidence_tier IS NOT NULL
                GROUP BY confidence_tier
                """,
                claims.tenant_id,
                str(days),
            )

            daily_rows = await conn.fetch(
                """
                SELECT DATE(created_at)::TEXT AS day, COUNT(*) AS cnt
                FROM turns
                WHERE tenant_id = $1
                  AND created_at > NOW() - ($2 || ' days')::INTERVAL
                GROUP BY DATE(created_at)
                ORDER BY day ASC
                """,
                claims.tenant_id,
                str(days),
            )

            top_q_rows = await conn.fetch(
                """
                SELECT LEFT(user_input, 200) AS q, COUNT(*) AS cnt
                FROM turns
                WHERE tenant_id = $1
                  AND created_at > NOW() - ($2 || ' days')::INTERVAL
                  AND user_input IS NOT NULL
                  AND user_input != ''
                GROUP BY LEFT(user_input, 200)
                ORDER BY cnt DESC
                LIMIT 10
                """,
                claims.tenant_id,
                str(days),
            )

            saved_count: int = 0
            try:
                saved_count = (
                    await conn.fetchval(
                        "SELECT COUNT(*) FROM pinned_analyses WHERE tenant_id = $1",
                        claims.tenant_id,
                    )
                    or 0
                )
            except Exception:
                pass

        total = int(agg["total_queries"] or 0)
        completed = int(agg["completed_queries"] or 0)
        clarification_count = int(agg["clarification_count"] or 0)
        low_quality_count = int(agg["low_quality_count"] or 0)

        conf_dist = ConfidenceDistribution()
        for row in conf_rows:
            tier = str(row["confidence_tier"] or "").lower()
            cnt = int(row["cnt"] or 0)
            if tier == "high":
                conf_dist.high = cnt
            elif tier == "medium":
                conf_dist.medium = cnt
            elif tier == "low":
                conf_dist.low = cnt

        feedback_dist = FeedbackDistribution(
            positive=int(agg["positive_feedback"] or 0),
            negative=int(agg["negative_feedback"] or 0),
            unrated=int(agg["unrated"] or 0),
        )

        return TenantAnalytics(
            period_days=days,
            total_queries=total,
            completed_queries=completed,
            failed_queries=int(agg["failed_queries"] or 0),
            success_rate_pct=round(100.0 * completed / max(1, total), 1),
            avg_latency_ms=round(float(agg["avg_latency_ms"] or 0), 1),
            p50_latency_ms=round(float(agg["p50_latency_ms"]), 1)
            if agg.get("p50_latency_ms")
            else None,
            p95_latency_ms=round(float(agg["p95_latency_ms"]), 1)
            if agg.get("p95_latency_ms")
            else None,
            queries_per_day=[
                DailyQueryCount(date=r["day"], count=int(r["cnt"])) for r in daily_rows
            ],
            top_questions=[TopQuestion(user_input=r["q"], count=int(r["cnt"])) for r in top_q_rows],
            confidence_distribution=conf_dist,
            clarification_rate_pct=round(100.0 * clarification_count / max(1, total), 1),
            feedback_distribution=feedback_dist,
            low_quality_rate_pct=round(100.0 * low_quality_count / max(1, total), 1),
            active_users=int(agg["active_users"] or 0),
            saved_analyses_count=int(saved_count),
        )
