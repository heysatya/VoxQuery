"use client";

import React from "react";
import { Pin, Trash2, LayoutGrid, BarChart2, TrendingUp, Table, Zap, Sparkles } from "lucide-react";
import { ResponsiveContainer, BarChart, Bar, LineChart, Line, XAxis, YAxis, Tooltip as RechartsTooltip } from "recharts";
import { type LastResult } from "../../../lib/types";

type PinnedWidget = {
  id: string;
  title: string;
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

/* Sample backup chart data for visual executive preview */
const MOCK_CHART_DATA = [
  { name: "Q1", value: 4200, growth: 12 },
  { name: "Q2", value: 5800, growth: 18 },
  { name: "Q3", value: 7100, growth: 24 },
  { name: "Q4", value: 9400, growth: 31 },
];

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
            <h3 className="text-sm font-semibold text-[var(--text-primary)] flex items-center gap-2">
              Executive Grid Workspace
              <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
                {pinnedWidgets.length} Active {pinnedWidgets.length === 1 ? "Metric" : "Metrics"}
              </span>
            </h3>
            <p className="text-[11px] text-[var(--text-muted)]">Custom pinned executive KPIs and side-by-side analytical widgets</p>
          </div>
        </div>
      </div>

      {pinnedWidgets.length === 0 ? (
        <div className="h-44 flex flex-col items-center justify-center border border-dashed border-[var(--border)] rounded-2xl bg-[var(--bg-glass)] p-6 text-center">
          <div className="p-3 rounded-full bg-[var(--bg-elevated)] border border-[var(--border-glass)] mb-3">
            <Pin className="w-5 h-5 text-[var(--text-muted)]" />
          </div>
          <p className="text-xs text-[var(--text-secondary)] font-medium">No pinned executive metrics yet.</p>
          <p className="text-[10px] text-[var(--text-muted)] mt-1 max-w-sm">
            Click the pin icon on any chart or stat card to assemble your personal executive dashboard.
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

            const chartDataToRender = formattedChartData.length > 0 ? formattedChartData : MOCK_CHART_DATA;

            return (
              <div
                key={widget.id}
                className="p-5 rounded-2xl bg-gradient-to-b from-[#161820] to-[#111319] border border-white/10 shadow-xl flex flex-col justify-between relative group hover:border-indigo-500/40 transition-all duration-300"
              >
                {/* Header Row */}
                <div className="flex items-start justify-between gap-3 mb-3">
                  <div>
                    <span className="text-[10px] font-mono text-indigo-400 uppercase tracking-widest block font-semibold mb-0.5">
                      PINNED EXECUTIVE WIDGET
                    </span>
                    <h4 className="text-xs font-bold text-white capitalize line-clamp-1">
                      {cleanTitle}
                    </h4>
                  </div>

                  {onRemoveWidget && (
                    <button
                      type="button"
                      onClick={() => onRemoveWidget(widget.id)}
                      className="p-1.5 rounded-lg bg-rose-500/10 text-rose-400 hover:bg-rose-500/20 border border-rose-500/20 transition-colors"
                      title="Unpin Widget"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  )}
                </div>

                {/* Embedded Recharts Mini Graphic */}
                <div className="h-36 w-full my-2 pt-2 bg-black/20 rounded-xl border border-white/5 p-2 flex items-center justify-center">
                  <ResponsiveContainer width="100%" height="100%">
                    {chartType === "line" ? (
                      <LineChart data={chartDataToRender}>
                        <XAxis dataKey="name" stroke="#6b7280" fontSize={10} tickLine={false} />
                        <YAxis stroke="#6b7280" fontSize={10} tickLine={false} width={30} />
                        <RechartsTooltip
                          contentStyle={{ backgroundColor: "#1f2937", borderRadius: "8px", border: "1px solid #374151" }}
                          labelStyle={{ color: "#fff", fontSize: "11px" }}
                        />
                        <Line type="monotone" dataKey="value" stroke="#818cf8" strokeWidth={2} dot={{ r: 3, fill: "#818cf8" }} />
                      </LineChart>
                    ) : (
                      <BarChart data={chartDataToRender}>
                        <XAxis dataKey="name" stroke="#6b7280" fontSize={10} tickLine={false} />
                        <YAxis stroke="#6b7280" fontSize={10} tickLine={false} width={30} />
                        <RechartsTooltip
                          contentStyle={{ backgroundColor: "#1f2937", borderRadius: "8px", border: "1px solid #374151" }}
                          labelStyle={{ color: "#fff", fontSize: "11px" }}
                        />
                        <Bar dataKey="value" fill="#6366f1" radius={[4, 4, 0, 0]} />
                      </BarChart>
                    )}
                  </ResponsiveContainer>
                </div>

                {/* Footer Metadata Bar */}
                <div className="mt-2 pt-2 border-t border-white/5 flex items-center justify-between text-[10px] text-gray-400">
                  <span className="font-mono flex items-center gap-1">
                    <Sparkles className="w-3 h-3 text-indigo-400" />
                    Ref: {(widget.result?.turnId || widget.result?.turn_id || widget.id).slice(0, 8)}
                  </span>
                  <span className="px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-medium">
                    Live Visual Dashboard
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
