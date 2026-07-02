from uuid import UUID, uuid4

from app.config import Settings
from app.core.session import InMemorySessionStore
from app.models.contracts import AuthClaims, ChartType, ConfidenceTier, InputModality, ResultShape


def test_session_create_and_context_preserves_resolved_entities():
    store = InMemorySessionStore(Settings(APP_ENV="test", AUTH_MODE="fake", TOKEN_BUDGET=40))
    claims = AuthClaims(
        user_id=UUID("00000000-0000-0000-0000-000000000001"),
        tenant_id=UUID("00000000-0000-0000-0000-000000000101"),
    )
    session, _ = store.create(claims)
    store.add_resolved_entity(session, "revenue", "net_revenue", "Net revenue")
    for index in range(5):
        store.append_turn(
            session,
            turn_id=uuid4(),
            user_query=f"show revenue by region {index}",
            generated_sql="SELECT 1",
            result_shape=ResultShape(
                columns=["region", "revenue"],
                chart_type=ChartType.bar,
                row_count=3,
                aggregate_summary="summary",
            ),
            confidence_tier=ConfidenceTier.high,
            clarification_triggered=False,
            input_modality=InputModality.text,
        )
    context = store.context_block(session)
    assert context.resolved_entities["revenue"].resolution == "net_revenue"
    assert context.truncated is True
