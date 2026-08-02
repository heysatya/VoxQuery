"use client";

import React, { useState } from "react";
import { LayoutGrid, Pin, Trash2, ArrowUp, ArrowDown, RotateCcw, Pencil, Check, X } from "lucide-react";
import { ResponsiveContainer, BarChart, Bar, LineChart, Line, XAxis, YAxis, Tooltip as RechartsTooltip } from "recharts";
import { formatResultValue } from "../../../lib/resultSemantics";
import { extractHeadline } from "../../../lib/resultMetrics";
import { startCheckNow, fetchResult, ApiRequestError } from "../../../lib/api";
import type { PinnedAnalysis } from "../../../lib/types";
import type { ResultResponse } from "../../../lib/types";

type StoredSemanticColumn = NonNullable<ResultResponse["result"]["semantic_columns"]>[number];

type StoredResult = {
  columns?: string[];
  rows?: Array<Array<string | number | null>>;
  row_count?: number;
  semantic_columns?: StoredSemanticColumn[];
};

export type PinnedWidget = PinnedAnalysis;

type ExecutiveWorkspaceProps = {
  pinnedWidgets?: PinnedWidget[];
  onRemoveWidget?: (id: string) => void;
  onRerunAnalysis?: (query: string) => void;
  onUpdateNote?: (widgetId: string, note: string | null) => void;
  token?: string | null;
};

function cleanTitle(rawTitle: string): string {
  const normalized = rawTitle.trim().replace(/_/g, " ").replace(/\s+/g, " ");
  if (!normalized) return "Saved finding";
  const withoutPrefix = normalized.replace(/^(trend|analysis|metric):\s*/i, "");
  return withoutPrefix.length > 72 ? `${withoutPrefix.slice(0, 69)}...` : withoutPrefix;
}

function formatSavedDate(value?: string): string | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? null
    : new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric" }).format(date);
}

function chartRows(result: StoredResult, columns: string[]) {
  const rows = result.rows ?? [];
  if (columns.length < 2) return [];
  return rows.slice(0, 8).flatMap((row) => {
    const value = row[1];
    if (typeof value !== "number") return [];
    return [{
      name: String(row[0] ?? "Unknown").length > 14
        ? `${String(row[0]).slice(0, 12)}...`
        : String(row[0] ?? "Unknown"),
      value,
    }];
  });
}

// ── Delta badge shown after "Check now" completes ─────────────────────────────
function DeltaBadge({ previous, current }: { previous: number; current: number }) {
  if (previous === 0) return null;
  const pctChange = ((current - previous) / Math.abs(previous)) * 100;
  const up = pctChange > 0;
  const flat = Math.abs(pctChange) < 0.05;
  return (
    <div
      className={`mt-2 text-xs flex items-center gap-1 ${
        flat ? "text-[var(--text-muted)]" : up ? "text-emerald-400" : "text-rose-400"
      }`}
    >
      {!flat && (up ? <ArrowUp className="w-3 h-3" /> : <ArrowDown className="w-3 h-3" />)}
      <span>{flat ? "No change" : `${up ? "+" : ""}${pctChange.toFixed(1)}%`} since snapshot</span>
    </div>
  );
}

