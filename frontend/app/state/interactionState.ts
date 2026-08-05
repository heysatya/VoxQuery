import type { AudioEvent, PipelineEvent, RecordingState } from "../../lib/types";

export type VoiceCaptureState =
  | "idle"
  | "permission_explaining"
  | "permission_requesting"
  | "connecting"
  | "listening"
  | "stopping"
  | "finalizing"
  | "reviewing"
  | "capture_error";

export type VoiceCaptureEvent =
  | "explain_permission"
  | "request_permission"
  | "permission_granted"
  | "connected"
  | "stop_requested"
  | "finalizing_started"
  | "transcript_ready"
  | "capture_failed"
  | "reset";

export type TurnLifecycleState =
  | "idle"
  | "submitting"
  | "accepted"
  | "retrieving_context"
  | "generating_sql"
  | "validating_sql"
  | "clarification_required"
  | "clarification_submitting"
  | "executing"
  | "preparing_answer"
  | "completed"
  | "recoverable_error"
  | "fatal_error";

export type TtsLifecycleState = "idle" | "loading" | "playing" | "paused" | "ended" | "failed";

export type NoticeSeverity = "info" | "warning" | "error";

export type UserNotice = {
  severity: NoticeSeverity;
  message: string;
};

export function notice(message: string, severity: NoticeSeverity = "info"): UserNotice {
  return { message, severity };
}

export function transitionVoiceState(
  current: VoiceCaptureState,
  event: VoiceCaptureEvent
): VoiceCaptureState {
  if (event === "reset") return "idle";
  if (event === "capture_failed") return "capture_error";

  const allowed: Record<VoiceCaptureState, Partial<Record<VoiceCaptureEvent, VoiceCaptureState>>> = {
    idle: {
      explain_permission: "permission_explaining",
      request_permission: "permission_requesting",
      permission_granted: "connecting"
    },
    permission_explaining: {
      request_permission: "permission_requesting",
      permission_granted: "connecting"
    },
    permission_requesting: {
      permission_granted: "connecting"
    },
    connecting: {
      connected: "listening"
    },
    listening: {
      stop_requested: "stopping",
      finalizing_started: "finalizing",
      transcript_ready: "reviewing"
    },
    stopping: {
      finalizing_started: "finalizing",
      transcript_ready: "reviewing"
    },
    finalizing: {
      transcript_ready: "reviewing"
    },
    reviewing: {
      request_permission: "permission_requesting",
      explain_permission: "permission_explaining",
      permission_granted: "connecting"
    },
    capture_error: {
      request_permission: "permission_requesting",
      explain_permission: "permission_explaining",
      permission_granted: "connecting"
    }
  };

  return allowed[current][event] ?? current;
}

export function mapVoiceToRecordingState(voiceState: VoiceCaptureState): RecordingState {
  if (voiceState === "connecting" || voiceState === "permission_requesting") {
    return "connecting";
  }
  if (voiceState === "listening") {
    return "recording";
  }
  if (voiceState === "stopping" || voiceState === "finalizing") {
    return "processing";
  }
  return "idle";
}

export function turnPhaseFromPipelineStage(stage: string): TurnLifecycleState {
  const map: Record<string, TurnLifecycleState> = {
    rag_retrieval: "retrieving_context",
    sql_generation: "generating_sql",
    sql_validation: "validating_sql",
    sql_execution: "executing",
    snowflake_executing: "executing",
    executing: "executing",
    chart_selection: "preparing_answer",
    rendering: "preparing_answer",
    tts_generation: "preparing_answer",
    clarification_pending: "clarification_required"
  };
  return map[stage] ?? "generating_sql";
}

