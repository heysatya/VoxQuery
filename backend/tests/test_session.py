from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from app.config import Settings
from app.core.session import InMemorySessionStore, RedisSessionStore
from app.models.contracts import (
    ApiError,
    AuthClaims,
    ChartType,
    ClarificationState,
    ConfidenceTier,
    InputModality,
    ResultShape,
)


class FakeRedis:
    def __init__(self, *, fail: bool = False, error_message: str = "redis unavailable") -> None:
        self.fail = fail
        self.error_message = error_message
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    def get(self, name: str) -> str | None:
        if self.fail:
            raise RuntimeError(self.error_message)
        return self.values.get(name)

    def setex(self, name: str, time: int, value: str) -> None:
        if self.fail:
            raise RuntimeError(self.error_message)
        self.values[name] = value
        self.ttls[name] = time

    def ping(self) -> bool:
        if self.fail:
            raise RuntimeError(self.error_message)
        return True


def claims() -> AuthClaims:
    return AuthClaims(
        user_id=UUID("00000000-0000-0000-0000-000000000001"),
        tenant_id=UUID("00000000-0000-0000-0000-000000000101"),
    )


def result_shape() -> ResultShape:
    return ResultShape(
        columns=["customer_segment", "total_net_revenue"],
        chart_type=ChartType.bar,
        row_count=3,
        aggregate_summary="summary",
    )


def test_session_create_and_context_preserves_resolved_entities():
    store = InMemorySessionStore(Settings(APP_ENV="test", AUTH_MODE="fake", TOKEN_BUDGET=40))
    session, _ = store.create(claims())
    store.add_resolved_entity(session, "revenue", "net_revenue", "Net revenue")
    for index in range(5):
        store.append_turn(
            session,
            turn_id=uuid4(),
            user_query=f"show revenue by region {index}",
            generated_sql="SELECT 1",
            result_shape=result_shape(),
            confidence_tier=ConfidenceTier.high,
            clarification_triggered=False,
            input_modality=InputModality.text,
        )
    context = store.context_block(session)
    assert context.resolved_entities["revenue"].resolution == "net_revenue"
    assert context.truncated is True


def test_redis_session_roundtrip_key_format_and_ttl_refresh():
    redis = FakeRedis()
    store = RedisSessionStore(
        Settings(APP_ENV="test", AUTH_MODE="fake", SESSION_TTL_SECONDS=120),
        client=redis,
    )

    session, _ = store.create(claims())
    key = f"session:{session.tenant_id}:{session.session_id}"
    assert key in redis.values
    assert redis.ttls[key] == 120

    first_saved = session.last_interaction_ts
    store.append_turn(
        session,
        turn_id=uuid4(),
        user_query="Show net revenue by customer segment",
        generated_sql="SELECT 1",
        result_shape=result_shape(),
        confidence_tier=ConfidenceTier.high,
        clarification_triggered=False,
        input_modality=InputModality.text,
    )
    loaded = store.get(session.tenant_id, session.session_id)
    assert loaded is not None
    assert loaded.history[0].user_query == "Show net revenue by customer segment"
    assert loaded.last_interaction_ts >= first_saved
    assert redis.ttls[key] == 120


def test_redis_pending_clarification_survives_roundtrip():
    redis = FakeRedis()
    store = RedisSessionStore(Settings(APP_ENV="test", AUTH_MODE="fake"), client=redis)
    session, _ = store.create(claims())
    turn_id = uuid4()

    store.set_pending_clarification(
        session,
        ClarificationState(
            pending=True,
            issued_at=datetime.now(UTC) - timedelta(seconds=31),
            turn_id=turn_id,
            original_query="Show revenue by region",
            question="Which revenue metric did you mean?",
            options=["Gross revenue", "Net revenue"],
        ),
    )

    loaded = store.get(session.tenant_id, session.session_id)
    assert loaded is not None
    assert loaded.clarification_state is not None
    assert loaded.clarification_state.turn_id == turn_id
    assert loaded.clarification_state.original_query == "Show revenue by region"