// ── Inline note editor ────────────────────────────────────────────────────────
function NoteEditor({
  note,
  onSave,
}: {
  note?: string | null;
  onSave: (value: string | null) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(note ?? "");

  if (!editing) {
    return (
      <div className="mt-3 flex items-start gap-1.5">
        {note ? (
          <p className="text-[11px] text-[var(--text-muted)] italic border-l-2 border-white/10 pl-2 flex-1">
            {note}
          </p>
        ) : (
          <p className="text-[11px] text-[var(--text-muted)] flex-1">+ Add a note</p>
        )}
        <button
          type="button"
          onClick={() => { setDraft(note ?? ""); setEditing(true); }}
          className="p-1 rounded text-[var(--text-muted)] hover:text-white hover:bg-white/10 transition-colors shrink-0"
          aria-label="Edit note"
        >
          <Pencil className="w-3 h-3" />
        </button>
      </div>
    );
  }

  return (
    <div className="mt-3 flex flex-col gap-1.5">
      <textarea
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        rows={2}
        placeholder="Why did this matter?"
        className="w-full text-[11px] bg-white/5 border border-white/10 rounded px-2 py-1.5 text-white placeholder-[var(--text-muted)] resize-none focus:outline-none focus:border-[var(--accent-blue)]/50"
      />
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => { onSave(draft.trim() || null); setEditing(false); }}
          className="flex items-center gap-1 text-[10px] text-[var(--accent-blue)] hover:underline"
        >
          <Check className="w-3 h-3" /> Save
        </button>
        <button
          type="button"
          onClick={() => setEditing(false)}
          className="flex items-center gap-1 text-[10px] text-[var(--text-muted)] hover:underline"
        >
          <X className="w-3 h-3" /> Cancel
        </button>
      </div>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────
const CHECK_POLL_INTERVAL_MS = 3000;
const CHECK_MAX_ATTEMPTS = 12;

export function ExecutiveWorkspace({
  pinnedWidgets = [],
  onRemoveWidget,
  onRerunAnalysis,
  onUpdateNote,
  token,
}: ExecutiveWorkspaceProps) {
  const [checking, setChecking] = useState<Record<string, boolean>>({});
  const [freshValues, setFreshValues] = useState<
    Record<string, { value: number | null; label: string | null } | null>
  >({});

  async function handleCheckNow(widget: PinnedWidget) {
    setChecking((s) => ({ ...s, [widget.id]: true }));
    try {
      const { turn_id } = await startCheckNow(widget.id, token);
      for (let attempt = 0; attempt < CHECK_MAX_ATTEMPTS; attempt++) {
        await new Promise((r) => setTimeout(r, CHECK_POLL_INTERVAL_MS));
        try {
          const result = await fetchResult(turn_id, token);
          setFreshValues((s) => ({ ...s, [widget.id]: extractHeadline(result.result) }));
          return;
        } catch (err) {
          if (err instanceof ApiRequestError && err.status === 202) continue;
          throw err;
        }
      }
      // Timed out — show nothing silently
      setFreshValues((s) => ({ ...s, [widget.id]: null }));
    } catch {
      // Silently suppress — no error card shown (test 8)
      setFreshValues((s) => ({ ...s, [widget.id]: null }));
    } finally {
      setChecking((s) => ({ ...s, [widget.id]: false }));
    }
  }

  return (
    <section
      className="w-full rounded-2xl glass-card p-5 relative overflow-hidden"
      aria-labelledby="saved-findings-title"
    >
      <div className="flex items-start justify-between gap-4 mb-4">
        <div className="flex items-start gap-2.5">
          <div className="p-2 rounded-xl bg-[var(--accent-blue)]/10 text-[var(--accent-blue)] border border-[var(--accent-blue)]/20">
            <LayoutGrid className="w-4 h-4" aria-hidden="true" />
          </div>
          <div>
            <h3 id="saved-findings-title" className="text-sm font-semibold text-white flex items-center gap-2">
              Saved findings
              <span className="text-[10px] px-2 py-0.5 rounded-full bg-[var(--accent-blue)]/15 text-[var(--accent-blue)] border border-[var(--accent-blue)]/30 font-medium">
                {pinnedWidgets.length}
              </span>
            </h3>
            <p className="text-[11px] text-[var(--text-muted)] mt-0.5">
              A running record of answers you&apos;ve chosen to keep. Add a note on why it mattered, and check back anytime to see what&apos;s changed.
            </p>
          </div>
        </div>
      </div>

      {pinnedWidgets.length === 0 ? (
        <div className="py-8 flex flex-col items-center justify-center border border-dashed border-white/10 rounded-xl bg-[var(--bg-surface)]/50 p-4 text-center">
          <div className="p-2.5 rounded-full bg-[var(--bg-elevated)] border border-white/10 mb-2">
            <Pin className="w-4 h-4 text-[var(--accent-blue)]" aria-hidden="true" />
          </div>
          <p className="text-xs text-[var(--text-secondary)] font-medium">No findings saved yet</p>
          <p className="text-[11px] text-[var(--text-muted)] mt-1 max-w-xs">
            Save an answer after asking a question to start building your record.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {pinnedWidgets.map((widget) => {
            const result = widget.result ?? null;
            const columns = result?.columns ?? [];
            const rows = result?.rows ?? [];
            const semantics = result?.semantic_columns ?? [];
            const chartData = result ? chartRows(result as StoredResult, columns) : [];

            // Use shared extractHeadline — same function as pin-time and check-now (test 9)
            const { value: headlineValue, label: headlineLabel } = extractHeadline(result);
            const metricIndex = semantics.findIndex((c) => c.role === "metric" || c.value_type === "number");
            const metricColumn = semantics[metricIndex >= 0 ? metricIndex : 1];

            const chartType = widget.chart_type === "line" ? "line" : "bar";
            const savedDate = formatSavedDate(widget.saved_at);
            const hasChart = chartData.length > 0;

            return (
              <article
                key={widget.id}
                className="p-4 rounded-xl bg-[var(--bg-surface)] border border-white/10 flex flex-col relative group hover:border-[var(--accent-blue)]/40 transition-colors"
              >
                {/* Card header */}
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="text-[10px] uppercase tracking-[0.16em] text-[var(--text-muted)] mb-1">
                      Saved finding
                    </p>
                    <h4 className="text-sm font-semibold text-white line-clamp-2">
                      {cleanTitle(widget.title)}
                    </h4>
                  </div>
                  {onRemoveWidget && (
                    <button
                      type="button"
                      onClick={() => onRemoveWidget(widget.id)}
                      className="p-2 rounded-lg text-[var(--text-muted)] hover:text-[var(--accent-rose)] hover:bg-[var(--accent-rose)]/10 border border-transparent hover:border-[var(--accent-rose)]/20 transition-colors touch-target"
                      title="Remove saved finding"
                      aria-label={`Remove ${cleanTitle(widget.title)}`}
                    >
                      <Trash2 className="w-3.5 h-3.5" aria-hidden="true" />
                    </button>
                  )}
                </div>

                {/* Headline value block / no-snapshot block */}
                {widget.data_status === "available" && headlineValue !== null && headlineValue !== undefined ? (
                  <div className="mt-3">
                    <div className="flex items-end justify-between gap-3">
                      <div>
                        <p className="text-[10px] text-[var(--text-muted)]">
                          {metricColumn?.display_name ?? widget.snapshot_headline_label}
                        </p>
                        <p className="text-2xl font-semibold tracking-tight text-white">
                          {formatResultValue(headlineValue, metricColumn)}
                        </p>
                      </div>
                      <span className="text-[10px] px-2 py-1 rounded-full border border-cyan-400/20 bg-cyan-400/10 text-cyan-300">
                        Saved snapshot
                      </span>
                    </div>

                    {freshValues[widget.id] &&
                      freshValues[widget.id]!.value !== null &&
                      widget.snapshot_headline_value != null && (
                        <DeltaBadge
                          previous={widget.snapshot_headline_value}
                          current={freshValues[widget.id]!.value!}
                        />
                      )}
                  </div>
                ) : (
                  <div className="mt-4 rounded-lg border border-white/10 bg-white/[0.02] px-3 py-3">
                    <p className="text-xs font-medium text-[var(--text-secondary)]">
                      This finding predates snapshot storage.
                    </p>
                    <p className="text-[11px] text-[var(--text-muted)] mt-1 mb-2">
                      Ask again to save a current version.
                    </p>
                    <button
                      type="button"
                      onClick={() =>
                        onRerunAnalysis?.(widget.original_question ?? cleanTitle(widget.title))
                      }
                      className="text-[11px] text-[var(--accent-blue)] hover:underline"
                    >
                      Ask again
                    </button>
                  </div>
                )}

                {/* Note editor */}
                {onUpdateNote && (
                  <NoteEditor
                    note={widget.note}
                    onSave={(value) => onUpdateNote(widget.id, value)}
                  />
                )}

                {/* Mini chart */}
                <div className="h-28 w-full mt-4 rounded-lg border border-white/5 bg-[var(--bg-base)]/70 p-2 flex items-center justify-center">
                  {hasChart ? (
                    <ResponsiveContainer width="100%" height="100%">
                      {chartType === "line" ? (
                        <LineChart data={chartData}>
                          <XAxis dataKey="name" stroke="#64748b" fontSize={10} tickLine={false} />
                          <YAxis
                            stroke="#64748b"
                            fontSize={10}
                            tickLine={false}
                            width={38}
                            tickFormatter={(value) => formatResultValue(value, metricColumn)}
                          />
                          <RechartsTooltip
                            formatter={(value) => [
                              formatResultValue(Number(value), metricColumn),
                              metricColumn?.display_name ?? "Value",
                            ]}
                            contentStyle={{ backgroundColor: "#10141c", borderRadius: "8px", border: "1px solid rgba(255,255,255,0.1)" }}
                          />
                          <Line type="monotone" dataKey="value" stroke="#38bdf8" strokeWidth={2} dot={{ r: 3, fill: "#38bdf8" }} />
                        </LineChart>
                      ) : (
                        <BarChart data={chartData}>
                          <XAxis dataKey="name" stroke="#64748b" fontSize={10} tickLine={false} />
                          <YAxis
                            stroke="#64748b"
                            fontSize={10}
                            tickLine={false}
                            width={38}
                            tickFormatter={(value) => formatResultValue(value, metricColumn)}
                          />
                          <RechartsTooltip
                            formatter={(value) => [
                              formatResultValue(Number(value), metricColumn),
                              metricColumn?.display_name ?? "Value",
                            ]}
                            contentStyle={{ backgroundColor: "#10141c", borderRadius: "8px", border: "1px solid rgba(255,255,255,0.1)" }}
                          />
                          <Bar dataKey="value" fill="#38bdf8" radius={[4, 4, 0, 0]} />
                        </BarChart>
                      )}
                    </ResponsiveContainer>
                  ) : (
                    <p className="text-xs text-[var(--text-muted)]">
                      {widget.data_status === "available"
                        ? "This result is best viewed as a table."
                        : "No visual preview available"}
                    </p>
                  )}
                </div>

                {/* Footer: saved date + check now */}
                <div className="mt-3 flex items-center justify-between">
                  <span className="text-[10px] text-[var(--text-muted)]">
                    Saved {formatSavedDate(widget.saved_at)}
                  </span>
                  {widget.data_status === "available" && (
                    <button
                      type="button"
                      onClick={() => handleCheckNow(widget)}
                      disabled={checking[widget.id]}
                      className="text-[11px] text-[var(--accent-blue)] hover:underline flex items-center gap-1 disabled:opacity-50"
                    >
                      <RotateCcw className="w-3 h-3" />{" "}
                      {checking[widget.id] ? "Checking…" : "Check now"}
                    </button>
                  )}
                </div>
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}
