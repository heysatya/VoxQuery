from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4

from app.config import Settings, get_settings
from app.core.token_count import TokenCounter
from app.models.contracts import (
    ApiError,
    AuthClaims,
    ClarificationState,
    ErrorCode,
    InputModality,
    QualityFlag,
    ResolvedEntity,
    ResultShape,
    SessionContextBlock,
    SessionHistoryTurn,
    VoiceSession,
)


class RedisClientProtocol(Protocol):
    def get(self, name: str) -> str | bytes | None: ...

    def setex(self, name: str, time: int, value: str) -> object: ...
    
    def delete(self, *names: str) -> int: ...

    def ping(self) -> object: ...


class InMemorySessionStore:
    def __init__(self, settings: Settings | None = None, counter: TokenCounter | None = None) -> None:
        self.settings = settings or get_settings()
        self.counter = counter or TokenCounter()
        self._sessions: dict[tuple[UUID, UUID], VoiceSession] = {}
        self._expires_at: dict[tuple[UUID, UUID], datetime] = {}

    def create(self, claims: AuthClaims) -> tuple[VoiceSession, datetime]:
        session = VoiceSession(
            session_id=uuid4(),
            user_id=claims.user_id,
            tenant_id=claims.tenant_id,
            conversation_id=uuid4(),
            snowflake_role=claims.snowflake_role,
        )
        expires_at = datetime.now(UTC) + timedelta(seconds=self.settings.session_ttl_seconds)
        key = self._key(session.tenant_id, session.session_id)
        self._sessions[key] = session
        self._expires_at[key] = expires_at
        return session, expires_at

    def get(self, tenant_id: UUID, session_id: UUID) -> VoiceSession | None:
        key = self._key(tenant_id, session_id)
        expires_at = self._expires_at.get(key)
        if not expires_at or expires_at <= datetime.now(UTC):
            self._sessions.pop(key, None)
            self._expires_at.pop(key, None)
            return None
        return self._sessions.get(key)

    def get_for_claims(self, claims: AuthClaims, session_id: UUID) -> VoiceSession | None:
        session = self.get(claims.tenant_id, session_id)
        if session is None or session.user_id != claims.user_id:
            return None
        return session

    def delete(self, tenant_id: UUID, session_id: UUID) -> None:
        key = self._key(tenant_id, session_id)
        self._sessions.pop(key, None)
        self._expires_at.pop(key, None)

    def save(self, session: VoiceSession) -> datetime:
        session.last_interaction_ts = datetime.now(UTC)
        key = self._key(session.tenant_id, session.session_id)
        expires_at = datetime.now(UTC) + timedelta(seconds=self.settings.session_ttl_seconds)
        self._sessions[key] = session
        self._expires_at[key] = expires_at
        return expires_at

    def context_block(self, session: VoiceSession) -> SessionContextBlock:
        resolved_token_count = self.counter.count_json(
            {term: entity.model_dump(mode="json") for term, entity in session.resolved_entities.items()}
        )
        remaining = max(0, self.settings.token_budget - resolved_token_count)
        selected_reversed: list[SessionHistoryTurn] = []
        used = 0
        for turn in reversed(session.history):
            turn_tokens = self.counter.count_json(turn.model_dump(mode="json"))
            if used + turn_tokens > remaining:
                continue
            selected_reversed.append(turn)
            used += turn_tokens
        selected = list(reversed(selected_reversed))
        turns_dropped = len(session.history) - len(selected)
        return SessionContextBlock(
            history=selected,
            resolved_entities=session.resolved_entities,
            truncated=turns_dropped > 0,
            turns_dropped=turns_dropped,
            truncation_note=(
                "Note: "
                f"{turns_dropped} earlier turns were omitted due to length. "
                "Resolved entity mappings from all turns are preserved above."
                if turns_dropped > 0
                else None
            ),
            token_count=resolved_token_count + used,
        )

    def append_turn(
        self,
        session: VoiceSession,
        *,
        turn_id: UUID,
        user_query: str,
        generated_sql: str,
        result_shape: ResultShape,
        confidence_tier,
        clarification_triggered: bool,
        input_modality: InputModality,
    ) -> SessionHistoryTurn:
        entry = SessionHistoryTurn(
            turn_index=session.turn_count,
            turn_id=turn_id,
            user_query=user_query,
            generated_sql=generated_sql,
            result_shape=result_shape,
            confidence_tier=confidence_tier,
            quality_flag=QualityFlag.ok,
            clarification_triggered=clarification_triggered,
            input_modality=input_modality,
        )
        session.history.append(entry)
        session.turn_count += 1
        self.save(session)
        return entry

    def set_pending_clarification(self, session: VoiceSession, state: ClarificationState) -> None:
        session.clarification_state = state
        self.save(session)

    def clear_pending_clarification(self, session: VoiceSession) -> None:
        session.clarification_state = None
        self.save(session)

    def add_resolved_entity(
        self, session: VoiceSession, term: str, resolution: str, option_selected: str
    ) -> None:
        if len(session.resolved_entities) >= 20 and term not in session.resolved_entities:
            oldest = min(
                session.resolved_entities.items(),
                key=lambda item: item[1].resolved_at_turn,
            )[0]
            session.resolved_entities.pop(oldest, None)
        session.resolved_entities[term] = ResolvedEntity(
            resolution=resolution,
            resolved_at_turn=session.turn_count,
            option_selected=option_selected,
        )
        self.save(session)

    def mark_low_quality(self, session: VoiceSession, turn_id: UUID) -> bool:
        for turn in session.history:
            if turn.turn_id == turn_id:
                turn.quality_flag = QualityFlag.low
                self.save(session)
                return True
        return False

    def health_status(self) -> str:
        return "local_stub"

    @staticmethod
    def _key(tenant_id: UUID, session_id: UUID) -> tuple[UUID, UUID]:
        return tenant_id, session_id


