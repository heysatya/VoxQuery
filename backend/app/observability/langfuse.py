from uuid import UUID
from typing import Any

import contextlib
from langfuse import Langfuse, propagate_attributes
from app.services.telemetry import emit
from app.models.contracts import TurnRecord
from app.config import get_settings

# We do not want Langfuse internals to raise to the pipeline.
# We wrap it in a class that catches exceptions and logs them to our telemetry tier 2.

class LangfuseTracer:
    def __init__(self):
        try:
            from app.config import get_settings
            if get_settings().app_env == "test":
                self.langfuse = None
            else:
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

    @contextlib.contextmanager
    def start_trace(self, turn: TurnRecord) -> Any:
        # Create root trace. trace.id = str(turn.turn_id)
        if self.langfuse is None:
            yield None
            return
        
        is_yielded = False
        try:
            with propagate_attributes(
                user_id=str(turn.user_id) if turn.user_id else None,
                session_id=str(turn.session_id) if turn.session_id else None,
                metadata={
                    "conversation_id": str(turn.conversation_id) if turn.conversation_id else None,
                    "tenant_id": str(turn.tenant_id) if turn.tenant_id else None,
                    "input_modality": turn.input_modality,
                    "model_name": get_settings().canonical_sql_model,
                }
            ):
                with self.langfuse.start_as_current_observation(
                    name="voice_turn",
                    as_type="span",
                    trace_context={"trace_id": turn.turn_id.hex}
                ) as trace:
                    is_yielded = True
                    yield trace
        except Exception as e:
            if is_yielded:
                raise
            emit("langfuse.error", tier=2, error=str(e), func="start_trace")
            yield None

    def span_stt_capture(self, trace, raw_transcript: str | None, submitted_text: str, confidence: float | None):
        if not trace:
            return
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
        if not trace:
            return
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
        if not trace:
            return
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
        if not trace:
            return
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
        if not trace:
            return
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
        
    def span_rag_retrieval(self, trace, rag_score: float, chunk_count: int):
        if not trace:
            return
        def _span():
            child = trace.start_observation(
                name="rag_retrieval",
                as_type="span",
                output={
                    "rag_score": rag_score,
                    "chunk_count": chunk_count
                }
            )
            child.end()
        self._safe_call(_span)

    def span_clarification_issued(self, trace, question: str, options: list[str]):
        if not trace:
            return
        def _span():
            child = trace.start_observation(
                name="clarification_issued",
                as_type="span",
                output={
                    "question": question,
                    "options": options
                }
            )
            child.end()
        self._safe_call(_span)

    def span_snowflake_executing(
        self,
        trace,
        *,
        snowflake_role: str | None,
        success: bool,
        row_count: int | None = None,
        error_type: str | None = None,
        error_detail: str | None = None,
    ):
        if not trace:
            return
        def _span():
            child = trace.start_observation(
                name="snowflake_executing",
                as_type="span",
                output={
                    "snowflake_role": snowflake_role,
                    "success": success,
                    "row_count": row_count,
                    # error_detail is redacted upstream (no DSN/credentials) before it reaches
                    # this call, but is safe to keep in Langfuse even though it's stripped
                    # from the client-facing API response in production.
                    "error_type": error_type,
                    "error_detail": error_detail,
                },
            )
            if not success:
                child.update(level="ERROR", status_message=error_type or "warehouse_error")
            child.end()
        self._safe_call(_span)

    def span_turn_completed(self, trace, latency_ms: int, success: bool = True, error_code: str | None = None):
        if not trace:
            return
        def _span():
            trace_metadata = {
                "latency_ms": latency_ms,
                "success": success
            }
            if error_code:
                trace_metadata["error_code"] = error_code

            trace.update(metadata=trace_metadata)
            child = trace.start_observation(
                name="turn_completed",
                as_type="span",
                output={
                    "latency_ms": latency_ms,
                    "success": success,
                    "error_code": error_code
                }
            )
            child.end()
        self._safe_call(_span)
        
    def score_feedback(self, turn_id: UUID, rating: int, composite_score: float, confidence_tier: str, clarification_triggered: bool, option_selected: str | None):
        if self.langfuse is None:
            return
        def _score():
            comment = "thumbs-up" if rating == 1 else "thumbs-down"
            self.langfuse.create_score(
                trace_id=turn_id.hex,
                name="user-thumbs",
                value=rating,
                data_type="NUMERIC",
                comment=comment,
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
