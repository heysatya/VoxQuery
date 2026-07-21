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
    llm_self_confidence: float | None,
    ambiguity_signals: list[AmbiguitySignal],
    *,
    threshold: float | None = None,
    settings: Settings | None = None,
) -> ConfidenceResult:
    settings = settings or get_settings()
    effective_threshold = threshold if threshold is not None else settings.confidence_threshold_primary
    payload = ConfidenceInput(
        rag_score=rag_score,
        validation_passed=validation_passed,
        llm_self_confidence=llm_self_confidence,
        ambiguity_signals=ambiguity_signals,
        threshold=effective_threshold,
    )
    
    # Determine active weights and renormalize
    active_weights = {
        "rag": DEFAULT_WEIGHTS["rag"],
        "validation": DEFAULT_WEIGHTS["validation"],
    }
    if payload.llm_self_confidence is not None:
        active_weights["llm"] = DEFAULT_WEIGHTS["llm"]
        
    total_weight = sum(active_weights.values())
    normalized_weights = {k: v / total_weight for k, v in active_weights.items()}
    
    validation_score = 1.0 if payload.validation_passed else 0.0
    base_score = (
        normalized_weights["rag"] * payload.rag_score
        + normalized_weights["validation"] * validation_score
    )
    if "llm" in normalized_weights:
        base_score += normalized_weights["llm"] * payload.llm_self_confidence

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
            **normalized_weights,
            "ambiguity_penalty_per_signal": {
                signal.value: penalty for signal, penalty in DEFAULT_PENALTIES.items()
            },
        },
    )
