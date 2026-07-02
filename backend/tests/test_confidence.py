from app.core.confidence import compute_confidence
from app.models.contracts import AmbiguitySignal, ConfidenceTier


def test_high_confidence_without_ambiguity():
    result = compute_confidence(0.9, True, 0.9, [])
    assert result.confidence_tier == ConfidenceTier.high
    assert result.clarification_triggered is False


def test_low_confidence_triggers_clarification():
    result = compute_confidence(0.7, True, 0.58, [AmbiguitySignal.metric_ambiguity])
    assert result.confidence_tier == ConfidenceTier.low
    assert result.clarification_triggered is True
    assert result.formula_weights["rag"] == 0.4


def test_validation_failure_hurts_score():
    passing = compute_confidence(0.8, True, 0.8, [])
    failing = compute_confidence(0.8, False, 0.8, [])
    assert failing.composite_score < passing.composite_score
