import { describe, expect, it } from "vitest";
import {
  formatResultValue,
  resultRowSummary,
  chartRationaleFor,
  selectedChartType,
  semanticColumns,
  validChartOptions,
  deriveCaveatText,
  validateNarrative,
  formatSqlHash,
  formatExecutionTime,
  formatDataSources,
} from "./resultSemantics";
import type { ResultResponse } from "./types";

const baseResult: ResultResponse = {
  turn_id: "turn-1",
  chart_type: "bar",
  chart_rationale: "Bar is valid for categorical comparison.",
  confidence_tier: "High",
  generated_sql: "SELECT customer_segment, SUM(net_revenue) FROM orders JOIN customers ON orders.customer_id = customers.id GROUP BY customer_segment",
  result: {
    columns: ["customer_segment", "total_net_revenue"],
    rows: [["Enterprise", 1240000]],
    row_count: 1
  },
  tts_text: "Enterprise leads net revenue.",
  proactive_questions: [],
  warnings: [],
  from_cache: false
};

const mediumResult: ResultResponse = {
  ...baseResult,
  confidence_tier: "Medium",
};

const mediumWithReasons: ResultResponse = {
  ...baseResult,
  confidence_tier: "Medium",
  confidence_reasons: ["Schema match was weaker than usual"],
};

const mediumWithWarnings: ResultResponse = {
  ...baseResult,
  confidence_tier: "Medium",
  warnings: [{ code: "possible_duplication", message: "Duplicates detected.", suggested_sql: null }],
};

const lowResult: ResultResponse = {
  ...baseResult,
  confidence_tier: "Low",
};

