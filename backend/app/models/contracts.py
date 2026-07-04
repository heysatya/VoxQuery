from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator


class InputModality(StrEnum):
    voice = "voice"
    text = "text"


class ConfidenceTier(StrEnum):
    high = "High"
    medium = "Medium"
    low = "Low"


class ChartType(StrEnum):
    bar = "bar"
    line = "line"
    table = "table"
    stat = "stat"


class QualityFlag(StrEnum):
    ok = "ok"
    low = "low"


class AmbiguitySignal(StrEnum):
    entity_ambiguity = "entity_ambiguity"
    metric_ambiguity = "metric_ambiguity"
    missing_join_path = "missing_join_path"
    pronoun_reference_failure = "pronoun_reference_failure"
    temporal_ambiguity = "temporal_ambiguity"
    scope_ambiguity = "scope_ambiguity"


AMBIGUITY_SEVERITY: tuple[AmbiguitySignal, ...] = (
    AmbiguitySignal.entity_ambiguity,
    AmbiguitySignal.metric_ambiguity,
    AmbiguitySignal.missing_join_path,
    AmbiguitySignal.pronoun_reference_failure,
    AmbiguitySignal.temporal_ambiguity,
    AmbiguitySignal.scope_ambiguity,
)


class PipelineStage(StrEnum):
    rag_retrieval = "rag_retrieval"
    sql_generation = "sql_generation"
    sql_validation = "sql_validation"
    snowflake_executing = "snowflake_executing"
    rendering = "rendering"


class ErrorCode(StrEnum):
    auth_invalid = "auth_invalid"
    auth_missing = "auth_missing"
    session_not_found = "session_not_found"
    session_expired = "session_expired"
    query_empty = "query_empty"
    query_too_long = "query_too_long"
    pipeline_in_flight = "pipeline_in_flight"
    clarification_expired = "clarification_expired"
    clarification_not_found = "clarification_not_found"
    turn_not_found = "turn_not_found"
    turn_forbidden = "turn_forbidden"
    turn_processing = "turn_processing"
    feedback_duplicate = "feedback_duplicate"
    warehouse_timeout = "warehouse_timeout"
    warehouse_error = "warehouse_error"
    sql_generation_failed = "sql_generation_failed"
    llm_unavailable = "llm_unavailable"
    internal_error = "internal_error"


ERROR_MESSAGES: dict[ErrorCode, str] = {
    ErrorCode.auth_invalid: "Your session has expired. Please sign in again.",
    ErrorCode.auth_missing: "Authentication required.",
    ErrorCode.session_not_found: "Session unavailable - please refresh.",
    ErrorCode.session_expired: "Your session has expired. Start a new conversation.",
    ErrorCode.query_empty: "Please enter a question before submitting.",
    ErrorCode.query_too_long: "Your question is too long. Please shorten it and try again.",
    ErrorCode.pipeline_in_flight: "A query is already running. Please wait for it to complete.",
    ErrorCode.clarification_expired: "That clarification has expired. Please submit your question again.",
    ErrorCode.clarification_not_found: "Clarification not found.",
    ErrorCode.turn_not_found: "Result not found.",
    ErrorCode.turn_forbidden: "You don't have access to this result.",
    ErrorCode.turn_processing: "Still processing - please wait.",
    ErrorCode.feedback_duplicate: "Feedback already recorded for this query.",
    ErrorCode.warehouse_timeout: (
        "Query timed out - the data warehouse may need a moment to wake up. "
        "Try again in 30 seconds."
    ),
    ErrorCode.warehouse_error: (
        "The data warehouse returned an error. Check that your schema access is configured correctly."
    ),
    ErrorCode.sql_generation_failed: (
        "I couldn't generate a valid query even after clarification. "
        "Try rephrasing or use the text input."
    ),
    ErrorCode.llm_unavailable: "The AI service is temporarily unavailable. Please try again in a moment.",
    ErrorCode.internal_error: "Something went wrong. Please try again.",
}


class ApiError(Exception):
    def __init__(self, code: ErrorCode, status_code: int, detail: str | None = None) -> None:
        self.code = code
        self.status_code = status_code
        self.detail = detail
        super().__init__(code.value)


class ErrorBody(BaseModel):
    code: str
    message: str
    detail: str | None = None


class ErrorEnvelope(BaseModel):
    error: ErrorBody


class AuthClaims(BaseModel):
    user_id: UUID
    tenant_id: UUID
    email: str = "local-user@voxquery.test"
    role: str = "viewer"
    snowflake_role: str = "ANALYST_READONLY"


class SessionCreateRequest(BaseModel):
    tenant_id: UUID


class SessionCreateResponse(BaseModel):
    session_id: UUID
    conversation_id: UUID
    expires_at: datetime


class QueryRequest(BaseModel):
    session_id: UUID
    submitted_text: str = Field(..., max_length=500)
    input_modality: Literal[InputModality.text] = InputModality.text
    raw_transcript: str | None = None
    stt_confidence: float | None = Field(default=None, ge=0, le=1)

    @field_validator("submitted_text")
    @classmethod
    def submitted_text_not_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("submitted_text must not be empty")
        return value.strip()


class QueryAcceptedResponse(BaseModel):
    turn_id: UUID
    status: Literal["processing"] = "processing"


class ClarificationResolutionType(StrEnum):
    option_selected = "option_selected"
    escaped = "escaped"
    timeout = "timeout"


class ClarificationRequest(BaseModel):
    session_id: UUID
    turn_id: UUID
    selection: str | None = None
    resolution_type: ClarificationResolutionType


class ClarificationResponse(BaseModel):
    status: str = "received"
    turn_id: UUID


