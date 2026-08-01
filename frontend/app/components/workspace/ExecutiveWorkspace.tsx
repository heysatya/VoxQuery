"use client";

import React from "react";
import { Pin, Trash2, LayoutGrid, Sparkles } from "lucide-react";
import { ResponsiveContainer, BarChart, Bar, LineChart, Line, XAxis, YAxis, Tooltip as RechartsTooltip } from "recharts";
import { type LastResult } from "../../../lib/types";

type PinnedWidget = {
  id: string;
  title: string;
  created_at?: string;
  result: LastResult | any;
};

type ExecutiveWorkspaceProps = {
  pinnedWidgets?: PinnedWidget[];
  onRemoveWidget?: (id: string) => void;
};

function formatCleanTitle(rawTitle: string): string {
  if (!rawTitle) return "Executive Analytics Metric";
  if (rawTitle.includes("Trend:") || rawTitle.includes("by ")) {
    const parts = rawTitle.replace(/^Trend:\s*/i, "").split(/by\s+/i);
    const mainMetric = parts[0].split(",").map((s) => s.trim().replace(/_/g, " ")).filter((s) => !s.includes("id")).join(" & ");
    const dimension = parts[1] ? parts[1].trim().replace(/_/g, " ") : "";
    if (mainMetric && dimension) return `${mainMetric} by ${dimension}`;
    if (mainMetric) return mainMetric;
  }
  return rawTitle.replace(/_/g, " ");
}

export function ExecutiveWorkspace({
  pinnedWidgets = [],
  onRemoveWidget,
}: ExecutiveWorkspaceProps) {
  return (
    <div className="w-full rounded-2xl glass-card p-5 relative overflow-hidden">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2.5">
          <div className="p-2 rounded-xl bg-[var(--accent-blue)]/10 text-[var(--accent-blue)] border border-[var(--accent-blue)]/20">
            <LayoutGrid className="w-4 h-4" />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-white flex items-center gap-2">
              Saved metrics
              <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-[var(--accent-blue)]/15 text-[var(--accent-blue)] border border-[var(--accent-blue)]/30 font-medium">
                {pinnedWidgets.length} pinned
              </span>
            </h3>
            <p className="text-[11px] text-[var(--text-muted)] font-normal">Personal dashboard of saved analytical views</p>
          </div>
        </div>
      </div>

      {pinnedWidgets.length === 0 ? (
        <div className="py-8 flex flex-col items-center justify-center border border-dashed border-white/10 rounded-xl bg-[var(--bg-surface)]/50 p-4 text-center">
          <div className="p-2.5 rounded-full bg-[var(--bg-elevated)] border border-white/10 mb-2">
            <Pin className="w-4 h-4 text-[var(--accent-blue)]" />
          </div>
          <p className="text-xs text-[var(--text-secondary)] font-medium">Nothing pinned yet.</p>
          <p className="text-[11px] text-[var(--text-muted)] mt-0.5 max-w-xs font-normal">
            Pin any chart after asking a question to build your workspace dashboard.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {pinnedWidgets.map((widget) => {
            const rawRes = widget.result?.resultData?.result || widget.result?.result || {};
            const rows = rawRes.rows || [];
            const cols = rawRes.columns || [];
            const cleanTitle = formatCleanTitle(widget.title);
            const chartType = widget.result?.chartType || widget.result?.chart_type || "bar";

            let formattedChartData: any[] = [];
            if (rows.length > 0 && cols.length >= 2) {
              formattedChartData = rows.slice(0, 8).map((row: any[]) => {
                const labelVal = String(row[0] ?? "");
                const numVal = typeof row[1] === "number" ? row[1] : parseFloat(String(row[1] ?? 0)) || 0;
                return {
                  name: labelVal.length > 12 ? labelVal.slice(0, 10) + ".." : labelVal,
                  value: numVal,
                };
              });
            }

            return (
              <div
                key={widget.id}
                className="p-4 rounded-xl bg-[var(--bg-surface)] border border-white/10 flex flex-col justify-between relative group hover:border-[var(--accent-blue)]/40 transition-all duration-200"
              >
                <div className="flex items-start justify-between gap-3 mb-2">
                  <h4 className="text-xs font-semibold text-white capitalize line-clamp-1">
                    {cleanTitle}
                  </h4>

                  {onRemoveWidget && (
                    <button
                      type="button"
                      onClick={() => onRemoveWidget(widget.id)}
                      className="p-1 rounded-lg bg-[var(--accent-rose)]/10 text-[var(--accent-rose)] hover:bg-[var(--accent-rose)]/20 border border-[var(--accent-rose)]/20 transition-colors touch-target flex items-center justify-center"
                      title="Unpin Widget"
                      aria-label="Unpin widget"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  )}
                </div>

                <div className="h-32 w-full my-2 pt-1 bg-[var(--bg-base)]/80 rounded-lg border border-white/5 p-2 flex items-center justify-center">
                  {formattedChartData.length > 0 ? (
                    <ResponsiveContainer width="100%" height="100%">
                      {chartType === "line" ? (
                        <LineChart data={formattedChartData}>
                          <XAxis dataKey="name" stroke="#64748b" fontSize={10} tickLine={false} />
                          <YAxis stroke="#64748b" fontSize={10} tickLine={false} width={30} />
                          <RechartsTooltip
                            contentStyle={{ backgroundColor: "#10141c", borderRadius: "8px", border: "1px solid rgba(255,255,255,0.1)" }}
                            labelStyle={{ color: "#fff", fontSize: "11px" }}
                          />
                          <Line type="monotone" dataKey="value" stroke="#38bdf8" strokeWidth={2} dot={{ r: 3, fill: "#38bdf8" }} />
                        </LineChart>
                      ) : (
                        <BarChart data={formattedChartData}>
                          <XAxis dataKey="name" stroke="#64748b" fontSize={10} tickLine={false} />
                          <YAxis stroke="#64748b" fontSize={10} tickLine={false} width={30} />
                          <RechartsTooltip
                            contentStyle={{ backgroundColor: "#10141c", borderRadius: "8px", border: "1px solid rgba(255,255,255,0.1)" }}
                            labelStyle={{ color: "#fff", fontSize: "11px" }}
                          />
                          <Bar dataKey="value" fill="#38bdf8" radius={[4, 4, 0, 0]} />
                        </BarChart>
                      )}
                    </ResponsiveContainer>
                  ) : (
                    <div className="text-xs text-[var(--text-muted)] flex items-center justify-center h-full font-mono font-normal">
                      No data returned for this metric
                    </div>
                  )}
                </div>

                {(() => {
                  const pinDate = widget.created_at
                    ? new Date(widget.created_at).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })
                    : new Date().toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
                  return (
                    <div className="mt-2 pt-2 border-t border-white/5 flex items-center justify-between text-[10px] text-[var(--text-muted)]">
                      <span className="font-mono flex items-center gap-1 text-[var(--text-muted)] font-normal">
                        <Sparkles className="w-3 h-3 text-[var(--accent-blue)]" />
                        Ref: {(widget.result?.turnId || widget.result?.turn_id || widget.id).slice(0, 8)}
                      </span>
                      <span className="px-2 py-0.5 rounded bg-[var(--bg-elevated)] text-[var(--text-secondary)] border border-white/5 font-mono">
                        Snapshot from {pinDate}
                      </span>
                    </div>
                  );
                })()}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
