import type { ResultResponse } from "./types";

export type ChartType = "bar" | "line" | "table" | "stat";
export type ResultCell = string | number | null;
type SemanticColumn = NonNullable<ResultResponse["result"]["semantic_columns"]>[number];

const CHART_LABELS: Record<ChartType, string> = {
  bar: "Bar",
  line: "Line",
  table: "Table",
  stat: "KPI",
};

export function displayNameForColumn(result: ResultResponse, columnName: string) {
  return semanticColumns(result).find((column) => column.name === columnName)?.display_name ?? columnName;
}

export function semanticColumns(result: ResultResponse): SemanticColumn[] {
  if (result.result.semantic_columns?.length) return result.result.semantic_columns;
  return result.result.columns.map((column, index) => ({
    name: column,
    display_name: titleCase(column),
    role: inferRole(column, index, result.result.rows),
    value_type: inferValueType(result.result.rows.map((row) => row[index])),
    ...inferDisplaySemantics(column, index, result.result.rows),
  }));
}

export function validChartOptions(result: ResultResponse): Array<{ value: ChartType; label: string }> {
  const valid = result.valid_visualizations?.length ? result.valid_visualizations : inferValidVisualizations(result);
  return valid.map((value) => ({ value, label: CHART_LABELS[value] }));
}

export function selectedChartType(result: ResultResponse, requested: string | null): ChartType {
  const valid = validChartOptions(result).map((option) => option.value);
  if (requested && valid.includes(requested as ChartType)) return requested as ChartType;
  if (valid.includes(result.chart_type)) return result.chart_type;
  return "table";
}

export function formatResultValue(value: ResultCell | undefined, column?: SemanticColumn): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") {
    const inferred = inferDisplaySemantics(column?.name ?? "value", 0, [[value]]);
    const display = {
      name: column?.name ?? "value",
      display_name: column?.display_name ?? "Value",
      role: column?.role ?? "metric" as const,
      value_type: column?.value_type ?? "number" as const,
      unit: column?.unit ?? inferred.unit,
      format: column?.format ?? inferred.format,
    };
    if (display.format === "percentage") {
      return new Intl.NumberFormat("en-US", { style: "percent", maximumFractionDigits: 1 }).format(value);
    }
    if (display.format === "compact currency" && display.unit) {
      return new Intl.NumberFormat("en-US", {
        style: "currency",
        currency: display.unit,
        notation: "compact",
        maximumFractionDigits: 1,
      }).format(value);
    }
    if (display.format === "full currency" && display.unit) {
      return new Intl.NumberFormat("en-US", {
        style: "currency",
        currency: display.unit,
        maximumFractionDigits: 2,
      }).format(value);
    }
    if (display.format === "compact number") {
      return new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(value);
    }
    if (display.format === "integer") {
      return new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(value);
    }
    return new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(value);
  }
  if (typeof value === "string" && (column?.value_type === "date" || column?.format === "date" || column?.format === "datetime")) {
    const date = new Date(value);
    if (!Number.isNaN(date.getTime())) return new Intl.DateTimeFormat("en-US", { dateStyle: "medium" }).format(date);
  }
  return String(value);
}

export function resultRowSummary(result: ResultResponse) {
  const preview = result.result.preview_row_count ?? result.result.rows.length;
  const total = result.result.row_count;
  if (result.result.is_truncated || preview < total) return `Showing ${preview} of ${total} rows`;
  return `${total} ${total === 1 ? "row" : "rows"}`;
}

export function chartRationaleFor(result: ResultResponse, chartType: ChartType) {
  if (chartType === result.chart_type) return result.chart_rationale;
  if (chartType === "table") return "Detailed tabular view requested.";
  if (chartType === "stat") return "Single KPI view requested.";
  if (chartType === "bar") return "Categorical comparison view requested.";
  return "Trend view requested.";
}

function titleCase(value: string) {
  return value.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
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

function inferDisplaySemantics(column: string, index: number, rows: ResultCell[][]): Pick<SemanticColumn, "unit" | "format"> {
  const lower = column.toLowerCase();
  const valueType = inferValueType(rows.map((row) => row[index]));
  if (valueType !== "number") {
    return { unit: null, format: valueType === "string" && /(date|month|year|quarter|week|day|time)/.test(lower) ? "date" : null };
  }
  if (/(percent|percentage|rate|margin|share|conversion)/.test(lower)) return { unit: null, format: "percentage" };
  if (/(revenue|sales|cost|price|profit|amount|refund|gmv)/.test(lower)) return { unit: "USD", format: "compact currency" };
  if (/(count|number|volume|units|accounts|customers|orders)/.test(lower)) return { unit: null, format: "compact number" };
  return { unit: null, format: "decimal" };
}

function inferValidVisualizations(result: ResultResponse): ChartType[] {
  const columns = semanticColumns(result);
  const roles = columns.map((column) => column.role);
  const types = columns.map((column) => column.value_type);
  const options: ChartType[] = ["table"];
  const hasMetric = roles.includes("metric") || types.includes("number");
  const hasDimension = roles.some((role) => role === "dimension" || role === "time");
  if (result.result.row_count === 1 && hasMetric) options.push("stat");
  if (columns.length >= 2 && hasDimension && hasMetric) options.push(roles[0] === "time" ? "line" : "bar");
  return options;
}

export function deriveCaveatText(result: ResultResponse): string | null {
  if (result.confidence_tier === "High") return null;
  const prefix = result.confidence_tier === "Low" ? "Needs confirmation" : "Review recommended";
  const reasons = result.confidence_reasons ?? result.trust?.confidence_reasons ?? [];
  if (reasons.length > 0) {
    const reason = reasons[0].toLowerCase();
    if (/time|period|date|quarter|month|year/.test(reason)) return `${prefix} — confirm the reporting period.`;
    if (/product|customer|region|segment|scope|entity/.test(reason)) return `${prefix} — confirm which business scope is included.`;
    if (/metric|calculate|measure/.test(reason)) return `${prefix} — confirm which metric should be used.`;
    if (/join|connect|duplicate/.test(reason)) return `${prefix} — confirm how the data should be connected.`;
  }
  if (result.warnings.some((warning) => warning.code === "possible_duplication")) {
    return "Review recommended — potential duplicate records may inflate this total.";
  }
  return result.confidence_tier === "Low"
    ? "Needs confirmation — this result is directional because the request could be interpreted more than one way."
    : "Review recommended — confirm the scope before acting on this result.";
}

export function validateNarrative(text: string): { valid: boolean; reason?: string } {
  if (!text || !text.trim()) return { valid: false, reason: "Narrative is empty." };
  if (/[*_`#[\]|]/.test(text)) return { valid: false, reason: "Narrative contains markdown characters not suitable for TTS." };
  const sentences = text.trim().split(/[.!?]+(?:\s+|$)/).filter(Boolean);
  if (sentences.length > 3) return { valid: false, reason: `Narrative has ${sentences.length} sentences; limit is 3 for executive TTS.` };
  return { valid: true };
}

export function formatSqlHash(hash: string | null | undefined): string {
  return hash ? hash.slice(0, 8).toUpperCase() : "—";
}

export function formatExecutionTime(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "—";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

export function formatDataSources(result: ResultResponse): string {
  const sources = result.trust?.data_sources;
  if (sources?.length) return sources.join(", ");
  const matches = Array.from((result.generated_sql ?? "").matchAll(/(?:FROM|JOIN)\s+([a-zA-Z_][a-zA-Z0-9_.]*)/gi), (match) => match[1].toLowerCase());
  const unique = [...new Set(matches)];
  return unique.length ? unique.join(", ") : "workspace data";
}
