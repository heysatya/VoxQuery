from app.config import Settings, get_settings
from app.models.contracts import AmbiguitySignal, ConfidenceInput, ConfidenceResult, ConfidenceTier


DEFAULT_WEIGHTS = {
    "rag": 0.40,
    "validation": 0.20,
    "llm": 0.40,
}

DEFAULT_PENALTIES: dict[AmbiguitySignal, float] = {
    AmbiguitySignal.entity_ambiguity: 0.18,
    AmbiguitySignal.metric_ambiguity: 0.16,
    AmbiguitySignal.missing_join_path: 0.20,
    AmbiguitySignal.pronoun_reference_failure: 0.20,
    AmbiguitySignal.temporal_ambiguity: 0.10,
    AmbiguitySignal.scope_ambiguity: 0.08,
}


def compute_confidence(
    rag_score: float,
    validation_passed: bool,
    llm_self_confidence: float,
    ambiguity_signals: list[AmbiguitySignal],
    *,
    threshold: float | None = None,
    settings: Settings | None = None,
) -> ConfidenceResult:
    settings = settings or get_settings()
    effective_threshold = threshold or settings.confidence_threshold_primary
    payload = ConfidenceInput(
        rag_score=rag_score,
        validation_passed=validation_passed,
        llm_self_confidence=llm_self_confidence,
        ambiguity_signals=ambiguity_signals,
        threshold=effective_threshold,
    )
    validation_score = 1.0 if payload.validation_passed else 0.0
    base_score = (
        DEFAULT_WEIGHTS["rag"] * payload.rag_score
        + DEFAULT_WEIGHTS["validation"] * validation_score
        + DEFAULT_WEIGHTS["llm"] * payload.llm_self_confidence
    )
    penalty_total = min(
        0.65, sum(DEFAULT_PENALTIES.get(signal, 0.0) for signal in set(payload.ambiguity_signals))
    )
    composite = max(0.0, min(1.0, round(base_score - penalty_total, 4)))

    if composite >= 0.80:
        tier = ConfidenceTier.high
    elif composite >= settings.confidence_threshold_primary:
        tier = ConfidenceTier.medium
    else:
        tier = ConfidenceTier.low

    return ConfidenceResult(
        composite_score=composite,
        confidence_tier=tier,
        clarification_triggered=composite < effective_threshold,
        ambiguity_penalty_total=round(penalty_total, 4),
        formula_weights={
            **DEFAULT_WEIGHTS,
            "ambiguity_penalty_per_signal": {
                signal.value: penalty for signal, penalty in DEFAULT_PENALTIES.items()
            },
        },
    )
