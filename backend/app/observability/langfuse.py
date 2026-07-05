import json
import logging
from uuid import UUID
from typing import Any

from langfuse import Langfuse, propagate_attributes
from app.services.telemetry import emit
from app.models.contracts import TurnRecord

# We do not want Langfuse internals to raise to the pipeline.
# We wrap it in a class that catches exceptions and logs them to our telemetry tier 2.

class LangfuseTracer:
    def __init__(self):
        try:
            self.langfuse = Langfuse()
        except Exception as e:
            emit("langfuse.init.error", tier=2, error=str(e))
            self.langfuse = None

    def _safe_call(self, func, *args, **kwargs):
        if self.langfuse is None:
            return None
        try:
            return func(*args, **kwargs)
        except Exception as e:
            emit("langfuse.error", tier=2, error=str(e), func=func.__name__)
            return None

    def start_trace(self, turn: TurnRecord) -> Any:
        # Create root trace. trace.id = str(turn.turn_id)
        if self.langfuse is None:
            return None
        
        def _create_trace():
            with propagate_attributes(
                user_id=str(turn.user_id) if turn.user_id else None,
                session_id=str(turn.session_id) if turn.session_id else None,
                metadata={
                    "conversation_id": str(turn.conversation_id) if turn.conversation_id else None,
                    "tenant_id": str(turn.tenant_id) if turn.tenant_id else None,
                    "input_modality": turn.input_modality,
                }
            ):
                return self.langfuse.start_observation(
                    name="voice_turn",
                    as_type="span",
                    trace_context={"trace_id": turn.turn_id.hex}
                )
        return self._safe_call(_create_trace)

    def span_stt_capture(self, trace, raw_transcript: str | None, submitted_text: str, confidence: float | None):
        if not trace: return
        import difflib
        edit_distance_ratio = None
        if raw_transcript and submitted_text:
            edit_distance_ratio = difflib.SequenceMatcher(None, raw_transcript.lower(), submitted_text.lower()).ratio()
            
        def _span():
            child = trace.start_observation(
                name="stt_capture",
                as_type="span",
                output={
                    "raw_transcript": raw_transcript,
                    "submitted_text": submitted_text,
                    "deepgram_confidence_raw": confidence,
                    "edit_distance_ratio": edit_distance_ratio
                }
            )
            child.end()
        self._safe_call(_span)

    def span_memory_retrieval(self, trace, truncated: bool, turns_dropped: int, token_count: int):
        if not trace: return
        def _span():
            child = trace.start_observation(
                name="memory_retrieval",
                as_type="span",
                output={
                    "truncated": truncated,
                    "turns_dropped": turns_dropped,
                    "token_count": token_count
                }
            )
            child.end()
        self._safe_call(_span)

    def span_history_injection(self, trace, total_prompt_tokens: int):
        if not trace: return
        def _span():
            child = trace.start_observation(
                name="history_injection",
                as_type="span",
                output={
                    "total_prompt_tokens": total_prompt_tokens
                }
            )
            child.end()
        self._safe_call(_span)

    def span_ambiguity_detection(self, trace, signals_detected: list, signals_suppressed: list, dominant_signal: str | None):
        if not trace: return
        def _span():
            child = trace.start_observation(
                name="ambiguity_detection",
                as_type="span",
                output={
                    "signals_detected": [s.__dict__ if hasattr(s, "__dict__") else str(s) for s in signals_detected],
                    "signals_suppressed": [s.__dict__ if hasattr(s, "__dict__") else str(s) for s in signals_suppressed],
                    "dominant_signal": dominant_signal
                }
            )
            child.end()
        self._safe_call(_span)

    def span_confidence_computation(self, trace, composite_score: float, confidence_tier: str, clarification_triggered: bool, formula_weights: dict):
        if not trace: return
        def _span():
            child = trace.start_observation(
                name="confidence_computation",
                as_type="span",
                output={
                    "composite_score": composite_score,
                    "confidence_tier": confidence_tier,
                    "clarification_triggered": clarification_triggered,
                    "formula_weights": formula_weights
                }
            )
            child.end()
        self._safe_call(_span)
        
    def score_feedback(self, turn_id: UUID, composite_score: float, confidence_tier: str, clarification_triggered: bool, option_selected: str | None):
        if self.langfuse is None:
            return
        def _score():
            self.langfuse.create_score(
                trace_id=turn_id.hex,
                name="user_feedback",
                value=-1,
                comment="thumbs-down",
                metadata={
                    "turn_id": str(turn_id),
                    "confidence_score": composite_score,
                    "confidence_tier": confidence_tier,
                    "clarification_triggered": clarification_triggered,
                    "option_selected": option_selected,
                }
            )
        self._safe_call(_score)
        
    def flush(self):
        if self.langfuse:
            self._safe_call(self.langfuse.flush)

tracer = LangfuseTracer()
