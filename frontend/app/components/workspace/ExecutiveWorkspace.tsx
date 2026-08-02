"use client";

import React from "react";
import { LayoutGrid, Pin, RefreshCw, Trash2 } from "lucide-react";
import { ResponsiveContainer, BarChart, Bar, LineChart, Line, XAxis, YAxis, Tooltip as RechartsTooltip } from "recharts";
import { formatResultValue } from "../../../lib/resultSemantics";
import type { ResultResponse } from "../../../lib/types";

type StoredSemanticColumn = NonNullable<ResultResponse["result"]["semantic_columns"]>[number];

type StoredResult = {
  columns?: string[];
  rows?: Array<Array<string | number | null>>;
  row_count?: number;
  semantic_columns?: StoredSemanticColumn[];
};

export type PinnedWidget = {
  id: string;
  title: string;
  created_at?: string;
  saved_at?: string;
  session_id?: string;
  user_input?: string;
  data_status?: "available" | "unavailable";
  data_source?: "snapshot" | "unavailable";
  chart_type?: string | null;
  result?: StoredResult | null;
  full_result?: StoredResult | null;
};

type ExecutiveWorkspaceProps = {
  pinnedWidgets?: PinnedWidget[];
  onRemoveWidget?: (id: string) => void;
  onRerunAnalysis?: (query: string) => void;
};

function cleanTitle(rawTitle: string): string {
  const normalized = rawTitle.trim().replace(/_/g, " ").replace(/\s+/g, " ");
  if (!normalized) return "Pinned analysis";
  const withoutPrefix = normalized.replace(/^(trend|analysis|metric):\s*/i, "");
  return withoutPrefix.length > 72 ? `${withoutPrefix.slice(0, 69)}...` : withoutPrefix;
}

function formatSavedDate(value?: string): string | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric" }).format(date);
}

function chartRows(result: StoredResult, columns: string[]) {
  const rows = result.rows ?? [];
  if (columns.length < 2) return [];
  return rows.slice(0, 8).flatMap((row) => {
    const value = row[1];
    if (typeof value !== "number") return [];
    return [{
      name: String(row[0] ?? "Unknown").length > 14 ? `${String(row[0]).slice(0, 12)}...` : String(row[0] ?? "Unknown"),
      value,
    }];
  });
}

