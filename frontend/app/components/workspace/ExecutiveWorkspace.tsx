"use client";

import React from "react";
import { Pin, Trash2, LayoutGrid, BarChart2, TrendingUp, Table, Zap } from "lucide-react";
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
    if (mainMetric && dimension) return `${mainMetric.toUpperCase()} by ${dimension}`;
    if (mainMetric) return mainMetric.toUpperCase();
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
            const rowCount = rows.length || rawRes.row_count || 0;
            const cleanTitle = formatCleanTitle(widget.title);
            const chartType = widget.result?.chartType || widget.result?.chart_type || "bar";

            return (
              <div
                key={widget.id}
                className="p-5 rounded-2xl bg-gradient-to-b from-[var(--bg-surface)] to-[var(--bg-glass)] border border-[var(--border-glass)] shadow-lg flex flex-col justify-between relative group hover:border-[var(--accent-blue)]/40 transition-all duration-300"
              >
                {/* Header */}
                <div className="flex items-start justify-between gap-3 mb-4">
                  <div className="flex items-center gap-2">
                    <div className="p-1.5 rounded-lg bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
                      {chartType === "line" ? (
                        <TrendingUp className="w-4 h-4" />
                      ) : chartType === "table" ? (
                        <Table className="w-4 h-4" />
                      ) : (
                        <BarChart2 className="w-4 h-4" />
                      )}
                    </div>
                    <div>
                      <span className="text-[10px] font-mono text-indigo-400 uppercase tracking-widest block font-semibold">
                        PINNED EXECUTIVE METRIC
                      </span>
                      <h4 className="text-xs font-semibold text-[var(--text-primary)] capitalize line-clamp-1">
                        {cleanTitle}
                      </h4>
                    </div>
                  </div>

                  {onRemoveWidget && (
                    <button
                      type="button"
                      onClick={() => onRemoveWidget(widget.id)}
                      className="p-1.5 rounded-lg bg-rose-500/10 text-rose-400 hover:bg-rose-500/20 border border-rose-500/20 transition-colors opacity-80 hover:opacity-100"
                      title="Unpin Widget"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  )}
                </div>

                {/* Metric Summary Card */}
                <div className="p-4 rounded-xl bg-[var(--bg-elevated)] border border-[var(--border-glass)] my-2">
                  <div className="flex items-baseline justify-between mb-2">
                    <span className="text-[11px] text-[var(--text-muted)] font-medium">Dataset Summary</span>
                    <span className="text-xs font-mono font-bold text-[var(--accent-blue)] flex items-center gap-1">
                      <Zap className="w-3 h-3" />
                      {rowCount.toLocaleString()} Records
                    </span>
                  </div>

                  {/* Top Column Highlights */}
                  {cols.length > 0 && (
                    <div className="flex flex-wrap gap-1.5 mt-2">
                      {cols.slice(0, 3).map((col: string, idx: number) => (
                        <span
                          key={idx}
                          className="text-[10px] font-mono px-2 py-0.5 rounded-md bg-[var(--bg-surface)] text-[var(--text-secondary)] border border-[var(--border)] capitalize"
                        >
                          {col.replace(/_/g, " ")}
                        </span>
                      ))}
                      {cols.length > 3 && (
                        <span className="text-[10px] font-mono px-1.5 py-0.5 text-[var(--text-muted)]">
                          +{cols.length - 3} more
                        </span>
                      )}
                    </div>
                  )}
                </div>

                {/* Footer metadata */}
                <div className="mt-3 pt-3 border-t border-[var(--border-glass)] flex items-center justify-between text-[10px] text-[var(--text-muted)]">
                  <span className="font-mono">
                    Turn Ref: {(widget.result?.turnId || widget.result?.turn_id || widget.id).slice(0, 8)}
                  </span>
                  <span className="px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-medium">
                    Verified Metric
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
