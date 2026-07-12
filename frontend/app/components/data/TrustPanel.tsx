"use client";

import React, { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ChevronDown, ShieldCheck, ShieldAlert, ShieldX, Info } from "lucide-react";
import { cn } from "../../../lib/utils";
import type { LastResult } from "../../../lib/types";
import {
  formatSqlHash,
  formatExecutionTime,
  formatDataSources,
  resultRowSummary,
} from "../../../lib/resultSemantics";

/* ── Trust Panel (Phase 4.1) ───────────────────────────────────── */

type TrustPanelProps = {
  result: LastResult;
};

const TIER_CONFIG = {
  High: {
    icon: ShieldCheck,
    iconColor: "text-[var(--accent-green)]",
    dotColor: "bg-[var(--accent-green)]",
    badgeClass: "bg-[var(--accent-green)]/10 border-[var(--accent-green)]/20 text-[var(--accent-green)]",
    label: "High confidence",
  },
  Medium: {
    icon: ShieldAlert,
    iconColor: "text-[var(--accent-amber)]",
    dotColor: "bg-[var(--accent-amber)]",
    badgeClass: "bg-[var(--accent-amber)]/10 border-[var(--accent-amber)]/20 text-[var(--accent-amber)]",
    label: "Partial match",
  },
  Low: {
    icon: Info,
    iconColor: "text-[var(--accent-blue)]",
    dotColor: "bg-[var(--accent-blue)]",
    badgeClass: "bg-[var(--accent-blue)]/10 border-[var(--accent-blue)]/20 text-[var(--accent-blue)]",
    label: "Assumptions made",
  },
};

function TrustRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-start gap-3 py-2 border-b border-[var(--border)] last:border-0">
      <span className="min-w-[140px] text-xs font-medium text-[var(--text-muted)] uppercase tracking-wider shrink-0">
        {label}
      </span>
      <span className="text-xs text-[var(--text-secondary)] break-all">{value}</span>
    </div>
  );
}

export function TrustPanel({ result }: TrustPanelProps) {
  const [expanded, setExpanded] = useState(false);
  const tier = result.confidenceTier;
  const config = TIER_CONFIG[tier] ?? TIER_CONFIG.High;
  const TierIcon = config.icon;
  const rd = result.resultData;

  // Evidence fields
  const confidenceReasons =
    rd.confidence_reasons ?? rd.trust?.confidence_reasons ?? [];
  const dataSources = formatDataSources(rd);
  const executionTime = formatExecutionTime(rd.trust?.execution_time_ms);
  const sqlHash = formatSqlHash(rd.trust?.sql_hash);
  const rowSummary = resultRowSummary(rd);
  const dataFreshness = rd.trust?.data_freshness_note ?? (rd.from_cache ? "Served from cache" : "Live warehouse query");
  const warningCount = rd.trust?.warning_count ?? rd.warnings.length;

  return (
    <div
      className={cn(
        "rounded-xl border transition-colors duration-200",
        expanded
          ? "border-[var(--border)] bg-[var(--bg-base)]/80"
          : "border-[var(--border)] bg-[var(--bg-base)]/40"
      )}
    >
      {/* Collapsed header — always visible */}
      <button
        type="button"
        aria-expanded={expanded}
        aria-label="How VoxQuery answered"
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-center justify-between px-4 py-3 gap-3 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent-blue)] rounded-xl"
      >
        <div className="flex items-center gap-2.5">
          <TierIcon
            className={cn("h-4 w-4 shrink-0", config.iconColor)}
            aria-hidden="true"
          />
          <span className={cn("text-xs font-semibold", config.iconColor)}>
            {config.label}
          </span>
          {dataFreshness && (
            <>
              <span className="text-[var(--text-muted)] text-xs">·</span>
              <span className="text-xs text-[var(--text-muted)]">{dataFreshness}</span>
            </>
          )}
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-[var(--text-muted)] hidden sm:inline">
            How VoxQuery answered
          </span>
          <ChevronDown
            className={cn("h-3.5 w-3.5 text-[var(--text-muted)] transition-transform duration-200", expanded && "rotate-180")}
          />
        </div>
      </button>

      {/* Expanded detail panel */}
      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.25 }}
            className="overflow-hidden"
          >
            <div className="px-4 pb-4 pt-1 space-y-0 border-t border-[var(--border)]">
              {/* Confidence tier */}
              <TrustRow
                label="Confidence"
                value={
                  <span className={cn("inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium border", config.badgeClass)}>
                    <span className={cn("w-1.5 h-1.5 rounded-full", config.dotColor)} />
                    {tier}
                  </span>
                }
              />

              {/* Confidence reasons — evidence-derived */}
              {confidenceReasons.length > 0 && (
                <TrustRow
                  label="Why"
                  value={
                    <ul className="space-y-1">
                      {confidenceReasons.map((r, i) => (
                        <li key={i} className="flex items-start gap-1.5">
                          <Info className="h-3 w-3 shrink-0 mt-0.5 text-[var(--text-muted)]" />
                          {r}
                        </li>
                      ))}
                    </ul>
                  }
                />
              )}

              {/* Data used */}
              <TrustRow label="Data used" value={dataSources} />

              {/* Data freshness */}
              <TrustRow label="Data freshness" value={dataFreshness} />

              {/* Execution */}
              <TrustRow
                label="Execution"
                value={
                  <span className="space-x-3">
                    <span>{rowSummary}</span>
                    {executionTime !== "—" && <span>· {executionTime}</span>}
                    {warningCount > 0 && (
                      <span className="text-[var(--accent-amber)]">
                        · {warningCount} {warningCount === 1 ? "warning" : "warnings"}
                      </span>
                    )}
                  </span>
                }
              />

              {/* SQL hash (dev transparency) */}
              {sqlHash !== "—" && (
                <TrustRow
                  label="SQL fingerprint"
                  value={
                    <span className="font-mono text-[var(--text-muted)]">#{sqlHash}</span>
                  }
                />
              )}

              {/* Warnings list */}
              {rd.warnings.length > 0 && (
                <TrustRow
                  label="Warnings"
                  value={
                    <ul className="space-y-1">
                      {rd.warnings.map((w, i) => (
                        <li key={i} className="text-[var(--accent-amber)]">
                          {w.message}
                        </li>
                      ))}
                    </ul>
                  }
                />
              )}

              {/* Interpretation */}
              <TrustRow
                label="Interpretation"
                value={
                  <span className="italic text-[var(--text-muted)]">
                    {rd.tts_text}
                  </span>
                }
              />
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
