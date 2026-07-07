"use client";

import React, { useState } from "react";
import { motion } from "framer-motion";
import { ThumbsDown, Code, Download, ChevronDown } from "lucide-react";
import { cn } from "../../../lib/utils";
import type { LastResult } from "../../../lib/types";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip as RechartsTooltip, ResponsiveContainer,
  LineChart, Line
} from "recharts";

/* ── Chart Renderer ────────────────────────────────────────────── */

function ChartRenderer({ type, data }: { type: string; data: { columns: string[]; rows: any[][] } }) {
  if (!data.columns || !data.rows || data.rows.length === 0) {
    return <div className="p-8 text-center text-[var(--text-muted)]">No data to display</div>;
  }

  const isStat = type === "stat" || (data.columns.length === 1 && data.rows.length === 1);
  if (isStat) {
    return (
      <div className="flex flex-col items-center justify-center py-12">
        <span className="text-xs font-semibold text-[var(--text-muted)] uppercase tracking-widest mb-2">
          {data.columns[0]}
        </span>
        <span className="text-5xl md:text-6xl font-bold bg-gradient-to-r from-[var(--chart-1)] to-[var(--chart-2)] bg-clip-text text-transparent">
          {String(data.rows[0][0])}
        </span>
      </div>
    );
  }

  if (type === "table") {
    return (
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-[var(--border)]">
            <tr>
              {data.columns.map((col, i) => (
                <th key={i} className="px-4 py-3 font-semibold text-[var(--text-secondary)] whitespace-nowrap text-xs uppercase tracking-wider">{col}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-[var(--border)]">
            {data.rows.map((row, i) => (
              <tr key={i} className="hover:bg-white/[0.02] transition-colors">
                {row.map((cell, j) => (
                  <td key={j} className="px-4 py-3 text-[var(--text-primary)] whitespace-nowrap">{String(cell)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  const chartData = data.rows.map(row => {
    const obj: any = {};
    data.columns.forEach((col, i) => {
      obj[col] = typeof row[i] === "number" ? row[i] : String(row[i]);
    });
    return obj;
  });

  const xKey = data.columns[0];
  const yKeys = data.columns.slice(1);
  const colors = ["#6366F1", "#8B5CF6", "#EC4899"];

  const tooltipStyle = {
    backgroundColor: "#1E2030",
    border: "1px solid rgba(255,255,255,0.06)",
    borderRadius: "12px",
    boxShadow: "0 8px 32px rgba(0,0,0,0.4)",
    color: "#F0F0F5",
    fontSize: "13px",
  };

  if (type === "line") {
    return (
      <div className="h-72 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={chartData} margin={{ top: 20, right: 20, left: 0, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="rgba(255,255,255,0.04)" />
            <XAxis dataKey={xKey} axisLine={false} tickLine={false} tick={{ fill: "#8B8FA3", fontSize: 12 }} />
            <YAxis axisLine={false} tickLine={false} tick={{ fill: "#8B8FA3", fontSize: 12 }} />
            <RechartsTooltip contentStyle={tooltipStyle} />
            {yKeys.map((key, i) => (
              <Line key={key} type="monotone" dataKey={key} stroke={colors[i % 3]} strokeWidth={2.5} dot={{ r: 3, strokeWidth: 2, fill: "#0C0D11" }} activeDot={{ r: 5 }} />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
    );
  }

  return (
    <div className="h-72 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={chartData} margin={{ top: 20, right: 20, left: 0, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="rgba(255,255,255,0.04)" />
          <XAxis dataKey={xKey} axisLine={false} tickLine={false} tick={{ fill: "#8B8FA3", fontSize: 12 }} />
          <YAxis axisLine={false} tickLine={false} tick={{ fill: "#8B8FA3", fontSize: 12 }} />
          <RechartsTooltip cursor={{ fill: "rgba(255,255,255,0.03)" }} contentStyle={tooltipStyle} />
          {yKeys.map((key, i) => (
            <Bar key={key} dataKey={key} fill={colors[i % 3]} radius={[6, 6, 0, 0]} />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

/* ── DataGlassPanel ────────────────────────────────────────────── */

type DataGlassPanelProps = {
  result: LastResult;
  feedbackSubmitted: boolean;
  isMuted: boolean;
  onFeedback: () => void | Promise<void>;
  onMute: () => void;
  onUnmute: () => void;
};

export function DataGlassPanel({
  result,
  feedbackSubmitted,
  onFeedback,
}: DataGlassPanelProps) {
  const [showSql, setShowSql] = useState(false);
  const [userChartOverride, setUserChartOverride] = useState<string | null>(null);

  const confidenceDot =
    result.confidenceTier === "High" ? "bg-[var(--accent-green)]" :
    result.confidenceTier === "Medium" ? "bg-[var(--accent-amber)]" :
    "bg-[var(--accent-rose)]";

  function downloadCSV() {
    const { columns, rows } = result.resultData.result;
    const csvContent = [
      columns.join(","),
      ...rows.map((row) =>
        row.map((v) => typeof v === "string" ? `"${v.replace(/"/g, '""')}"` : String(v)).join(",")
      )
    ].join("\\n");
    const blob = new Blob([csvContent], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "voxquery_export.csv";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, delay: 0.3 }}
      className="glass-card p-6 md:p-8"
    >
      {/* Medium confidence caveat */}
      {result.confidenceTier === "Medium" && (
        <div className="mb-6 px-4 py-3 rounded-xl bg-[var(--accent-amber)]/10 border border-[var(--accent-amber)]/20 text-[var(--accent-amber)] text-sm">
          I'm moderately confident — the query joined tables I'm less familiar with. You may want to review the SQL below.
        </div>
      )}

      {/* Chart */}
      <ChartRenderer
        type={userChartOverride ?? result.chartType}
        data={result.resultData.result}
      />

      {/* Trust & Actions Bar */}
      <div className="mt-6 pt-5 border-t border-[var(--border)] flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-4 text-sm text-[var(--text-secondary)]">
          {/* Confidence */}
          <div className="flex items-center gap-2">
            <span className={cn("w-2 h-2 rounded-full", confidenceDot)} />
            <span>{result.confidenceTier} confidence</span>
          </div>
          {/* Chart rationale */}
          {result.chartRationale && (
            <span className="hidden md:inline text-[var(--text-muted)]">· {result.chartRationale}</span>
          )}
        </div>

        <div className="flex items-center gap-1">
          {/* Chart type override */}
          <select
            aria-label="Chart Type"
            value={userChartOverride ?? result.chartType}
            onChange={(e) => setUserChartOverride(e.target.value)}
            className="mr-2 bg-transparent border border-[var(--border)] rounded-lg py-1.5 px-2 text-xs text-[var(--text-secondary)] focus:outline-none focus:ring-1 focus:ring-[var(--accent-blue)] cursor-pointer"
          >
            <option value="bar">Bar</option>
            <option value="line">Line</option>
            <option value="table">Table</option>
            <option value="stat">Stat</option>
          </select>

          {/* Download CSV */}
          <button type="button" onClick={downloadCSV} className="p-2 text-[var(--text-muted)] hover:text-[var(--accent-blue)] rounded-lg transition-colors" title="Download CSV">
            <Download className="h-4 w-4" />
          </button>

          {/* Feedback */}
          <button
            type="button"
            onClick={onFeedback}
            className={cn(
              "p-2 rounded-lg transition-colors",
              feedbackSubmitted ? "text-[var(--accent-rose)] cursor-default" : "text-[var(--text-muted)] hover:text-[var(--accent-rose)]"
            )}
            title={feedbackSubmitted ? "Feedback recorded" : "Flag this result"}
          >
            <ThumbsDown className={cn("h-4 w-4", feedbackSubmitted && "fill-current")} />
          </button>
        </div>
      </div>

      {/* View SQL — collapsed by default */}
      <div className="mt-4">
        <button
          type="button"
          onClick={() => setShowSql(!showSql)}
          className="flex items-center gap-2 text-xs text-[var(--text-muted)] hover:text-[var(--text-secondary)] transition-colors"
        >
          <Code className="h-3.5 w-3.5" />
          <span>{showSql ? "Hide SQL" : "View generated SQL"}</span>
          <ChevronDown className={cn("h-3 w-3 transition-transform", showSql && "rotate-180")} />
        </button>

        {showSql && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            className="mt-3 p-4 bg-[var(--bg-base)] rounded-xl overflow-x-auto border border-[var(--border)]"
          >
            <pre className="text-sm text-[var(--chart-2)] font-mono leading-relaxed">
              {result.resultData.generated_sql}
            </pre>
          </motion.div>
        )}
      </div>
    </motion.div>
  );
}