describe("result semantics", () => {
  it("infers semantic columns when the backend omits metadata", () => {
    const columns = semanticColumns(baseResult);
    expect(columns[0]).toMatchObject({ display_name: "Customer Segment", role: "dimension", value_type: "string" });
    expect(columns[1]).toMatchObject({ display_name: "Total Net Revenue", role: "metric", value_type: "number" });
  });

  it("limits chart choices to valid visualizations", () => {
    expect(validChartOptions(baseResult).map((option) => option.value)).toEqual(["table", "stat", "bar"]);
    expect(selectedChartType(baseResult, "line")).toBe("bar");
    expect(selectedChartType(baseResult, "table")).toBe("table");
  });

  it("prefers backend valid visualizations when present", () => {
    const result: ResultResponse = { ...baseResult, valid_visualizations: ["table"] };
    expect(validChartOptions(result).map((option) => option.value)).toEqual(["table"]);
    expect(selectedChartType(result, "bar")).toBe("table");
  });

  it("formats metrics and row summaries consistently", () => {
    const metric = semanticColumns(baseResult)[1];
    expect(formatResultValue(1240000, metric)).toBe("1,240,000");
    expect(resultRowSummary(baseResult)).toBe("1 row");
    expect(
      resultRowSummary({
        ...baseResult,
        result: { ...baseResult.result, rows: [["Enterprise", 1240000]], row_count: 10, preview_row_count: 1, is_truncated: true }
      })
    ).toBe("Showing 1 of 10 rows");
  });

  it("applies semantic formats correctly", () => {
    // 1. `net_revenue` with unit USD renders `$1.5M`.
    expect(formatResultValue(1500000, { name: "net_revenue", display_name: "Net Rev", role: "metric", value_type: "number", format: "compact currency", unit: "USD" })).toBe("$1.5M");
    // 2. percentage column renders `23%`.
    expect(formatResultValue(0.23, { name: "rate", display_name: "Rate", role: "metric", value_type: "number", format: "percentage" })).toBe("23%");
    // 3. date column renders human-readable date.
    expect(formatResultValue("2023-10-01", { name: "date", display_name: "Date", role: "dimension", value_type: "date" })).toBe("Oct 1, 2023");
    // 4. null renders a deliberate empty or em dash replacement according to product decision.
    expect(formatResultValue(null)).toBe("—");
  });

  it("updates chart rationale when the selected chart changes", () => {
    expect(chartRationaleFor(baseResult, "bar")).toBe("Bar is valid for categorical comparison.");
    expect(chartRationaleFor(baseResult, "table")).toBe("Detailed tabular view requested.");
    expect(chartRationaleFor(baseResult, "stat")).toBe("Single KPI view requested.");
  });

  // ── Phase 4.2: Evidence-derived caveats ────────────────────────

  it("4.2: returns null caveat for High confidence", () => {
    expect(deriveCaveatText(baseResult)).toBeNull();
  });

  it("4.2: derives caveat from backend confidence_reasons when present", () => {
    const caveat = deriveCaveatText(mediumWithReasons);
    expect(caveat).toMatch(/Partial match/);
    expect(caveat).toMatch(/schema match was weaker/i);
  });

  it("4.2: derives caveat from warnings when no reasons provided", () => {
    const caveat = deriveCaveatText(mediumWithWarnings);
    expect(caveat).toMatch(/Partial match/);
    expect(caveat).toMatch(/duplicate/i);
  });

  it("4.2: falls back to tier-based caveat for Medium with no other evidence", () => {
    const caveat = deriveCaveatText(mediumResult);
    expect(caveat).toMatch(/We made some assumptions/);
  });

  it("4.2: falls back to assumptions caveat for Low tier", () => {
    const caveat = deriveCaveatText(lowResult);
    expect(caveat).toMatch(/We made a few assumptions/);
  });

  // ── Phase 4.4: Visualization policy ───────────────────────────

  it("4.4: line chart unavailable for unordered categorical data", () => {
    // customer_segment is a dimension but not a time role, so line should NOT appear
    const opts = validChartOptions(baseResult).map((o) => o.value);
    expect(opts).not.toContain("line");
  });

  it("4.4: stat unavailable for multi-row non-KPI result", () => {
    const multiRow: ResultResponse = {
      ...baseResult,
      result: { ...baseResult.result, rows: [["Enterprise", 100], ["SMB", 200]], row_count: 2 }
    };
    const opts = validChartOptions(multiRow).map((o) => o.value);
    expect(opts).not.toContain("stat");
  });

  it("4.4: invalid backend chart recommendation falls back to table", () => {
    const badChart = { ...baseResult, valid_visualizations: ["table"] as Array<"bar" | "line" | "table" | "stat"> };
    // Even if user requests "bar", must fall back to table since it's not in valid set
    expect(selectedChartType(badChart, "bar")).toBe("table");
    expect(selectedChartType(badChart, "line")).toBe("table");
  });

  // ── Phase 4.5: Narrative guardrails ───────────────────────────

  it("4.5: valid narrative passes guardrail (1-3 sentences, plain text)", () => {
    expect(validateNarrative("Enterprise leads net revenue.")).toEqual({ valid: true });
    expect(validateNarrative("Revenue is up. Enterprise leads. SMB follows.")).toEqual({ valid: true });
  });

  it("4.5: narrative with > 3 sentences fails guardrail", () => {
    const result = validateNarrative("Sentence one. Sentence two. Sentence three. Sentence four.");
    expect(result.valid).toBe(false);
    expect(result.reason).toMatch(/4 sentences/);
  });

  it("4.5: narrative containing markdown is rejected for TTS", () => {
    const result = validateNarrative("Revenue is **high**. Enterprise leads.");
    expect(result.valid).toBe(false);
    expect(result.reason).toMatch(/markdown/i);
  });

  it("4.5: empty narrative fails guardrail", () => {
    expect(validateNarrative("").valid).toBe(false);
    expect(validateNarrative("   ").valid).toBe(false);
  });

  // ── Phase 4 trust surface utilities ───────────────────────────

  it("formatSqlHash returns first 8 chars uppercase or em dash", () => {
    expect(formatSqlHash("abcdef1234567890")).toBe("ABCDEF12");
    expect(formatSqlHash(null)).toBe("—");
    expect(formatSqlHash(undefined)).toBe("—");
  });

  it("formatExecutionTime formats ms and seconds correctly", () => {
    expect(formatExecutionTime(450)).toBe("450ms");
    expect(formatExecutionTime(1500)).toBe("1.5s");
    expect(formatExecutionTime(null)).toBe("—");
  });

  it("formatDataSources infers table names from SQL when trust.data_sources absent", () => {
    const sources = formatDataSources(baseResult);
    expect(sources).toContain("orders");
    expect(sources).toContain("customers");
  });

  it("formatDataSources uses trust.data_sources when provided", () => {
    const withSources: ResultResponse = {
      ...baseResult,
      trust: { confidence_tier: "High", row_count: 1, warning_count: 0, generated_sql_present: true, semantic_columns_present: false, data_sources: ["orders", "customers", "products"] }
    };
    expect(formatDataSources(withSources)).toBe("orders, customers, products");
  });
});
