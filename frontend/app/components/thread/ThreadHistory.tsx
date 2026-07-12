"use client";

import React, { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ChevronDown, Code } from "lucide-react";
import { cn } from "../../../lib/utils";
import type { LastResult } from "../../../lib/types";
import { selectedChartType } from "../../../lib/resultSemantics";

type ExpandableThreadEntryProps = {
  turn: LastResult;
  index: number;
};

function ExpandableThreadEntry({ turn, index }: ExpandableThreadEntryProps) {
  const [expanded, setExpanded] = useState(false);
  const chartType = selectedChartType(turn.resultData, null);

  const confidenceColor =
    turn.confidenceTier === "High"
      ? "bg-[var(--accent-green)]"
      : turn.confidenceTier === "Medium"
      ? "bg-[var(--accent-amber)]"
      : "bg-red-400";

  return (
    <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-surface)] overflow-hidden">
      <button
        type="button"
        onClick={() => setExpanded((prev) => !prev)}
        aria-expanded={expanded}
        aria-controls={`thread-entry-${turn.turnId}`}
        className="w-full flex items-center gap-3 px-4 py-3 text-left hover:bg-[var(--bg-elevated)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent-blue)] transition-colors"
      >
        <span className="text-[10px] font-semibold tracking-wider uppercase text-[var(--text-muted)] shrink-0">
          Q{index + 1}
        </span>
        <span className="flex-1 text-sm text-[var(--text-secondary)] truncate">
          {turn.submittedText}
        </span>
        <span className={cn("w-1.5 h-1.5 rounded-full shrink-0", confidenceColor)} />
        <span className="text-[11px] text-[var(--text-muted)] shrink-0">
          {turn.confidenceTier}
        </span>
        <ChevronDown
          className={cn(
            "h-3.5 w-3.5 text-[var(--text-muted)] transition-transform shrink-0",
            expanded && "rotate-180"
          )}
        />
      </button>

      <AnimatePresence initial={false}>
        {expanded && (
          <motion.div
            id={`thread-entry-${turn.turnId}`}
            key="content"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.25, ease: [0.23, 1, 0.32, 1] }}
            className="overflow-hidden"
          >
            <div className="px-4 pb-4 space-y-3 border-t border-[var(--border)]">
              {/* Summary headline */}
              {turn.resultData.tts_text && (
                <p className="pt-3 text-sm text-[var(--text-secondary)] italic">
                  &ldquo;{turn.resultData.tts_text}&rdquo;
                </p>
              )}

              {/* Metadata row */}
              <div className="flex flex-wrap gap-3 text-[11px] text-[var(--text-muted)]">
                <span>{turn.resultData.result.row_count ?? turn.resultData.result.rows.length} rows</span>
                <span>·</span>
                <span>{chartType} view</span>
                {turn.resultData.warnings.length > 0 && (
                  <>
                    <span>·</span>
                    <span className="text-[var(--accent-amber)]">
                      {turn.resultData.warnings.length} warning
                      {turn.resultData.warnings.length !== 1 && "s"}
                    </span>
                  </>
                )}
              </div>

              {/* SQL preview */}
              {turn.resultData.generated_sql && (
                <details className="group">
                  <summary className="flex items-center gap-1.5 text-[11px] text-[var(--text-muted)] cursor-pointer hover:text-[var(--text-secondary)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent-blue)] transition-colors list-none">
                    <Code className="h-3 w-3" />
                    View SQL
                  </summary>
                  <pre className="mt-2 p-3 rounded-lg bg-[var(--bg-base)] text-[10px] text-[var(--chart-2)] font-mono leading-relaxed overflow-x-auto border border-[var(--border)]">
                    {turn.resultData.generated_sql}
                  </pre>
                </details>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

type ThreadHistoryProps = {
  turns: LastResult[];
  activeTurnId: string | null;
};

/**
 * Prior conversation turns — compressed by default, expandable on demand.
 * Each entry shows: question, confidence, row count, chart type, and SQL.
 * The active turn is excluded from this list (it is rendered separately).
 */
export function ThreadHistory({ turns, activeTurnId }: ThreadHistoryProps) {
  const priorTurns = turns.filter((turn) => turn.turnId !== activeTurnId);
  if (!priorTurns.length) return null;

  return (
    <section
      aria-label="Prior turns"
      className="mb-6 space-y-2"
    >
      <p className="text-[10px] font-semibold tracking-widest uppercase text-[var(--text-muted)] mb-3">
        Prior questions
      </p>
      {priorTurns.map((turn, index) => (
        <ExpandableThreadEntry key={turn.turnId} turn={turn} index={index} />
      ))}
      <div className="border-b border-[var(--border)] pt-2" />
    </section>
  );
}
