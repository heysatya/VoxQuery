import type { ResultResponse } from "./types";

export type ChartType = "bar" | "line" | "table" | "stat";

export type ResultCell = string | number | null;

type SemanticColumn = NonNullable<ResultResponse["result"]["semantic_columns"]>[number];

const CHART_LABELS: Record<ChartType, string> = {
  bar: "Bar",
  line: "Line",
  table: "Table",
  stat: "Stat"
};

export function displayNameForColumn(result: ResultResponse, columnName: string) {
  return semanticColumns(result).find((column) => column.name === columnName)?.display_name ?? columnName;
}

export function semanticColumns(result: ResultResponse): SemanticColumn[] {
  if (result.result.semantic_columns?.length) {
    return result.result.semantic_columns;
  }
  return result.result.columns.map((column, index) => ({
    name: column,
    display_name: column.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase()),
    role: inferRole(column, index, result.result.rows),
    value_type: inferValueType(result.result.rows.map((row) => row[index]))
  }));
}

export function validChartOptions(result: ResultResponse): Array<{ value: ChartType; label: string }> {
  const valid = result.valid_visualizations?.length
    ? result.valid_visualizations
    : inferValidVisualizations(result);
  return valid.map((value) => ({ value, label: CHART_LABELS[value] }));
}

export function selectedChartType(result: ResultResponse, requested: string | null): ChartType {
  const valid = validChartOptions(result).map((option) => option.value);
  const recommended = result.chart_type;
  if (requested && valid.includes(requested as ChartType)) return requested as ChartType;
  if (valid.includes(recommended)) return recommended;
  return "table";
}

export function formatResultValue(value: ResultCell | undefined, column?: SemanticColumn) {
  if (value === null || value === undefined) return "—"; // Product decision: em dash for nulls
  if (typeof value === "number") {
    if (column?.format === "percentage") {
      return new Intl.NumberFormat("en-US", { style: "percent", maximumFractionDigits: 1 }).format(value);
    }
    if (column?.format === "compact currency" && column?.unit) {
      return new Intl.NumberFormat("en-US", { style: "currency", currency: column.unit, notation: "compact" }).format(value);
    }
    if (column?.format === "full currency" && column?.unit) {
      return new Intl.NumberFormat("en-US", { style: "currency", currency: column.unit }).format(value);
    }
    if (column?.format === "compact number") {
      return new Intl.NumberFormat("en-US", { notation: "compact" }).format(value);
    }
    if (column?.format === "integer") {
      return new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(value);
    }
    if (column?.role === "metric" || column?.format === "decimal") {
      return new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(value);
    }
    return String(value);
  }
  if (typeof value === "string") {
    if (column?.value_type === "date" || column?.format === "date" || column?.format === "datetime") {
      const date = new Date(value);
      if (!isNaN(date.getTime())) {
        return new Intl.DateTimeFormat("en-US", { dateStyle: "medium" }).format(date);
      }
    }
  }
  return value;
}

export function resultRowSummary(result: ResultResponse) {
  const preview = result.result.preview_row_count ?? result.result.rows.length;
  const total = result.result.row_count;
  if (result.result.is_truncated || preview < total) {
    return `Showing ${preview} of ${total} rows`;
  }
  return `${total} ${total === 1 ? "row" : "rows"}`;
}

export function chartRationaleFor(result: ResultResponse, chartType: ChartType) {
  if (chartType === result.chart_type) return result.chart_rationale;
  if (chartType === "table") return "Detailed tabular view requested.";
  if (chartType === "stat") return "Single KPI view requested.";
  if (chartType === "bar") return "Categorical comparison view requested.";
  if (chartType === "line") return "Trend view requested.";
  return `${CHART_LABELS[chartType]} is available for this result shape.`;
}

function inferRole(column: string, index: number, rows: ResultCell[][]): SemanticColumn["role"] {
  const lower = column.toLowerCase();
  const valueType = inferValueType(rows.map((row) => row[index]));
  if (/(date|month|year|quarter|week|day|time)/.test(lower)) return "time";
  if (lower.endsWith("_id") || lower === "id") return "identifier";
  if (valueType === "number" && (index > 0 || rows.length === 1)) return "metric";
  if (["string", "date", "datetime", "boolean"].includes(valueType)) return "dimension";
  return "unknown";
}

