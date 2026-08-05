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
  anomaly?: BriefingAnomaly | null;
  anomalies?: BriefingAnomaly[];
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

export type BriefingKpi = {
  label: string;
  value: string;
  change_pct?: number | null;
  trend?: "up" | "down" | "neutral" | null;
  insight: string;
};

export type BriefingAnomaly = {
  severity: "warning" | "critical" | "info";
  title: string;
  description: string;
  direction?: "up" | "down" | null;
  magnitude_pct?: number | null;
};

export type ExecutiveBriefingData = {
  date: string;
  greeting: string;
  kpis: BriefingKpi[];
  summary_narrative: string;
  anomalies: BriefingAnomaly[];
  proactive_insights: string[];
  is_live?: boolean;
  data_source?: "live" | "fallback";
};

export type GraphNode = {
  id: string;
  label: string;
  type: "query" | "entity" | "metric" | "filter" | "insight";
  turn_index: number;
};

export type GraphEdge = {
  source: string;
  target: string;
  relation: string;
};

export type MemoryGraphData = {
  session_id: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
};

export type MemoryItem = {
  id: string;
  memory_type: "metric_interest" | "dimension_interest" | "time_range" | "filter_preference" | "clarification_resolution";
  label: string;
  confidence: number;
  last_observed_at?: string | null;
  created_at?: string | null;
  source_turn_id?: string | null;
};

export type MemorySummaryResponse = {
  items: MemoryItem[];
  total: number;
};

export type PinnedAnalysis = {
  id: string;
  title: string;
  note?: string | null;
  original_question?: string;
  chart_type?: string;
  saved_at?: string;
  result?: ResultResponse["result"] | null;
  data_status: "available" | "no_snapshot";
  snapshot_headline_value?: number | null;
  snapshot_headline_label?: string | null;
};

export type QueryHistoryItem = {
  turn_id: string;
  session_id: string;
  submitted_text: string;
  user_input?: string;
  user_display?: string;
  input_modality: InputModality;
  created_at: string;
  confidence_tier?: "High" | "Medium" | "Low" | null;
  chart_type?: string | null;
  quality_flags?: string[];
  execution_time_ms?: number | null;
  latency_ms?: number | null;
  user_feedback?: number | null;
};

export type QueryHistoryPage = {
  items: QueryHistoryItem[];
  total: number;
  total_count: number;
  page: number;
  page_size: number;
  total_pages: number;
  has_more?: boolean;
};

export type QueryHistoryDetail = {
  turn_id: string;
  session_id: string;
  tenant_id: string;
  submitted_text: string;
  input_modality: InputModality;
  raw_transcript?: string | null;
  stt_confidence?: number | null;
  transcript_edited?: boolean;
  generated_sql?: string | null;
  chart_type?: string | null;
  chart_rationale?: string | null;
  confidence_tier?: string | null;
  confidence_reasons?: string[];
  row_count?: number | null;
  execution_time_ms?: number | null;
  user_feedback?: number | null;
  quality_flag?: string | null;
  quality_flags?: string[];
  created_at: string;
};

export type TenantAnalytics = {
  total_queries: number;
  active_sessions: number;
  avg_latency_ms: number;
  satisfaction_rate: number;
  success_rate_pct?: number;
  low_quality_rate_pct?: number;
  queries_by_day?: Array<{ date: string; count: number }>;
  queries_per_day?: Array<{ date: string; count: number }>;
  modality_breakdown?: { voice: number; text: number };
  confidence_breakdown?: { High: number; Medium: number; Low: number };
  confidence_distribution: { high: number; medium: number; low: number };
  top_metrics?: Array<{ metric: string; count: number }>;
  top_questions?: Array<{ user_input: string; count: number }>;
};

export type HealthCheckItem = {
  name: string;
  status: "ok" | "degraded" | "error" | "not_configured";
  latency_ms?: number | null;
  details?: string | null;
};

export type SystemHealthResponse = {
  status: "ok" | "degraded" | "error";
  overall?: "ok" | "degraded" | "error";
  components?: Record<string, HealthCheckItem>;
  checks?: HealthCheckItem[];
  checked_at: string;
  version?: string;
  last_briefing_at?: string | null;
};

export type ShareLinkCreateRequest = {
  turn_id: string;
  title?: string;
  expires_in_days?: number;
  ttl_hours?: number;
};

export type ShareLinkCreateResponse = {
  token: string;
  share_url?: string;
  url?: string;
  expires_at: string;
};

export type SharedResultResponse = {
  token: string;
  title?: string;
  label?: string;
  submitted_text?: string;
  user_input?: string;
  chart_type?: string;
  confidence_tier?: "High" | "Medium" | "Low";
  generated_sql?: string;
  result?: ResultResponse["result"];
  full_result?: ResultResponse["result"];
  created_at: string;
  expires_at: string;
};

export type WorkspaceDetail = {
  id: string;
  tenant_id: string;
  name: string;
  widgets: PinnedAnalysis[];
};
