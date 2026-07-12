from app.core.input_resolver import resolve_input
from app.models.contracts import (
    AmbiguitySignal,
    SchemaChunk,
    SessionHistoryTurn,
)


def test_resolve_input_clean_pass_through():
    resolution = resolve_input(
        text="what is the net revenue",
        schema_chunks=[
            SchemaChunk(
                content="net_revenue definition", source_ref="file", similarity=0.9
            )
        ],
        session_history=[],
        resolved_entities={},
    )
    assert resolution.should_block is False
    assert resolution.pre_sql_ambiguity is None


def test_resolve_input_metric_non_blocking():
    # 'revenue' matches two metrics, so metric_ambiguity is detected, but shouldn't block.
    resolution = resolve_input(
        text="what is the revenue",
        schema_chunks=[
            SchemaChunk(
                content="net_revenue definition", source_ref="file", similarity=0.9
            ),
            SchemaChunk(
                content="gross_revenue definition", source_ref="file", similarity=0.9
            ),
        ],
        session_history=[],
        resolved_entities={},
    )
    assert resolution.should_block is False
    assert resolution.pre_sql_ambiguity is not None
    assert AmbiguitySignal.metric_ambiguity in resolution.pre_sql_ambiguity.signals_detected


def test_resolve_input_scope_blocking():
    # 'top item' without N
    resolution = resolve_input(
        text="what is the best product",
        schema_chunks=[
            SchemaChunk(content="product definition", source_ref="file", similarity=0.9)
        ],
        session_history=[],
        resolved_entities={},
    )
    assert resolution.should_block is True
    assert resolution.pre_sql_ambiguity is not None
    assert AmbiguitySignal.scope_ambiguity in resolution.pre_sql_ambiguity.signals_detected


def test_resolve_input_pronoun_blocking():
    # 'show me that' with no history
    resolution = resolve_input(
        text="show me that",
        schema_chunks=[
            SchemaChunk(content="product definition", source_ref="file", similarity=0.9)
        ],
        session_history=[],
        resolved_entities={},
    )
    assert resolution.should_block is True
    assert resolution.pre_sql_ambiguity is not None
    assert AmbiguitySignal.pronoun_reference_failure in resolution.pre_sql_ambiguity.signals_detected