class FeedbackRequest(BaseModel):
    session_id: UUID
    turn_id: UUID
    rating: int = -1

    @field_validator("rating")
    @classmethod
    def rating_is_thumbs_down(cls, value: int) -> int:
        if value != -1:
            raise ValueError("MVP only accepts thumbs-down rating -1")
        return value


class StatusResponse(BaseModel):
    status: str


class TelemetryRequest(BaseModel):
    session_id: UUID | None = None
    event: Literal["stt.mic.permission"]
    outcome: Literal["granted", "denied", "unavailable"] | None = None
    latency_ms: int | None = None
    error_code: str | None = None


class ResultShape(BaseModel):
    columns: list[str]
    chart_type: ChartType
    row_count: int = Field(ge=0)
    aggregate_summary: str


class ResultPayload(BaseModel):
    columns: list[str]
    rows: list[list[Any]]
    row_count: int = Field(ge=0)


class ResultResponse(BaseModel):
    turn_id: UUID
    chart_type: ChartType
    chart_rationale: str
    confidence_tier: ConfidenceTier
    generated_sql: str
    result: ResultPayload
    tts_text: str
    from_cache: bool = False


class SchemaChunk(BaseModel):
    source_ref: str
    content: str
    entity_type: str = "column"
    similarity: float = Field(default=0.8, ge=0, le=1)
    table: str | None = None
    column: str | None = None


class ResolvedEntity(BaseModel):
    resolution: str
    resolved_at_turn: int
    option_selected: str


class SessionHistoryTurn(BaseModel):
    turn_index: int
    turn_id: UUID
    user_query: str
    generated_sql: str
    result_shape: ResultShape
    confidence_tier: ConfidenceTier
    quality_flag: QualityFlag = QualityFlag.ok
    clarification_triggered: bool = False
    input_modality: InputModality


class ClarificationState(BaseModel):
    pending: bool
    issued_at: datetime
    turn_id: UUID
    original_query: str
    question: str
    options: list[str]
    raw_transcript: str | None = None
    stt_confidence: float | None = None
    input_modality: InputModality = InputModality.text


class VoiceSession(BaseModel):
    session_id: UUID
    user_id: UUID
    tenant_id: UUID
    conversation_id: UUID
    turn_count: int = 0
    last_interaction_ts: datetime = Field(default_factory=lambda: datetime.now(UTC))
    snowflake_role: str
    clarification_state: ClarificationState | None = None
    history: list[SessionHistoryTurn] = Field(default_factory=list)
    resolved_entities: dict[str, ResolvedEntity] = Field(default_factory=dict)


class SessionContextBlock(BaseModel):
    history: list[SessionHistoryTurn]
    resolved_entities: dict[str, ResolvedEntity]
    truncated: bool
    turns_dropped: int
    truncation_note: str | None = None
    token_count: int


class AmbiguityDetectionResult(BaseModel):
    signals_detected: list[AmbiguitySignal]
    signals_suppressed: list[AmbiguitySignal]
    dominant_signal: AmbiguitySignal | None
    ambiguous_terms: list[str] = Field(default_factory=list)


class ConfidenceInput(BaseModel):
    rag_score: float = Field(ge=0, le=1)
    validation_passed: bool
    llm_self_confidence: float = Field(ge=0, le=1)
    ambiguity_signals: list[AmbiguitySignal]
    threshold: float


class ConfidenceResult(BaseModel):
    composite_score: float = Field(ge=0, le=1)
    confidence_tier: ConfidenceTier
    clarification_triggered: bool
    ambiguity_penalty_total: float
    formula_weights: dict[str, Any]


class PipelineProgressEvent(BaseModel):
    type: str = "pipeline_progress"
    stage: PipelineStage
    turn_id: UUID
    elapsed_ms: int


class ClarificationRequestEvent(BaseModel):
    type: str = "clarification_request"
    turn_id: UUID
    question: str
    options: list[str]
    timeout_seconds: int


class ClarificationTimeoutWarningEvent(BaseModel):
    type: str = "clarification_timeout_warning"
    turn_id: UUID
    seconds_remaining: int


class ResultReadyEvent(BaseModel):
    type: str = "result_ready"
    turn_id: UUID
    confidence_tier: ConfidenceTier
    chart_type: ChartType
    chart_rationale: str
    result_json: dict[str, Any]
    proactive_questions: list[str]
    from_cache: bool = False


class PipelineErrorEvent(BaseModel):
    type: str = "pipeline_error"
    turn_id: UUID
    code: str
    message: str


class InterimTranscriptEvent(BaseModel):
    type: str = "interim_transcript"
    text: str
    is_final: bool = False


class FinalTranscriptEvent(BaseModel):
    type: str = "final_transcript"
    text: str
    confidence: float
    is_final: bool = True


class AudioErrorEvent(BaseModel):
    type: str = "error"
    code: str
    message: str


class TurnRecord(BaseModel):
    turn_id: UUID = Field(default_factory=uuid4)
    session_id: UUID
    conversation_id: UUID
    user_id: UUID
    tenant_id: UUID
    user_input: str
    raw_transcript: str | None = None
    deepgram_confidence_raw: float | None = None
    generated_sql: str = ""
    result_json: ResultShape | None = None
    chart_type: ChartType | None = None
    chart_rationale: str = ""
    confidence_tier: ConfidenceTier | None = None
    composite_score: float | None = None
    clarification_triggered: bool = False
    quality_flag: QualityFlag = QualityFlag.ok
    source: str = "user"
    input_modality: InputModality
    latency_ms: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed: bool = False
    feedback_submitted: bool = False
    full_result: ResultPayload | None = None
    tts_text: str = ""
    from_cache: bool = False
