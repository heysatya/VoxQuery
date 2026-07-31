"use client";

import React, { useEffect, useState } from "react";
import { Brain, RefreshCw, Layers, Database, BarChart3, Filter, CheckCircle2, Compass } from "lucide-react";
import { type VoxQueryAuthRelay } from "../../hooks/useVoxQuerySession";

export type GraphNode = {
  id: string;
  label: string;
  type: "query" | "entity" | "metric" | "filter" | "insight";
  turn_index: number;
};

export type GraphEdge = {
  source: string;
  target: string;
  relation: string;
};

export type MemoryGraphData = {
  session_id: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
};

type ExecutiveMemoryGraphProps = {
  sessionId: string | null;
  apiUrl?: string;
  auth: VoxQueryAuthRelay;
};

function formatNodeLabel(node: GraphNode): string {
  let label = node.label.replace(/^Entity:\s*/i, "").replace(/^Filter:\s*/i, "").replace(/_/g, " ");
  if (label.length > 50) label = label.slice(0, 47) + "...";
  return label;
}

export function ExecutiveMemoryGraph({
  sessionId,
  apiUrl = "http://127.0.0.1:8000",
  auth,
}: ExecutiveMemoryGraphProps) {
  const [graphData, setGraphData] = useState<MemoryGraphData | null>(null);
  const [loading, setLoading] = useState(false);
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);

  const fetchGraph = async () => {
    if (!sessionId) return;
    setLoading(true);
    try {
      const token = await auth.getToken();
      const res = await fetch(`${apiUrl}/api/memory-graph/${sessionId}`, {
        headers: {
          "Authorization": token ? `Bearer ${token}` : "Bearer fake",
          "X-Fake-User-Id": "00000000-0000-0000-0000-000000000001",
          "X-Fake-Tenant-Id": "00000000-0000-0000-0000-000000000101",
          "X-Fake-Role": "admin",
        },
      });
      if (res.ok) {
        const data = await res.json();
        setGraphData(data);
      }
    } catch (err) {
      console.error("Could not fetch memory graph", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void fetchGraph();
  }, [sessionId, auth]);

  if (!sessionId) {
    return (
      <div className="flex flex-col items-center justify-center p-8 border border-dashed border-[var(--border)] rounded-2xl bg-[var(--bg-glass)] text-center">
        <Brain className="w-8 h-8 text-[var(--text-muted)] mb-3" />
        <p className="text-sm text-[var(--text-secondary)] font-medium">Start a query session to view context lineage.</p>
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
            <h3 className="text-sm font-semibold text-[var(--text-primary)] flex items-center gap-2">
              Executive Context Lineage
              <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-purple-500/10 text-purple-400 border border-purple-500/20">
                {graphData?.nodes?.length || 0} Context Nodes
              </span>
            </h3>
            <p className="text-[11px] text-[var(--text-muted)]">Multi-turn analytical decision flow & active context memory</p>
          </div>
        </div>
        <button
          type="button"
          onClick={fetchGraph}
          className="p-2 rounded-xl bg-[var(--bg-surface)] hover:bg-[var(--bg-elevated)] text-[var(--text-muted)] hover:text-[var(--text-primary)] border border-[var(--border-glass)] transition-colors"
          title="Refresh Context Lineage"
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
                      Turn {turnIdx} Context
                    </span>
                    <span className="text-[10px] text-[var(--text-muted)] flex items-center gap-1 font-mono">
                      <CheckCircle2 className="w-3 h-3 text-emerald-400" /> Retained
                    </span>
                  </div>

                  {/* Primary Question / Scope */}
                  {queryNode && (
                    <div>
                      <span className="text-[10px] text-[var(--text-muted)] font-mono uppercase tracking-wider block mb-1">
                        Analytical Scope
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

          {/* Active Context Chips */}
          <div className="p-4 rounded-xl bg-[var(--bg-elevated)] border border-[var(--border-glass)] flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Compass className="w-4 h-4 text-purple-400" />
              <span className="text-xs font-semibold text-[var(--text-primary)]">Active Decision Context:</span>
            </div>
            <div className="flex flex-wrap gap-2">
              <span className="text-[10px] font-mono px-2.5 py-1 rounded-lg bg-purple-500/10 text-purple-300 border border-purple-500/20">
                Multi-Turn Retained
              </span>
              <span className="text-[10px] font-mono px-2.5 py-1 rounded-lg bg-emerald-500/10 text-emerald-300 border border-emerald-500/20">
                Zero Context Loss
              </span>
            </div>
          </div>
        </div>
      ) : (
        <div className="h-44 flex items-center justify-center">
          <p className="text-sm text-[var(--text-secondary)] font-medium">No context history recorded for this session.</p>
        </div>
      )}
    </div>
  );
}
