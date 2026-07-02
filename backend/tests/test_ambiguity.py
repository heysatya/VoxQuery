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
        SchemaChunk(source_ref="order_items.discount_rate", content="Discount rate for net revenue"),
        SchemaChunk(source_ref="order_items.freight_value", content="Freight value for gross revenue"),
    ]
    result = detect_ambiguity("show net revenue by customer segment", chunks)
    assert AmbiguitySignal.metric_ambiguity not in result.signals_detected


def test_pronoun_without_history_is_detected():
    result = detect_ambiguity("filter that by Q3", [])
    assert AmbiguitySignal.pronoun_reference_failure in result.signals_detected
