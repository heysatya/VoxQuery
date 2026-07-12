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
};

export type SessionCreateResponse = {
  session_id: string;
  conversation_id: string;
  expires_at: string;
};

export type QueryRequest = {
  session_id: string;
  parent_turn_id: string | null;
  submitted_text: string;
  input_modality: InputModality;
  raw_transcript: string | null;
  stt_confidence: number | null;
  transcript_edited: boolean;
};

export type QueryAcceptedResponse = {
  turn_id: string;
  status: "processing";
};

export type ClarificationRequest = {
  session_id: string;
  turn_id: string;
  selection: string | null;
  resolution_type: "option_selected" | "escaped";
};

export type ResultResponse = {
  turn_id: string;
  chart_type: "bar" | "line" | "table" | "stat";
  chart_rationale: string;
  confidence_tier: "High" | "Medium" | "Low";
  confidence_reasons?: string[];
  generated_sql: string;
  result: {
    columns: string[];
    rows: Array<Array<string | number | null>>;
    row_count: number;
    semantic_columns?: Array<{
      name: string;
      display_name: string;
      role: "dimension" | "metric" | "time" | "identifier" | "unknown";
      value_type: "string" | "number" | "date" | "datetime" | "boolean" | "null" | "mixed";
      unit?: string | null;
      format?: "compact currency" | "full currency" | "percentage" | "compact number" | "integer" | "decimal" | "date" | "datetime" | "duration" | "null" | null;
    }>;
    preview_row_count?: number;
    is_truncated?: boolean;
  };
  tts_text: string;
  proactive_questions: string[];
  warnings: Array<{
    code: "possible_duplication";
    message: string;
    suggested_sql: string | null;
  }>;
  valid_visualizations?: Array<"bar" | "line" | "table" | "stat">;
  trust?: {
    confidence_tier: "High" | "Medium" | "Low";
    confidence_reasons?: string[];
    row_count: number;
    warning_count: number;
    generated_sql_present: boolean;
    semantic_columns_present: boolean;
    execution_time_ms?: number | null;
    data_sources?: string[] | null;
    sql_hash?: string | null;
    data_freshness_note?: string | null;
  } | null;
  from_cache: boolean;
};

export type LastResult = {
  turnId: string;
  submittedText: string;
  parentTurnId: string | null;
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
    }
  | {
      type: "result_ready";
      turn_id: string;
      confidence_tier?: "High" | "Medium" | "Low" | unknown;
      chart_type?: "bar" | "line" | "table" | "stat" | unknown;
      chart_rationale?: string | unknown;
      result_json?: Record<string, unknown>;
      proactive_questions?: string[];
      from_cache?: boolean;
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
