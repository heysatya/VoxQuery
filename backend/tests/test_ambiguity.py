from app.core.ambiguity import detect_ambiguity
from app.models.contracts import AmbiguitySignal, ResolvedEntity, SchemaChunk


def test_metric_ambiguity_detected_for_revenue():
    chunks = [
        SchemaChunk(source_ref="finance.gross_revenue", content="Gross revenue"),
        SchemaChunk(source_ref="finance.net_revenue", content="Net revenue"),
    ]
    result = detect_ambiguity("show revenue by region", chunks)
    assert AmbiguitySignal.metric_ambiguity in result.signals_detected


def test_resolved_entity_suppresses_metric_ambiguity():
    chunks = [
        SchemaChunk(source_ref="finance.gross_revenue", content="Gross revenue"),
        SchemaChunk(source_ref="finance.net_revenue", content="Net revenue"),
    ]
    result = detect_ambiguity(
        "show revenue by region",
        chunks,
        resolved_entities={
            "revenue": ResolvedEntity(
                resolution="net_revenue",
                resolved_at_turn=1,
                option_selected="Net revenue",
            )
        },
    )
    assert AmbiguitySignal.metric_ambiguity in result.signals_suppressed
    assert AmbiguitySignal.metric_ambiguity not in result.signals_detected


def test_explicit_net_revenue_is_not_metric_ambiguous():
    chunks = [
        SchemaChunk(source_ref="order_items.price", content="Order item sale price for revenue"),
        SchemaChunk(
            source_ref="order_items.discount_rate", content="Discount rate for net revenue"
        ),
        SchemaChunk(
            source_ref="order_items.freight_value", content="Freight value for gross revenue"
        ),
    ]
    result = detect_ambiguity("show net revenue by customer segment", chunks)
    assert AmbiguitySignal.metric_ambiguity not in result.signals_detected


def test_pronoun_without_history_is_detected():
    result = detect_ambiguity("filter that by Q3", [])
    assert AmbiguitySignal.pronoun_reference_failure in result.signals_detected


def test_entity_ambiguity_detected():
    chunks = [
        SchemaChunk(source_ref="users.region", content="Geographic region of user"),
        SchemaChunk(source_ref="sales.region", content="Sales territory region"),
    ]
    result = detect_ambiguity("show sales by region", chunks)
    assert AmbiguitySignal.entity_ambiguity in result.signals_detected


def test_entity_ambiguity_not_detected_when_unambiguous():
    chunks = [
        SchemaChunk(source_ref="users.region", content="Geographic region of user"),
    ]
    result = detect_ambiguity("show sales by region", chunks)
    assert AmbiguitySignal.entity_ambiguity not in result.signals_detected


def test_temporal_ambiguity_detected():
    chunks = [
        SchemaChunk(source_ref="orders.created_at", content="Order creation date"),
        SchemaChunk(source_ref="orders.shipped_at", content="Order shipping date"),
    ]
    result = detect_ambiguity("show orders from today", chunks)
    assert AmbiguitySignal.temporal_ambiguity in result.signals_detected


def test_scope_ambiguity_detected():
    chunks = []
    result = detect_ambiguity("who are the top customers", chunks)
    assert AmbiguitySignal.scope_ambiguity in result.signals_detected


def test_scope_ambiguity_avoided_with_number():
    chunks = []
    result = detect_ambiguity("who are the top 10 customers", chunks)
    assert AmbiguitySignal.scope_ambiguity not in result.signals_detected


def test_missing_join_path_detected():
    chunks = [
        SchemaChunk(source_ref="users.name", content="User name", table="users"),
        SchemaChunk(source_ref="orders.amount", content="Order amount", table="orders"),
    ]
    result = detect_ambiguity("show users by orders", chunks)
    assert AmbiguitySignal.missing_join_path in result.signals_detected


def test_missing_join_path_avoided_with_join_context():
    chunks = [
        SchemaChunk(
            source_ref="users.name", content="User name join_path: users->orders", table="users"
        ),
        SchemaChunk(source_ref="orders.amount", content="Order amount", table="orders"),
    ]
    result = detect_ambiguity("show users by orders", chunks)
    assert AmbiguitySignal.missing_join_path not in result.signals_detected


def test_temporal_ambiguity_not_detected_when_unambiguous():
    chunks = [
        SchemaChunk(source_ref="orders.created_at", content="Order creation date"),
    ]
    result = detect_ambiguity("show orders from today", chunks)
    assert AmbiguitySignal.temporal_ambiguity not in result.signals_detected


def test_entity_ambiguity_not_detected_for_foreign_key_pointers():
    chunks = [
        SchemaChunk(source_ref="products.product_category", content="Product category"),
        SchemaChunk(source_ref="order_items.product_id", content="Foreign key product ID"),
    ]
    result = detect_ambiguity("show revenue by product category", chunks)
    assert AmbiguitySignal.entity_ambiguity not in result.signals_detected

