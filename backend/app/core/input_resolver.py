from pydantic import BaseModel
from app.models.contracts import (
    AmbiguityDetectionResult,
    AmbiguitySignal,
    ResolvedEntity,
    SchemaChunk,
    SessionHistoryTurn,
)
from app.core.ambiguity import detect_ambiguity


class InputResolution(BaseModel):
    resolved_text: str
    pre_sql_ambiguity: AmbiguityDetectionResult | None
    should_block: bool


def resolve_input(
    text: str,
    schema_chunks: list[SchemaChunk],
    session_history: list[SessionHistoryTurn],
    resolved_entities: dict[str, ResolvedEntity] | None = None,
) -> InputResolution:
    resolved_entities = resolved_entities or {}

    ambiguity_result = detect_ambiguity(
        submitted_text=text,
        schema_chunks=schema_chunks,
        resolved_entities=resolved_entities,
        history=session_history,
    )

    if not ambiguity_result.signals_detected:
        return InputResolution(
            resolved_text=text,
            pre_sql_ambiguity=None,
            should_block=False,
        )

    blocking_signals = {
        AmbiguitySignal.scope_ambiguity,
        AmbiguitySignal.pronoun_reference_failure,
    }

    has_blocking_signal = any(sig in blocking_signals for sig in ambiguity_result.signals_detected)

    should_block = has_blocking_signal

    return InputResolution(
        resolved_text=text,
        pre_sql_ambiguity=ambiguity_result,
        should_block=should_block,
    )
