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
    <div className="w-full rounded-2xl bg-gradient-to-br from-[var(--bg-glass)] to-[var(--bg-surface)] border border-[var(--border-glass)] shadow-2xl p-6 backdrop-blur-xl relative overflow-hidden">
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-2.5">
          <div className="p-2.5 rounded-xl bg-gradient-to-br from-indigo-500/20 to-purple-500/20 text-indigo-400 border border-indigo-500/30 shadow-inner">
            <LayoutGrid className="w-5 h-5" />
          </div>
          <div>
            <h3 className="text-sm font-bold text-white flex items-center gap-2">
              Saved metrics
              <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-cyan-500/20 text-cyan-300 border border-cyan-400/30 font-semibold">
                {pinnedWidgets.length} pinned
              </span>
            </h3>
            <p className="text-[11px] text-slate-300 font-medium">Your personal dashboard of saved analytical views</p>
          </div>
        </div>
      </div>

      {pinnedWidgets.length === 0 ? (
        <div className="h-44 flex flex-col items-center justify-center border border-dashed border-slate-700/60 rounded-2xl bg-slate-900/60 p-6 text-center">
          <div className="p-3 rounded-full bg-slate-800 border border-slate-700 mb-3">
            <Pin className="w-5 h-5 text-cyan-400" />
          </div>
          <p className="text-xs text-slate-200 font-semibold">Nothing pinned yet.</p>
          <p className="text-[11px] text-slate-300 mt-1 max-w-sm">
            Pin any chart to build your own board.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
          {pinnedWidgets.map((widget) => {
            const rawRes = widget.result?.resultData?.result || widget.result?.result || {};
            const rows = rawRes.rows || [];
            const cols = rawRes.columns || [];
            const cleanTitle = formatCleanTitle(widget.title);
            const chartType = widget.result?.chartType || widget.result?.chart_type || "bar";

            // Prepare chart data if rows exist
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
                className="p-5 rounded-2xl bg-gradient-to-b from-slate-900 to-slate-950 border border-slate-700/60 shadow-xl flex flex-col justify-between relative group hover:border-cyan-400/50 transition-all duration-300"
              >
                {/* Header Row */}
                <div className="flex items-start justify-between gap-3 mb-3">
                  <h4 className="text-xs font-bold text-white capitalize line-clamp-1">
                    {cleanTitle}
                  </h4>

                  {onRemoveWidget && (
                    <button
                      type="button"
                      onClick={() => onRemoveWidget(widget.id)}
                      className="p-1.5 rounded-lg bg-rose-500/10 text-rose-400 hover:bg-rose-500/20 border border-rose-500/20 transition-colors"
                      title="Unpin Widget"
                      aria-label="Unpin widget"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  )}
                </div>

                {/* Embedded Recharts Mini Graphic or Honest Empty State */}
                <div className="h-36 w-full my-2 pt-2 bg-slate-950/70 rounded-xl border border-slate-800 p-2 flex items-center justify-center">
                  {formattedChartData.length > 0 ? (
                    <ResponsiveContainer width="100%" height="100%">
                      {chartType === "line" ? (
                        <LineChart data={formattedChartData}>
                          <XAxis dataKey="name" stroke="#94a3b8" fontSize={10} tickLine={false} />
                          <YAxis stroke="#94a3b8" fontSize={10} tickLine={false} width={30} />
                          <RechartsTooltip
                            contentStyle={{ backgroundColor: "#0f172a", borderRadius: "8px", border: "1px solid #334155" }}
                            labelStyle={{ color: "#fff", fontSize: "11px" }}
                          />
                          <Line type="monotone" dataKey="value" stroke="#38bdf8" strokeWidth={2} dot={{ r: 3, fill: "#38bdf8" }} />
                        </LineChart>
                      ) : (
                        <BarChart data={formattedChartData}>
                          <XAxis dataKey="name" stroke="#94a3b8" fontSize={10} tickLine={false} />
                          <YAxis stroke="#94a3b8" fontSize={10} tickLine={false} width={30} />
                          <RechartsTooltip
                            contentStyle={{ backgroundColor: "#0f172a", borderRadius: "8px", border: "1px solid #334155" }}
                            labelStyle={{ color: "#fff", fontSize: "11px" }}
                          />
                          <Bar dataKey="value" fill="#38bdf8" radius={[4, 4, 0, 0]} />
                        </BarChart>
                      )}
                    </ResponsiveContainer>
                  ) : (
                    <div className="text-xs text-slate-400 flex items-center justify-center h-full font-mono font-medium">
                      No data returned for this metric
                    </div>
                  )}
                </div>

                {/* Footer Metadata Bar */}
                {(() => {
                  const pinDate = widget.created_at
                    ? new Date(widget.created_at).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })
                    : new Date().toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
                  return (
                    <div className="mt-2 pt-2 border-t border-slate-800/60 flex items-center justify-between text-[10px] text-slate-300">
                      <span className="font-mono flex items-center gap-1 text-slate-300 font-medium">
                        <Sparkles className="w-3 h-3 text-cyan-400" />
                        Ref: {(widget.result?.turnId || widget.result?.turn_id || widget.id).slice(0, 8)}
                      </span>
                      <span className="px-2 py-0.5 rounded bg-slate-800 text-slate-200 border border-slate-700 font-mono font-medium">
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
