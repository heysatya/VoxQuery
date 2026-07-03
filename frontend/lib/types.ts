export type InputModality = "voice" | "text";

export type MicPermission = "unknown" | "prompt" | "granted" | "denied";

export type SessionState = {
  sessionId: string | null;
  conversationId: string | null;
};

export type RecordingState = "idle" | "connecting" | "recording" | "processing";

export type ClarificationState = {
  pending: boolean;
  question: string | null;
  options: string[];
  secondsRemaining: number;
};

export type SessionCreateResponse = {
  session_id: string;
  conversation_id: string;
  expires_at: string;
};

export type QueryRequest = {
  session_id: string;
  submitted_text: string;
  input_modality: InputModality;
  raw_transcript: string | null;
  stt_confidence: number | null;
};

export type QueryAcceptedResponse = {
  turn_id: string;
  status: "processing";
};

export type ClarificationRequest = {
  session_id: string;
  turn_id: string;
  selection: string | null;
  resolution_type: "option_selected" | "escaped" | "timeout";
};

export type ResultResponse = {
  turn_id: string;
  chart_type: "bar" | "line" | "table" | "stat";
  chart_rationale: string;
  confidence_tier: "High" | "Medium" | "Low";
  generated_sql: string;
  result: {
    columns: string[];
    rows: Array<Array<string | number | null>>;
    row_count: number;
  };
  tts_text: string;
  from_cache: boolean;
};

export type LastResult = {
  turnId: string;
  confidenceTier: "High" | "Medium" | "Low";
  chartType: string;
  chartRationale: string;
  resultData: ResultResponse;
  proactiveQuestions: string[];
};

export type PipelineEvent =
  | {
      type: "pipeline_progress";
      stage: string;
      turn_id: string;
      elapsed_ms: number;
    }
  | {
      type: "clarification_request";
      turn_id: string;
      question: string;
      options: string[];
      timeout_seconds: number;
    }
  | {
      type: "clarification_timeout_warning";
      turn_id: string;
      seconds_remaining: number;
    }
  | {
      type: "result_ready";
      turn_id: string;
      confidence_tier: "High" | "Medium" | "Low";
      chart_type: "bar" | "line" | "table" | "stat";
      chart_rationale: string;
      result_json: Record<string, unknown>;
      proactive_questions: string[];
      from_cache: boolean;
    }
  | {
      type: "pipeline_error";
      turn_id: string;
      code: string;
      message: string;
    };

export type AudioEvent =
  | {
      type: "interim_transcript";
      text: string;
      is_final: false;
    }
  | {
      type: "final_transcript";
      text: string;
      confidence: number;
      is_final: true;
    }
  | {
      type: "error";
      code: string;
      message: string;
    };