export function ExecutiveWorkspace({ pinnedWidgets = [], onRemoveWidget, onRerunAnalysis }: ExecutiveWorkspaceProps) {
  return (
    <section className="w-full rounded-2xl glass-card p-5 relative overflow-hidden" aria-labelledby="pinned-analyses-title">
      <div className="flex items-start justify-between gap-4 mb-4">
        <div className="flex items-start gap-2.5">
          <div className="p-2 rounded-xl bg-[var(--accent-blue)]/10 text-[var(--accent-blue)] border border-[var(--accent-blue)]/20">
            <LayoutGrid className="w-4 h-4" aria-hidden="true" />
          </div>
          <div>
            <h3 id="pinned-analyses-title" className="text-sm font-semibold text-white flex items-center gap-2">
              Pinned analyses
              <span className="text-[10px] px-2 py-0.5 rounded-full bg-[var(--accent-blue)]/15 text-[var(--accent-blue)] border border-[var(--accent-blue)]/30 font-medium">
                {pinnedWidgets.length}
              </span>
            </h3>
            <p className="text-[11px] text-[var(--text-muted)] mt-0.5">Saved answer snapshots for quick review. They do not update until you run the original question again.</p>
          </div>
        </div>
      </div>

      {pinnedWidgets.length === 0 ? (
        <div className="py-8 flex flex-col items-center justify-center border border-dashed border-white/10 rounded-xl bg-[var(--bg-surface)]/50 p-4 text-center">
          <div className="p-2.5 rounded-full bg-[var(--bg-elevated)] border border-white/10 mb-2">
            <Pin className="w-4 h-4 text-[var(--accent-blue)]" aria-hidden="true" />
          </div>
          <p className="text-xs text-[var(--text-secondary)] font-medium">No analyses pinned yet</p>
          <p className="text-[11px] text-[var(--text-muted)] mt-1 max-w-xs">Pin a useful answer after asking a question to keep it here for later review.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {pinnedWidgets.map((widget) => {
            const result = widget.result ?? widget.full_result ?? null;
            const columns = result?.columns ?? [];
            const rows = result?.rows ?? [];
            const semantics = result?.semantic_columns ?? [];
            const chartData = result ? chartRows(result, columns) : [];
            const metricIndex = semantics.findIndex((column) => column.role === "metric" || column.value_type === "number");
            const metricColumn = semantics[metricIndex >= 0 ? metricIndex : 1];
            const headlineValue = rows.length > 0 && metricColumn ? rows[0][metricIndex >= 0 ? metricIndex : 1] : undefined;
            const chartType = widget.chart_type === "line" ? "line" : "bar";
            const savedDate = formatSavedDate(widget.saved_at ?? widget.created_at);
            const hasData = Boolean(result && rows.length > 0 && columns.length > 0);
            const isEmptyResult = Boolean(result && (result.row_count ?? rows.length) === 0);

            return (
              <article key={widget.id} className="p-4 rounded-xl bg-[var(--bg-surface)] border border-white/10 flex flex-col relative group hover:border-[var(--accent-blue)]/40 transition-colors">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="text-[10px] uppercase tracking-[0.16em] text-[var(--text-muted)] mb-1">Pinned analysis</p>
                    <h4 className="text-sm font-semibold text-white line-clamp-2">{cleanTitle(widget.title)}</h4>
                  </div>
                  {onRemoveWidget && (
                    <button
                      type="button"
                      onClick={() => onRemoveWidget(widget.id)}
                      className="p-2 rounded-lg text-[var(--text-muted)] hover:text-[var(--accent-rose)] hover:bg-[var(--accent-rose)]/10 border border-transparent hover:border-[var(--accent-rose)]/20 transition-colors touch-target"
                      title="Remove pinned analysis"
                      aria-label={`Remove ${cleanTitle(widget.title)}`}
                    >
                      <Trash2 className="w-3.5 h-3.5" aria-hidden="true" />
                    </button>
                  )}
                </div>

                {hasData && headlineValue !== undefined ? (
                  <div className="mt-3 flex items-end justify-between gap-3">
                    <div>
                      <p className="text-[10px] text-[var(--text-muted)]">{metricColumn?.display_name ?? columns[1]}</p>
                      <p className="text-2xl font-semibold tracking-tight text-white">{formatResultValue(headlineValue, metricColumn)}</p>
                    </div>
                    <span className="text-[10px] px-2 py-1 rounded-full border border-cyan-400/20 bg-cyan-400/10 text-cyan-300">Saved snapshot</span>
                  </div>
                ) : (
                  <div className="mt-4 rounded-lg border border-amber-400/20 bg-amber-400/5 px-3 py-3">
                    <p className="text-xs font-medium text-amber-200">
                      {isEmptyResult ? "This analysis returned no matching rows." : "The saved result is unavailable."}
                    </p>
                    <p className="text-[11px] text-amber-100/60 mt-1">Run the original question again to create a current result.</p>
                  </div>
                )}

                <div className="h-28 w-full mt-4 rounded-lg border border-white/5 bg-[var(--bg-base)]/70 p-2 flex items-center justify-center">
                  {chartData.length > 0 ? (
                    <ResponsiveContainer width="100%" height="100%">
                      {chartType === "line" ? (
                        <LineChart data={chartData}>
                          <XAxis dataKey="name" stroke="#64748b" fontSize={10} tickLine={false} />
                          <YAxis stroke="#64748b" fontSize={10} tickLine={false} width={38} tickFormatter={(value) => formatResultValue(value, metricColumn)} />
                          <RechartsTooltip formatter={(value) => [formatResultValue(Number(value), metricColumn), metricColumn?.display_name ?? "Value"]} contentStyle={{ backgroundColor: "#10141c", borderRadius: "8px", border: "1px solid rgba(255,255,255,0.1)" }} />
                          <Line type="monotone" dataKey="value" stroke="#38bdf8" strokeWidth={2} dot={{ r: 3, fill: "#38bdf8" }} />
                        </LineChart>
                      ) : (
                        <BarChart data={chartData}>
                          <XAxis dataKey="name" stroke="#64748b" fontSize={10} tickLine={false} />
                          <YAxis stroke="#64748b" fontSize={10} tickLine={false} width={38} tickFormatter={(value) => formatResultValue(value, metricColumn)} />
                          <RechartsTooltip formatter={(value) => [formatResultValue(Number(value), metricColumn), metricColumn?.display_name ?? "Value"]} contentStyle={{ backgroundColor: "#10141c", borderRadius: "8px", border: "1px solid rgba(255,255,255,0.1)" }} />
                          <Bar dataKey="value" fill="#38bdf8" radius={[4, 4, 0, 0]} />
                        </BarChart>
                      )}
                    </ResponsiveContainer>
                  ) : (
                    <p className="text-xs text-[var(--text-muted)]">{hasData ? "This result is best viewed as a table." : "No visual preview available"}</p>
                  )}
                </div>

                <div className="mt-3 pt-3 border-t border-white/5 flex items-center justify-between gap-3 text-[10px] text-[var(--text-muted)]">
                  <span>{savedDate ? `Saved ${savedDate}` : "Saved analysis"}</span>
                  <div className="flex items-center gap-2">
                    <span>{hasData ? "Snapshot" : "Needs review"}</span>
                    {onRerunAnalysis && widget.user_input && (
                      <button
                        type="button"
                        onClick={() => onRerunAnalysis(widget.user_input as string)}
                        className="inline-flex items-center gap-1 rounded-md border border-cyan-300/20 px-2 py-1 text-[10px] text-cyan-200 hover:bg-cyan-300/10 touch-target"
                        aria-label={`Run saved analysis again: ${cleanTitle(widget.title)}`}
                      >
                        <RefreshCw className="h-3 w-3" aria-hidden="true" />
                        Run again
                      </button>
                    )}
                  </div>
                </div>
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}
