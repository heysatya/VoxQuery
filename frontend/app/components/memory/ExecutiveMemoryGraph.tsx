"use client";

import React, { useCallback, useEffect, useState } from "react";
import { CheckCircle2, Filter, History, RefreshCw } from "lucide-react";
import { fetchMemoryGraph, ApiRequestError } from "../../../lib/api";
import type { GraphEdge, GraphNode, MemoryGraphData } from "../../../lib/types";
import { FailureNotice } from "../notice/FailureNotice";

export type { GraphNode, GraphEdge, MemoryGraphData };

type ExecutiveMemoryGraphProps = {
  sessionId: string | null;
  authToken?: string | null;
};

function formatNodeLabel(node: GraphNode): string {
  const label = node.label
    .replace(/^Entity:\s*/i, "")
    .replace(/^Filter:\s*/i, "")
    .replace(/^Chart:\s*/i, "")
    .replace(/_/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  return label.length > 140 ? `${label.slice(0, 137)}...` : label;
}

export function ExecutiveMemoryGraph({ sessionId, authToken }: ExecutiveMemoryGraphProps) {
  const [graphData, setGraphData] = useState<MemoryGraphData | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  const loadGraph = useCallback(async () => {
    if (!sessionId) return;
    setLoading(true);
    setLoadError(null);
    try {
      setGraphData(await fetchMemoryGraph(sessionId, authToken));
    } catch (error) {
      setGraphData(null);
      setLoadError(error instanceof ApiRequestError ? error.message : "Could not load the conversation trail.");
    } finally {
      setLoading(false);
    }
  }, [authToken, sessionId]);

  useEffect(() => {
    void loadGraph();
  }, [loadGraph]);

  if (!sessionId) {
    return (
      <div className="flex flex-col items-center justify-center p-8 border border-dashed border-[var(--border)] rounded-2xl bg-[var(--bg-glass)] text-center">
        <History className="w-8 h-8 text-[var(--text-muted)] mb-3" aria-hidden="true" />
        <p className="text-sm text-[var(--text-secondary)] font-medium">Your conversation trail will appear here.</p>
        <p className="text-xs text-[var(--text-muted)] mt-1">Follow-up questions will show how the analysis became more focused.</p>
      </div>
    );
  }

  const turnsMap = new Map<number, GraphNode[]>();
  graphData?.nodes.forEach((node) => {
    const nodes = turnsMap.get(node.turn_index) ?? [];
    nodes.push(node);
    turnsMap.set(node.turn_index, nodes);
  });
  const turnIndexes = Array.from(turnsMap.keys()).sort((a, b) => a - b);

  return (
    <section className="w-full rounded-2xl bg-gradient-to-br from-[var(--bg-glass)] to-[var(--bg-surface)] border border-[var(--border-glass)] shadow-2xl p-6 relative overflow-hidden backdrop-blur-xl" aria-labelledby="analysis-recap-title">
      <div className="flex items-start justify-between gap-4 mb-6">
        <div className="flex items-start gap-2.5">
          <div className="p-2.5 rounded-xl bg-purple-500/10 text-purple-300 border border-purple-500/20">
            <History className="w-5 h-5" aria-hidden="true" />
          </div>
          <div>
            <h3 id="analysis-recap-title" className="text-sm font-bold text-white">Conversation trail</h3>
            <p className="text-[11px] text-slate-300 font-medium mt-0.5">The questions behind this analysis</p>
          </div>
        </div>
        <button
          type="button"
          onClick={() => void loadGraph()}
          className="p-2 rounded-xl bg-slate-800/80 hover:bg-slate-800 text-slate-200 hover:text-white border border-slate-700/60 transition-colors touch-target"
          title="Refresh conversation trail"
          aria-label="Refresh conversation trail"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} aria-hidden="true" />
        </button>
      </div>

      {loading ? (
        <div role="status" aria-live="polite" className="h-48 flex items-center justify-center">
          <div className="w-8 h-8 border-2 border-[var(--accent-blue)] border-t-transparent rounded-full animate-spin" />
          <span className="sr-only">Loading conversation trail</span>
        </div>
      ) : loadError ? (
        <div role="status" aria-live="polite" className="my-4">
          <FailureNotice severity="info" message={loadError} action={{ label: "Retry", onClick: () => void loadGraph() }} />
        </div>
      ) : turnIndexes.length === 0 ? (
        <div className="h-36 flex flex-col items-center justify-center text-center">
          <p className="text-sm text-[var(--text-secondary)] font-medium">No questions in this conversation yet.</p>
          <p className="text-xs text-[var(--text-muted)] mt-1">Ask a follow-up question and VoxQuery will show how the analysis evolves.</p>
        </div>
      ) : (
        <ol className="relative space-y-4" aria-label="Analysis steps">
          {turnIndexes.map((turnIndex, index) => {
            const nodes = turnsMap.get(turnIndex) ?? [];
            const query = nodes.find((node) => node.type === "query");
            const filters = nodes.filter((node) => node.type === "filter");
            const isCurrent = index === turnIndexes.length - 1;
            return (
              <li key={turnIndex} className="relative flex gap-3">
                {index < turnIndexes.length - 1 && <span className="absolute left-[11px] top-7 bottom-[-18px] w-px bg-white/10" aria-hidden="true" />}
                <span className={`relative z-10 mt-1 flex h-6 w-6 shrink-0 items-center justify-center rounded-full border ${isCurrent ? "border-cyan-300/50 bg-cyan-300/10" : "border-white/10 bg-[var(--bg-elevated)]"}`}>
                  <CheckCircle2 className={`h-3.5 w-3.5 ${isCurrent ? "text-cyan-300" : "text-emerald-400"}`} aria-hidden="true" />
                </span>
                <div className={`min-w-0 flex-1 rounded-xl border p-4 ${isCurrent ? "border-cyan-300/20 bg-cyan-300/5" : "border-white/10 bg-[var(--bg-surface)]"}`}>
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="text-[10px] uppercase tracking-[0.16em] text-[var(--text-muted)]">{isCurrent ? "Current focus" : "Earlier in this analysis"}</span>
                    <span className="text-[10px] text-[var(--text-muted)]">Step {index + 1}</span>
                  </div>
                  <p className="mt-2 text-sm font-semibold leading-6 text-white">{query ? formatNodeLabel(query) : "Analysis step"}</p>
                  {index > 0 && <p className="mt-1 text-[11px] text-cyan-200/70">This step builds on the previous question.</p>}
                  {filters.length > 0 && (
                    <div className="mt-3 flex flex-wrap gap-2">
                      {filters.map((filter) => (
                        <span key={filter.id} className="inline-flex items-center gap-1.5 rounded-full border border-amber-300/20 bg-amber-300/5 px-2.5 py-1 text-[11px] text-amber-200">
                          <Filter className="h-3 w-3" aria-hidden="true" />
                          {formatNodeLabel(filter)}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}
