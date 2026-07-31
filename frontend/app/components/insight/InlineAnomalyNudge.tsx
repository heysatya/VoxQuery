"use client";

import React from "react";
import { AlertTriangle, Sparkles } from "lucide-react";
import type { BriefingAnomaly } from "../../../lib/types";

type InlineAnomalyNudgeProps = {
  anomaly?: BriefingAnomaly;
  onAskBreakdown?: (query: string) => void;
};

export function InlineAnomalyNudge({
  anomaly = {
    severity: "warning",
    title: "Variance detected",
    description: "Metric is 23% below last week's 30-day average.",
  },
  onAskBreakdown,
}: InlineAnomalyNudgeProps) {
  const queryText = `Give me the breakdown for ${anomaly.title}`;

  return (
    <div className="my-4 p-3.5 rounded-xl bg-amber-500/10 border border-amber-500/20 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 text-xs text-amber-200">
      <div className="flex items-center gap-2.5">
        <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0" />
        <div>
          <span className="font-bold text-amber-300">{anomaly.title}: </span>
          <span>{anomaly.description}</span>
        </div>
      </div>

      {onAskBreakdown && (
        <button
          type="button"
          onClick={() => onAskBreakdown(queryText)}
          className="shrink-0 px-3 py-1.5 rounded-lg bg-amber-500/20 hover:bg-amber-500/30 border border-amber-500/30 text-amber-100 font-medium flex items-center gap-1.5 transition-colors"
        >
          <Sparkles className="w-3 h-3 text-amber-300" />
          <span>Want the breakdown?</span>
        </button>
      )}
    </div>
  );
}