class RedisSessionStore(InMemorySessionStore):
    def __init__(
        self,
        settings: Settings | None = None,
        counter: TokenCounter | None = None,
        client: RedisClientProtocol | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.counter = counter or TokenCounter()
        self.client = client or self._client_from_settings(self.settings)

    def create(self, claims: AuthClaims) -> tuple[VoiceSession, datetime]:
        session = VoiceSession(
            session_id=uuid4(),
            user_id=claims.user_id,
            tenant_id=claims.tenant_id,
            conversation_id=uuid4(),
            snowflake_role=claims.snowflake_role,
        )
        expires_at = self.save(session)
        return session, expires_at

    def get(self, tenant_id: UUID, session_id: UUID) -> VoiceSession | None:
        try:
            raw = self.client.get(self.redis_key(tenant_id, session_id))
        except Exception as exc:
            raise self._session_unavailable(exc) from exc
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        try:
            session = VoiceSession.model_validate_json(raw)
        except Exception as exc:
            raise self._session_unavailable(exc) from exc
        if session.tenant_id != tenant_id or session.session_id != session_id:
            return None
        return session

    def delete(self, tenant_id: UUID, session_id: UUID) -> None:
        try:
            self.client.delete(self.redis_key(tenant_id, session_id))
        except Exception as exc:
            raise self._session_unavailable(exc) from exc

    def save(self, session: VoiceSession) -> datetime:
        session.last_interaction_ts = datetime.now(UTC)
        expires_at = datetime.now(UTC) + timedelta(seconds=self.settings.session_ttl_seconds)
        try:
            self.client.setex(
                self.redis_key(session.tenant_id, session.session_id),
                self.settings.session_ttl_seconds,
                session.model_dump_json(),
            )
        except Exception as exc:
            raise self._session_unavailable(exc) from exc
        return expires_at

    def health_status(self) -> str:
        try:
            self.client.ping()
        except Exception:
            return "degraded"
        return "ok"

    @staticmethod
    def redis_key(tenant_id: UUID, session_id: UUID) -> str:
        return f"session:{tenant_id}:{session_id}"

    @staticmethod
    def _session_unavailable(exc: Exception) -> ApiError:
        return ApiError(
            ErrorCode.session_not_found,
            status_code=404,
            detail=f"Redis session store unavailable: {type(exc).__name__}",
        )

    @staticmethod
    def _client_from_settings(settings: Settings) -> RedisClientProtocol:
        if not settings.upstash_redis_url:
            raise RuntimeError("UPSTASH_REDIS_URL is required when SESSION_STORE=redis.")
        import redis

        return redis.Redis.from_url(
            settings.upstash_redis_url,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )


def build_session_store(settings: Settings | None = None) -> InMemorySessionStore:
    resolved_settings = settings or get_settings()
    if resolved_settings.session_store == "redis":
        return RedisSessionStore(settings=resolved_settings)
    return InMemorySessionStore(settings=resolved_settings)