def test_redis_resolved_entities_cap_and_quality_flag_persist():
    redis = FakeRedis()
    store = RedisSessionStore(Settings(APP_ENV="test", AUTH_MODE="fake"), client=redis)
    session, _ = store.create(claims())
    turn_id = uuid4()
    store.append_turn(
        session,
        turn_id=turn_id,
        user_query="Show net revenue by customer segment",
        generated_sql="SELECT 1",
        result_shape=result_shape(),
        confidence_tier=ConfidenceTier.high,
        clarification_triggered=False,
        input_modality=InputModality.text,
    )

    for index in range(21):
        session.turn_count = index
        store.add_resolved_entity(session, f"term_{index}", f"resolution_{index}", f"Option {index}")
    assert len(session.resolved_entities) == 20
    assert "term_0" not in session.resolved_entities

    assert store.mark_low_quality(session, turn_id) is True
    loaded = store.get(session.tenant_id, session.session_id)
    assert loaded is not None
    assert len(loaded.resolved_entities) == 20
    assert loaded.history[0].quality_flag == "low"


def test_redis_failure_maps_to_safe_session_error_without_leaking_connection_detail():
    store = RedisSessionStore(
        Settings(APP_ENV="test", AUTH_MODE="fake"),
        client=FakeRedis(fail=True, error_message="redis://secret-host.example:6379 failed"),
    )

    with pytest.raises(ApiError) as exc:
        store.get(claims().tenant_id, uuid4())

    assert exc.value.code == "session_not_found"
    assert exc.value.detail == "Redis session store unavailable: RuntimeError"
    assert store.health_status() == "degraded"


def test_redis_mode_requires_url_at_startup_and_reports_ok_when_reachable():
    settings = Settings(
        APP_ENV="test",
        AUTH_MODE="fake",
        SESSION_STORE="redis",
        UPSTASH_REDIS_URL=None,
    )
    with pytest.raises(RuntimeError, match="UPSTASH_REDIS_URL"):
        settings.validate_startup()

    store = RedisSessionStore(settings, client=FakeRedis())
    assert store.health_status() == "ok"


def test_redis_mode_requires_tls_in_staging_and_production():
    staging = Settings(
        APP_ENV="staging",
        AUTH_MODE="clerk",
        SESSION_STORE="redis",
        UPSTASH_REDIS_URL="redis://example.com:6379",
        CLERK_ISSUER="https://clerk.voxquery.test",
        CLERK_JWKS_URL="https://clerk.voxquery.test/.well-known/jwks.json",
    )
    with pytest.raises(RuntimeError, match="rediss://"):
        staging.validate_startup()

    production = Settings(
        APP_ENV="production",
        AUTH_MODE="clerk",
        SESSION_STORE="redis",
        UPSTASH_REDIS_URL="rediss://example.com:6379",
        CLERK_ISSUER="https://clerk.voxquery.test",
        CLERK_JWKS_URL="https://clerk.voxquery.test/.well-known/jwks.json",
    )
    production.validate_startup()


def test_redis_create_failure_maps_to_safe_session_error():
    store = RedisSessionStore(Settings(APP_ENV="test", AUTH_MODE="fake"), client=FakeRedis(fail=True))

    with pytest.raises(ApiError) as exc:
        store.create(claims())

    assert exc.value.code == "session_not_found"
    assert exc.value.detail == "Redis session store unavailable: RuntimeError"


def test_redis_tenant_mismatch_returns_none():
    redis = FakeRedis()
    store = RedisSessionStore(Settings(APP_ENV="test", AUTH_MODE="fake"), client=redis)
    session, _ = store.create(claims())
    wrong_tenant_id = UUID("00000000-0000-0000-0000-000000000999")

    loaded = store.get(wrong_tenant_id, session.session_id)

    assert loaded is None


def test_redis_invalid_json_maps_to_safe_session_error():
    redis = FakeRedis()
    store = RedisSessionStore(Settings(APP_ENV="test", AUTH_MODE="fake"), client=redis)
    session, _ = store.create(claims())
    redis.values[f"session:{session.tenant_id}:{session.session_id}"] = "{not-json"

    with pytest.raises(ApiError) as exc:
        store.get(session.tenant_id, session.session_id)

    assert exc.value.code == "session_not_found"
    assert exc.value.detail == "Redis session store unavailable: ValidationError"
