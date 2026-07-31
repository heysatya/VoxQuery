"use client";

import React, { useEffect, useState } from "react";
import { Brain, RefreshCw, BarChart3, Filter, CheckCircle2 } from "lucide-react";
import { fetchMemoryGraph, ApiRequestError } from "../../../lib/api";
import type { GraphNode, GraphEdge, MemoryGraphData } from "../../../lib/types";

export type { GraphNode, GraphEdge, MemoryGraphData };

type ExecutiveMemoryGraphProps = {
  sessionId: string | null;
  authToken?: string | null;
};

function formatNodeLabel(node: GraphNode): string {
  let label = node.label.replace(/^Entity:\s*/i, "").replace(/^Filter:\s*/i, "").replace(/_/g, " ");
  if (label.length > 50) label = label.slice(0, 47) + "...";
  return label;
}

export function ExecutiveMemoryGraph({
  sessionId,
  authToken,
}: ExecutiveMemoryGraphProps) {
  const [graphData, setGraphData] = useState<MemoryGraphData | null>(null);
  const [loading, setLoading] = useState(false);

  const fetchGraph = async () => {
    if (!sessionId) return;
    setLoading(true);
    try {
      const data = await fetchMemoryGraph(sessionId, authToken);
      setGraphData(data);
    } catch (err) {
      console.error("Could not fetch memory graph", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void fetchGraph();
  }, [sessionId, authToken]);

  if (!sessionId) {
    return (
      <div className="flex flex-col items-center justify-center p-8 border border-dashed border-[var(--border)] rounded-2xl bg-[var(--bg-glass)] text-center">
        <Brain className="w-8 h-8 text-[var(--text-muted)] mb-3" />
        <p className="text-sm text-[var(--text-secondary)] font-medium">Ask a question to get started — I'll keep track of what you've covered as you go.</p>
      </div>
    );
  }

  // Group nodes by turn index
  const turnsMap = new Map<number, GraphNode[]>();
  if (graphData?.nodes) {
    graphData.nodes.forEach((node) => {
      const list = turnsMap.get(node.turn_index) || [];
      list.push(node);
      turnsMap.set(node.turn_index, list);
    });
  }

  const turnIndexes = Array.from(turnsMap.keys()).sort((a, b) => a - b);

  return (
    <div className="w-full rounded-2xl bg-gradient-to-br from-[var(--bg-glass)] to-[var(--bg-surface)] border border-[var(--border-glass)] shadow-2xl p-6 relative overflow-hidden backdrop-blur-xl">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-2.5">
          <div className="p-2.5 rounded-xl bg-gradient-to-br from-purple-500/20 to-pink-500/20 text-purple-400 border border-purple-500/30 shadow-inner">
            <Brain className="w-5 h-5 animate-pulse" />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-[var(--text-primary)]">
              What we've covered
            </h3>
            <p className="text-[11px] text-[var(--text-muted)]">
              A quick recap of the questions and filters you've used in this session
            </p>
          </div>
        </div>
        <button
          type="button"
          onClick={fetchGraph}
          className="p-2 rounded-xl bg-[var(--bg-surface)] hover:bg-[var(--bg-elevated)] text-[var(--text-muted)] hover:text-[var(--text-primary)] border border-[var(--border-glass)] transition-colors"
          title="Refresh History"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
        </button>
      </div>

      {loading ? (
        <div className="h-48 flex items-center justify-center">
          <div className="w-8 h-8 border-2 border-[var(--accent-blue)] border-t-transparent rounded-full animate-spin" />
        </div>
      ) : graphData && turnIndexes.length > 0 ? (
        <div className="space-y-5">
          {/* Visual Step-by-Step Lineage */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {turnIndexes.map((turnIdx) => {
              const nodesInTurn = turnsMap.get(turnIdx) || [];
              const queryNode = nodesInTurn.find((n) => n.type === "query");
              const filterNodes = nodesInTurn.filter((n) => n.type === "filter");
              const metricNodes = nodesInTurn.filter((n) => n.type === "metric" || n.type === "insight");

              return (
                <div
                  key={turnIdx}
                  className="p-4 rounded-xl bg-[var(--bg-surface)] border border-[var(--border-glass)] shadow-md flex flex-col justify-between space-y-3 relative"
                >
                  <div className="flex items-center justify-between">
                    <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-indigo-500/10 text-indigo-400 border border-indigo-500/20 font-semibold uppercase">
                      Question {turnIdx}
                    </span>
                    <span className="text-[10px] text-[var(--text-muted)] flex items-center gap-1 font-mono">
                      <CheckCircle2 className="w-3 h-3 text-emerald-400" /> Active
                    </span>
                  </div>

                  {/* Primary Question / Scope */}
                  {queryNode && (
                    <div>
                      <span className="text-[10px] text-[var(--text-muted)] font-mono uppercase tracking-wider block mb-1">
                        You asked
                      </span>
                      <p className="text-xs font-semibold text-[var(--text-primary)] line-clamp-2">
                        {formatNodeLabel(queryNode)}
                      </p>
                    </div>
                  )}

                  {/* Applied Filters & Metrics */}
                  <div className="space-y-2 pt-2 border-t border-[var(--border-glass)]">
                    {filterNodes.map((fn) => (
                      <div key={fn.id} className="flex items-center gap-1.5 text-[11px] text-amber-300 font-mono">
                        <Filter className="w-3 h-3 shrink-0" />
                        <span className="truncate">{formatNodeLabel(fn)}</span>
                      </div>
                    ))}

                    {metricNodes.map((mn) => (
                      <div key={mn.id} className="flex items-center gap-1.5 text-[11px] text-emerald-300 font-mono">
                        <BarChart3 className="w-3 h-3 shrink-0" />
                        <span className="truncate">{formatNodeLabel(mn)}</span>
                      </div>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      ) : (
        <div className="h-44 flex items-center justify-center">
          <p className="text-sm text-[var(--text-secondary)] font-medium">Ask a question to get started — I'll keep track of what you've covered as you go.</p>
        </div>
      )}
    </div>
  );
}