function inferValueType(values: Array<ResultCell | undefined>): SemanticColumn["value_type"] {
  const nonNull = values.filter((value): value is string | number => value !== null && value !== undefined);
  if (!nonNull.length) return "null";
  if (nonNull.every((value) => typeof value === "number")) return "number";
  if (nonNull.every((value) => typeof value === "string")) return "string";
  return "mixed";
}

function inferValidVisualizations(result: ResultResponse): ChartType[] {
  const columns = semanticColumns(result);
  const roles = columns.map((column) => column.role);
  const types = columns.map((column) => column.value_type);
  const options: ChartType[] = ["table"];
  const hasMetric = roles.includes("metric") || types.includes("number");
  const hasDimension = roles.some((role) => role === "dimension" || role === "time");
  if (result.result.row_count === 1 && hasMetric) options.push("stat");
  if (columns.length >= 2 && hasDimension && hasMetric) options.push("bar");
  if (columns.length >= 2 && roles[0] === "time" && hasMetric) options.push("line");
  return options;
}

/* ── Phase 4: Trust Surface Utilities ─────────────────────────── */

/**
 * 4.2 Evidence-derived caveat text.
 * Derives a human-readable caveat from backend evidence rather than a hardcoded string.
 * Priority: backend confidence_reasons > warnings > tier-based fallback.
 */
export function deriveCaveatText(result: ResultResponse): string | null {
  const tier = result.confidence_tier;
  if (tier === "High") return null;
  // Prefer backend-provided reasons
  const reasons = result.confidence_reasons ?? result.trust?.confidence_reasons ?? [];
  if (reasons.length > 0) {
    return `${tier} confidence — ${reasons[0].toLowerCase()}`;
  }
  // Derive from warnings
  if (result.warnings.some((w) => w.code === "possible_duplication")) {
    return `${tier} confidence — joined tables may contain duplicate source records.`;
  }
  // Tier-based fallback (generic but still evidence-referenced, not hardcoded)
  if (tier === "Low") {
    return "We made a few assumptions to answer this.";
  }
  return "We made some assumptions to calculate this. Review the SQL below.";
}

/**
 * 4.5 Narrative guardrail.
 * Returns true when a narrative string is safe for TTS and executive presentation:
 *   - plain text (no markdown)
 *   - ≤ 3 sentences
 */
export function validateNarrative(text: string): { valid: boolean; reason?: string } {
  if (!text || !text.trim()) return { valid: false, reason: "Narrative is empty." };
  if (/[*_`#[\]|]/.test(text)) return { valid: false, reason: "Narrative contains markdown characters not suitable for TTS." };
  // Count sentences: split on . ! ? followed by space or end of string
  const sentences = text.trim().split(/[.!?]+(?:\s+|$)/).filter(Boolean);
  if (sentences.length > 3) {
    return { valid: false, reason: `Narrative has ${sentences.length} sentences; limit is 3 for executive TTS.` };
  }
  return { valid: true };
}

/**
 * Formats an abbreviated SQL hash for display (first 8 chars).
 */
export function formatSqlHash(hash: string | null | undefined): string {
  if (!hash) return "—";
  return hash.slice(0, 8).toUpperCase();
}

/**
 * Formats execution time in milliseconds to a human-readable string.
 */
export function formatExecutionTime(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "—";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

/**
 * Derives a human-readable list of data sources from the result.
 */
export function formatDataSources(result: ResultResponse): string {
  const sources = result.trust?.data_sources;
  if (sources && sources.length > 0) return sources.join(", ");
  // Infer from SQL: extract table names after FROM / JOIN keywords
  const sql = result.generated_sql ?? "";
  const matches = Array.from(sql.matchAll(/(?:FROM|JOIN)\s+([a-zA-Z_][a-zA-Z0-9_.]*)/gi), (m) => m[1].toLowerCase());
  const unique = [...new Set(matches)];
  if (unique.length > 0) return unique.join(", ");
  return "warehouse data";
}