export function isActiveTurnPhase(phase: TurnLifecycleState) {
  return [
    "submitting",
    "accepted",
    "retrieving_context",
    "generating_sql",
    "validating_sql",
    "clarification_submitting",
    "executing",
    "preparing_answer"
  ].includes(phase);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

function isNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function parseJsonRecord(data: string): Record<string, unknown> | null {
  try {
    const parsed = JSON.parse(data) as unknown;
    return isRecord(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

function hasTurnId(value: Record<string, unknown>): value is Record<string, unknown> & { turn_id: string } {
  return typeof value.turn_id === "string" && value.turn_id.length > 0;
}

export function parsePipelineEvent(data: string): PipelineEvent | null {
  const value = parseJsonRecord(data);
  if (!value || typeof value.type !== "string") return null;

  if (value.type === "pipeline_progress") {
    if (!hasTurnId(value) || typeof value.stage !== "string" || !isNumber(value.elapsed_ms)) return null;
    return {
      type: "pipeline_progress",
      stage: value.stage,
      turn_id: value.turn_id,
      elapsed_ms: value.elapsed_ms
    };
  }

  if (value.type === "clarification_request") {
    if (
      !hasTurnId(value) ||
      typeof value.question !== "string" ||
      !isStringArray(value.options)
    ) {
      return null;
    }
    return {
      type: "clarification_request",
      turn_id: value.turn_id,
      question: value.question,
      options: value.options
    };
  }

  if (value.type === "result_ready") {
    if (!hasTurnId(value)) return null;
    return {
      type: "result_ready",
      turn_id: value.turn_id,
      confidence_tier: value.confidence_tier,
      chart_type: value.chart_type,
      chart_rationale: value.chart_rationale,
      result_json: isRecord(value.result_json) ? value.result_json : undefined,
      proactive_questions: isStringArray(value.proactive_questions) ? value.proactive_questions : undefined,
      from_cache: typeof value.from_cache === "boolean" ? value.from_cache : undefined
    };
  }

  if (value.type === "pipeline_error") {
    if (!hasTurnId(value) || typeof value.code !== "string" || typeof value.message !== "string") return null;
    return {
      type: "pipeline_error",
      turn_id: value.turn_id,
      code: value.code,
      message: value.message
    };
  }

  return null;
}

export function parseAudioEvent(data: string): AudioEvent | null {
  const value = parseJsonRecord(data);
  if (!value || typeof value.type !== "string") return null;

  if (value.type === "interim_transcript") {
    if (typeof value.text !== "string" || value.is_final !== false) return null;
    return { type: "interim_transcript", text: value.text, is_final: false };
  }

  if (value.type === "final_transcript") {
    if (typeof value.text !== "string" || !isNumber(value.confidence) || value.is_final !== true) return null;
    return {
      type: "final_transcript",
      text: value.text,
      confidence: value.confidence,
      is_final: true
    };
  }

  if (value.type === "error") {
    if (typeof value.code !== "string" || typeof value.message !== "string") return null;
    return { type: "error", code: value.code, message: value.message };
  }

  return null;
}

/**
 * Derives a single human-readable status label from the three explicit
 * lifecycle state dimensions. Callers should use this instead of ad-hoc
 * string concatenation in render paths.
 */
export function getStatusLabel(
  voiceState: VoiceCaptureState,
  turnState: TurnLifecycleState,
  ttsState: TtsLifecycleState
): string {
  // Voice capture branch
  if (voiceState === "permission_explaining" || voiceState === "permission_requesting") {
    return "Requesting microphone access...";
  }
  if (voiceState === "connecting") return "Connecting to voice stream...";
  if (voiceState === "listening") return "Recording...";
  if (voiceState === "stopping" || voiceState === "finalizing") return "Processing audio...";
  if (voiceState === "reviewing") return "Review your transcript before submitting";
  if (voiceState === "capture_error") return "Voice capture failed — use text input";

  // Turn lifecycle branch
  if (turnState === "submitting") return "Submitting query...";
  if (turnState === "accepted") return "Query accepted — waiting for pipeline...";
  if (turnState === "retrieving_context") return "Understanding your question...";
  if (turnState === "generating_sql") return "Crafting the query...";
  if (turnState === "validating_sql") return "Verifying accuracy...";
  if (turnState === "executing") return "Running against your data...";
  if (turnState === "preparing_answer") return "Building your answer...";
  if (turnState === "clarification_required") return "Clarification needed before executing";
  if (turnState === "clarification_submitting") return "Submitting clarification...";
  if (turnState === "recoverable_error") return "Something went wrong — try rephrasing";
  if (turnState === "fatal_error") return "Query failed — check the backend connection";
  if (turnState === "completed") {
    if (ttsState === "failed") return "Voice playback failed — text answer is shown";
    if (ttsState === "playing") return "Playing answer...";
    return "Result ready";
  }

  return "Ready";
}


