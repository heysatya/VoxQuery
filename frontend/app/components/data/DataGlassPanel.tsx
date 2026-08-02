"use client";

import React, { useState } from "react";
import { motion } from "framer-motion";
import { ThumbsDown, ThumbsUp, Code, Download, ChevronDown, Link, Printer, Pin } from "lucide-react";
import { format as formatSql } from "sql-formatter";
import { cn } from "../../../lib/utils";
import type { LastResult } from "../../../lib/types";
import {
  chartRationaleFor,
  deriveCaveatText,
  displayNameForColumn,
  formatResultValue,
  resultRowSummary,
  selectedChartType,
  semanticColumns,
  type ChartType,
  type ResultCell,
  validChartOptions
} from "../../../lib/resultSemantics";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip as RechartsTooltip, ResponsiveContainer,
  LineChart, Line
} from "recharts";
import { TrustPanel } from "./TrustPanel";
import { triggerPdfExport } from "../../../lib/pdfExporter";
import { createShareLink } from "../../../lib/api";

/* -- Chart Renderer ---------------------------------------------- */

function ChartRenderer({ type, result, onDrillDown }: { type: ChartType; result: LastResult["resultData"]; onDrillDown?: (query: string) => void }) {
  const data = result.result;
  const columnSemantics = semanticColumns(result);

  const columnSemanticsMap = React.useMemo(() => {
    const map: Record<string, typeof columnSemantics[number]> = {};
    columnSemantics.forEach((col) => {
      map[col.name] = col;
    });
    return map;
  }, [columnSemantics]);

  const xKey = data.columns ? data.columns[0] : "";
  const yKeys = data.columns ? data.columns.slice(1) : [];

  const chartData = React.useMemo(() => {
    if (!data.columns || !data.rows) return [];
    return data.rows.map(row => {
      const obj: Record<string, ResultCell> = {};
      data.columns.forEach((col, i) => {
        obj[col] = row[i];
      });
      return obj;
    });
  }, [data.columns, data.rows]);

  // Z-score statistical outlier detection
  const outlierIndexes = React.useMemo(() => {
    if (!yKeys || yKeys.length === 0) return new Set<number>();
    const values = chartData.map((row) => {
      const v = row[yKeys[0]];
      return typeof v === "number" ? v : parseFloat(String(v)) || 0;
    });
    if (values.length < 3) return new Set<number>();
    const mean = values.reduce((a, b) => a + b, 0) / values.length;
    const variance = values.reduce((sum, val) => sum + Math.pow(val - mean, 2), 0) / values.length;
    const stdDev = Math.sqrt(variance);
    if (stdDev === 0) return new Set<number>();
    const outliers = new Set<number>();
    values.forEach((v, idx) => {
      if (Math.abs(v - mean) / stdDev > 1.5) {
        outliers.add(idx);
      }
    });
    return outliers;
  }, [chartData, yKeys]);

  if (!data.columns || !data.rows || data.rows.length === 0) {
    return <div className="p-8 text-center text-[var(--text-muted)]">No data to display</div>;
  }

  const isStat = type === "stat" || (data.columns.length === 1 && data.rows.length === 1);
  if (isStat) {
    return (
      <div className="flex flex-col items-center justify-center py-12">
        <span className="text-xs font-semibold text-[var(--text-muted)] uppercase tracking-widest mb-2">
          {displayNameForColumn(result, data.columns[0])}
        </span>
        <span className="text-5xl md:text-6xl font-bold bg-gradient-to-r from-[var(--chart-1)] to-[var(--chart-2)] bg-clip-text text-transparent">
          {formatResultValue(data.rows[0][0], columnSemantics[0])}
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
                <th key={i} className="px-4 py-3 font-semibold text-[var(--text-secondary)] whitespace-nowrap text-xs uppercase tracking-wider">{displayNameForColumn(result, col)}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-[var(--border)]">
            {data.rows.map((row, i) => (
              <tr key={i} className="hover:bg-white/[0.02] transition-colors">
                {row.map((cell, j) => (
                  <td key={j} className="px-4 py-3 text-[var(--text-primary)] whitespace-nowrap">{formatResultValue(cell, columnSemantics[j])}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  const yCol = columnSemantics.length > 1 ? columnSemantics[1] : undefined;

  const formatXTick = (val: any) => {
    if (val === null || val === undefined) return "";
    const str = String(val);
    if (/^\d{4}-\d{2}-\d{2}/.test(str)) {
      const datePart = str.substring(0, 10);
      const [year, month, day] = datePart.split("-").map(Number);
      const date = new Date(Date.UTC(year, month - 1, day));
      if (!isNaN(date.getTime())) {
        if (day === 1) {
          return date.toLocaleDateString("en-US", { month: "short", year: "numeric", timeZone: "UTC" });
        }
        return date.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });
      }
      return datePart;
    }
    if (typeof val === "string" && val.length > 20) {
      return val.slice(0, 18) + "…";
    }
    return String(val);
  };

  const formatYTick = (val: any) => {
    if (typeof val !== "number") return String(val ?? "");
    if (yCol?.format === "percentage") {
      return new Intl.NumberFormat("en-US", { style: "percent", maximumFractionDigits: 1, notation: "compact" }).format(val);
    }
    if ((yCol?.format === "compact currency" || yCol?.format === "full currency") && yCol?.unit) {
      return new Intl.NumberFormat("en-US", { style: "currency", currency: yCol.unit, notation: "compact" }).format(val);
    }
    return new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(val);
  };

  const colors = ["#6366F1", "#8B5CF6", "#EC4899"];

  const tooltipStyle = {
    backgroundColor: "#1E2030",
    border: "1px solid rgba(255,255,255,0.06)",
    borderRadius: "12px",
    boxShadow: "0 8px 32px rgba(0,0,0,0.4)",
    color: "#F0F0F5",
    fontSize: "13px",
  };

  const handleChartClick = (data: any) => {
    if (!onDrillDown || !data || !data.activeLabel) return;
    onDrillDown(`Tell me more about ${data.activeLabel}`);
  };

  if (type === "line") {
    return (
      <div className="h-72 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={chartData} margin={{ top: 20, right: 25, left: 15, bottom: 20 }} onClick={handleChartClick} style={{ cursor: onDrillDown ? "pointer" : "default" }}>
            <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="rgba(255,255,255,0.04)" />
            <XAxis dataKey={xKey} axisLine={false} tickLine={false} tickFormatter={formatXTick} tick={{ fill: "#8B8FA3", fontSize: 12 }} dy={8} />
            <YAxis axisLine={false} tickLine={false} tickFormatter={formatYTick} width={55} tick={{ fill: "#8B8FA3", fontSize: 12 }} />
            <RechartsTooltip
              contentStyle={tooltipStyle}
              labelFormatter={(label) => formatXTick(label)}
              formatter={(value: any, name: any) => [
                formatResultValue(value, columnSemanticsMap[String(name)]),
                displayNameForColumn(result, String(name))
              ]}
            />
            {yKeys.map((key, i) => (
              <Line
                key={key}
                type="monotone"
                dataKey={key}
                stroke={colors[i % 3]}
                strokeWidth={2.5}
                dot={(props: any) => {
                  const { cx, cy, index } = props;
                  const isAnomaly = outlierIndexes.has(index);
                  if (isAnomaly) {
                    return (
                      <g key={index}>
                        <circle cx={cx} cy={cy} r={8} fill="#EF4444" opacity={0.3} className="animate-pulse" />
                        <circle cx={cx} cy={cy} r={4} fill="#EF4444" stroke="#ffffff" strokeWidth={1.5} />
                      </g>
                    );
                  }
                  return <circle key={index} cx={cx} cy={cy} r={3} fill="#0C0D11" stroke={colors[i % 3]} strokeWidth={2} />;
                }}
                activeDot={{ r: 6 }}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
    );
  }

  return (
    <div className="h-72 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={chartData} margin={{ top: 20, right: 25, left: 15, bottom: 20 }} onClick={handleChartClick} style={{ cursor: onDrillDown ? "pointer" : "default" }}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="rgba(255,255,255,0.04)" />
          <XAxis dataKey={xKey} axisLine={false} tickLine={false} tickFormatter={formatXTick} tick={{ fill: "#8B8FA3", fontSize: 12 }} dy={8} />
          <YAxis axisLine={false} tickLine={false} tickFormatter={formatYTick} width={55} tick={{ fill: "#8B8FA3", fontSize: 12 }} />
          <RechartsTooltip
            cursor={{ fill: "rgba(255,255,255,0.03)" }}
            contentStyle={tooltipStyle}
            labelFormatter={(label) => formatXTick(label)}
            formatter={(value: any, name: any) => [
              formatResultValue(value, columnSemanticsMap[String(name)]),
              displayNameForColumn(result, String(name))
            ]}
          />
          {yKeys.map((key, i) => (
            <Bar key={key} dataKey={key} fill={colors[i % 3]} radius={[6, 6, 0, 0]}>
              {chartData.map((entry, index) => {
                const isAnomaly = outlierIndexes.has(index);
                return (
                  <React.Fragment key={`cell-${index}`}>
                    {isAnomaly ? (
                      // Glowing Red/Rose for Anomaly bars
                      <rect fill="url(#anomaly-grad)" />
                    ) : (
                      <rect fill={colors[i % 3]} />
                    )}
                  </React.Fragment>
                );
              })}
            </Bar>
          ))}
          <defs>
            <linearGradient id="anomaly-grad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#F43F5E" />
              <stop offset="100%" stopColor="#BE123C" />
            </linearGradient>
          </defs>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

/* ── DataGlassPanel ────────────────────────────────────────────── */

type DataGlassPanelProps = {
  result: LastResult;
  feedbackRating: -1 | 1 | null;
  onFeedback: (rating: -1 | 1) => void | Promise<void>;
  onDrillDown?: (query: string) => void;
  onDrilldownOpen?: (turnId: string) => void;
  onPin?: (result: LastResult) => void;
};

export function DataGlassPanel({
  result,
  feedbackRating,
  onFeedback,
  onDrillDown,
  onDrilldownOpen,
  onPin,
}: DataGlassPanelProps) {
  const [showSql, setShowSql] = useState(false);
  const [userChartOverride, setUserChartOverride] = useState<string | null>(null);
  const chartOptions = validChartOptions(result.resultData);
  const chartType = selectedChartType(result.resultData, userChartOverride);
  const chartRationale = chartRationaleFor(result.resultData, chartType);
  const rowSummary = resultRowSummary(result.resultData);

  // 4.2 Evidence-derived caveat — not hardcoded
  const caveatText = deriveCaveatText(result.resultData);

  function downloadCSV() {
    const { columns, rows } = result.resultData.result;
    const formatHeader = (v: string) => {
      const str = String(v);
      if (str.includes('"') || str.includes(",") || str.includes("\n") || str.includes("\r")) {
        return `"${str.replace(/"/g, '""')}"`;
      }
      return str;
    };
    const formatCell = (v: ResultCell | undefined) => {
      if (v === null || v === undefined) return "";
      if (typeof v === "string") {
        return `"${v.replace(/"/g, '""')}"`;
      }
      const str = String(v);
      if (str.includes('"') || str.includes(",") || str.includes("\n") || str.includes("\r")) {
        return `"${str.replace(/"/g, '""')}"`;
      }
      return str;
    };
    const csvContent = [
      columns.map(formatHeader).join(","),
      ...rows.map((row) => row.map(formatCell).join(","))
    ].join("\n");
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

  const [copiedLink, setCopiedLink] = useState(false);
  async function copyPermalink() {
    try {
      const shareRes = await createShareLink({ turn_id: result.turnId, ttl_hours: 168 });
      if (shareRes?.url) {
        await navigator.clipboard.writeText(shareRes.url);
        setCopiedLink(true);
        setTimeout(() => setCopiedLink(false), 2000);
        return;
      }
    } catch (err) {
      console.warn("Share link creation error, falling back to permalink", err);
    }
    const url = new URL(window.location.href);
    url.searchParams.set("share", result.turnId);
    navigator.clipboard.writeText(url.toString()).then(() => {
      setCopiedLink(true);
      setTimeout(() => setCopiedLink(false), 2000);
    });
  }

  function exportToPDF() {
    triggerPdfExport(
      "VoxQuery Executive Briefing Report",
      result.resultData.tts_text,
      []
    );
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, delay: 0.3 }}
      className="glass-card p-6 md:p-8"
    >
      {/* 4.2 Evidence-derived caveat — only shown for Medium/Low, derived from backend */}
      {caveatText && (
        <div className="mb-6 px-4 py-3 rounded-xl bg-[var(--accent-amber)]/10 border border-[var(--accent-amber)]/20 text-[var(--accent-amber)] text-sm">
          {caveatText}
        </div>
      )}

      {result.resultData.warnings.map((warning) => (
        <div
          key={warning.code}
          className="mb-6 px-4 py-3 rounded-xl bg-[var(--accent-amber)]/10 border border-[var(--accent-amber)]/20 text-[var(--accent-amber)] text-sm"
        >
          {warning.message}
        </div>
      ))}

      {/* Chart */}
      <div className="sr-only">
        Chart data alternative: {result.resultData.result.columns.join(", ")}; {rowSummary}.
      </div>
      <ChartRenderer
        type={chartType}
        result={result.resultData}
        onDrillDown={onDrillDown}
      />

      {/* Actions bar */}
      <div className="mt-6 pt-5 border-t border-[var(--border)] flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-4 text-sm text-[var(--text-secondary)]">
          {/* Chart rationale */}
          {chartRationale && (
            <span className="hidden md:inline text-[var(--text-muted)] text-xs">{chartRationale}</span>
          )}
        </div>

        <div className="flex items-center gap-1">
          {/* Chart type override */}
          <select
            aria-label="Chart Type"
            value={chartType}
            onChange={(e) => setUserChartOverride(e.target.value)}
            className="mr-2 bg-transparent border border-[var(--border)] rounded-lg py-1.5 px-2 text-xs text-[var(--text-secondary)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-blue)] cursor-pointer"
          >
            {chartOptions.map((option) => (
              <option key={option.value} value={option.value}>{option.label}</option>
            ))}
          </select>

          {/* Drilldown */}
          {onDrilldownOpen && (
            <button
              type="button"
              onClick={() => onDrilldownOpen(result.turnId)}
              className="p-2 text-[var(--text-muted)] hover:text-[var(--accent-blue)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent-blue)] rounded-lg transition-colors"
              title="Drilldown Raw Data"
            >
              <Code className="h-4 w-4" />
            </button>
          )}

          {/* Pin to Workspace */}
          {onPin && (
            <button
              type="button"
              onClick={() => onPin(result)}
              className="p-2 text-[var(--text-muted)] hover:text-[var(--accent-blue)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent-blue)] rounded-lg transition-colors"
              title="Pin to Workspace"
            >
              <Pin className="h-4 w-4" />
            </button>
          )}

          {/* Download CSV */}
          <button type="button" onClick={downloadCSV} className="p-2 text-[var(--text-muted)] hover:text-[var(--accent-blue)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent-blue)] rounded-lg transition-colors" title="Download CSV">
            <Download className="h-4 w-4" />
          </button>

          {/* Export PDF */}
          <button type="button" onClick={exportToPDF} className="p-2 text-[var(--text-muted)] hover:text-[var(--accent-blue)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent-blue)] rounded-lg transition-colors" title="Export to PDF">
            <Printer className="h-4 w-4" />
          </button>

          {/* Share Permalink */}
          <button type="button" onClick={copyPermalink} className="p-2 text-[var(--text-muted)] hover:text-[var(--accent-blue)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent-blue)] rounded-lg transition-colors" title={copiedLink ? "Link copied!" : "Copy permalink"}>
            <Link className={cn("h-4 w-4", copiedLink && "text-[var(--accent-green)]")} />
          </button>

          {/* Feedback */}
          <button
            type="button"
            onClick={() => onFeedback(1)}
            className={cn(
              "p-2 rounded-lg transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent-blue)]",
              feedbackRating === 1 ? "text-[var(--accent-green)]" : "text-[var(--text-muted)] hover:text-[var(--accent-green)]"
            )}
            title={feedbackRating === 1 ? "Feedback recorded" : "Mark helpful"}
          >
            <ThumbsUp className={cn("h-4 w-4", feedbackRating === 1 && "fill-current")} />
          </button>
          <button
            type="button"
            onClick={() => onFeedback(-1)}
            className={cn(
              "p-2 rounded-lg transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent-blue)]",
              feedbackRating === -1 ? "text-[var(--accent-rose)]" : "text-[var(--text-muted)] hover:text-[var(--accent-rose)]"
            )}
            title={feedbackRating === -1 ? "Feedback recorded" : "Flag this result"}
          >
            <ThumbsDown className={cn("h-4 w-4", feedbackRating === -1 && "fill-current")} />
          </button>
        </div>
      </div>

      {/* 4.1 Trust Panel — full expandable section */}
      <div className="mt-4">
        <TrustPanel result={result} />
      </div>

      {/* View SQL — collapsed by default */}
      <div className="mt-4">
        <button
          type="button"
          onClick={() => setShowSql(!showSql)}
          className="flex items-center gap-2 text-xs text-[var(--text-muted)] hover:text-[var(--text-secondary)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent-blue)] transition-colors"
        >
          <Code className="h-3.5 w-3.5" />
          <span>{showSql ? "Hide SQL" : "View generated SQL"}</span>
          <ChevronDown className={cn("h-3 w-3 transition-transform", showSql && "rotate-180")} />
        </button>

        {showSql && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            className="mt-3 p-4 bg-[var(--bg-base)] rounded-xl overflow-x-auto border border-[var(--border)] shadow-inner"
          >
            <pre className="text-sm text-[var(--chart-2)] font-mono leading-relaxed whitespace-pre-wrap">
              {formatSql(result.resultData.generated_sql, { language: "postgresql" })}
            </pre>
          </motion.div>
        )}
      </div>
    </motion.div>
  );
}
