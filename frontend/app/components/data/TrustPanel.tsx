"use client";

import React, { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ChevronDown, Info, ShieldAlert, ShieldCheck } from "lucide-react";
import { cn } from "../../../lib/utils";
import type { LastResult } from "../../../lib/types";
import { formatDataSources, formatExecutionTime, formatSqlHash, resultRowSummary } from "../../../lib/resultSemantics";

type TrustPanelProps = { result: LastResult };

const TIER_CONFIG = {
  High: {
    icon: ShieldCheck,
    color: "text-[var(--accent-green)]",
    dot: "bg-[var(--accent-green)]",
    badge: "bg-[var(--accent-green)]/10 border-[var(--accent-green)]/20 text-[var(--accent-green)]",
    label: "Validated result",
  },
  Medium: {
    icon: ShieldAlert,
    color: "text-[var(--accent-amber)]",
    dot: "bg-[var(--accent-amber)]",
    badge: "bg-[var(--accent-amber)]/10 border-[var(--accent-amber)]/20 text-[var(--accent-amber)]",
    label: "Review recommended",
  },
  Low: {
    icon: Info,
    color: "text-[var(--accent-blue)]",
    dot: "bg-[var(--accent-blue)]",
    badge: "bg-[var(--accent-blue)]/10 border-[var(--accent-blue)]/20 text-[var(--accent-blue)]",
    label: "Needs confirmation",
  },
} as const;

function TrustRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-start gap-3 py-2 border-b border-[var(--border)] last:border-0">
      <span className="min-w-[140px] text-xs font-medium text-[var(--text-muted)] uppercase tracking-wider shrink-0">{label}</span>
      <span className="text-xs text-[var(--text-secondary)] break-all">{value}</span>
    </div>
  );
}

export function TrustPanel({ result }: TrustPanelProps) {
  const [expanded, setExpanded] = useState(false);
  const rd = result.resultData;
  const config = TIER_CONFIG[result.confidenceTier] ?? TIER_CONFIG.High;
  const TierIcon = config.icon;
  const confidenceReasons = rd.confidence_reasons ?? rd.trust?.confidence_reasons ?? [];
  const dataSources = formatDataSources(rd);
  const executionTime = formatExecutionTime(rd.trust?.execution_time_ms);
  const sqlHash = formatSqlHash(rd.trust?.sql_hash);
  const dataFreshness = rd.trust?.data_freshness_note ?? (rd.from_cache ? "Served from cache" : "Live warehouse query");
  const warningCount = rd.trust?.warning_count ?? rd.warnings.length;

  return (
    <div className={cn("rounded-xl border transition-colors duration-200", expanded ? "border-[var(--border)] bg-[var(--bg-base)]/80" : "border-[var(--border)] bg-[var(--bg-base)]/40")}>
      <button
        type="button"
        aria-expanded={expanded}
        aria-label="How VoxQuery answered"
        onClick={() => setExpanded((value) => !value)}
        className="w-full flex items-center justify-between px-4 py-3 gap-3 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent-blue)] rounded-xl"
      >
        <div className="flex items-center gap-2.5 min-w-0">
          <TierIcon className={cn("h-4 w-4 shrink-0", config.color)} aria-hidden="true" />
          <span className={cn("text-xs font-semibold", config.color)}>{config.label}</span>
          <span className="text-[var(--text-muted)] text-xs" aria-hidden="true">•</span>
          <span className="text-xs text-[var(--text-muted)] truncate">{dataFreshness}</span>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <span className="text-xs text-[var(--text-muted)] hidden sm:inline">How VoxQuery answered</span>
          <ChevronDown className={cn("h-3.5 w-3.5 text-[var(--text-muted)] transition-transform", expanded && "rotate-180")} aria-hidden="true" />
        </div>
      </button>

      <AnimatePresence initial={false}>
        {expanded && (
          <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto" }} exit={{ opacity: 0, height: 0 }} className="overflow-hidden">
            <div className="px-4 pb-4 pt-1 space-y-0 border-t border-[var(--border)]">
              <TrustRow label="Confidence" value={<span className={cn("inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium border", config.badge)}><span className={cn("w-1.5 h-1.5 rounded-full", config.dot)} />{result.confidenceTier}</span>} />
              {confidenceReasons.length > 0 && <TrustRow label="Why" value={<ul className="space-y-1">{confidenceReasons.map((reason, index) => <li key={index} className="flex items-start gap-1.5"><Info className="h-3 w-3 shrink-0 mt-0.5 text-[var(--text-muted)]" />{reason}</li>)}</ul>} />}
              <TrustRow label="Data used" value={dataSources} />
              <TrustRow label="Data freshness" value={dataFreshness} />
              <TrustRow label="Execution" value={<span className="space-x-3"><span>{resultRowSummary(rd)}</span>{executionTime !== "—" && <span>• {executionTime}</span>}{warningCount > 0 && <span className="text-[var(--accent-amber)]">• {warningCount} {warningCount === 1 ? "warning" : "warnings"}</span>}</span>} />
              {sqlHash !== "—" && <TrustRow label="SQL fingerprint" value={<span className="font-mono text-[var(--text-muted)]">#{sqlHash}</span>} />}
              {rd.warnings.length > 0 && <TrustRow label="Warnings" value={<ul className="space-y-1">{rd.warnings.map((warning, index) => <li key={index} className="text-[var(--accent-amber)]">{warning.message}</li>)}</ul>} />}
              <TrustRow label="Interpretation" value={<span className="italic text-[var(--text-muted)]">{rd.tts_text}</span>} />
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
