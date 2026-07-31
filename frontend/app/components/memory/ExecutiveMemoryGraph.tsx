"use client";

import React, { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Brain, RefreshCw, Layers, Database, BarChart3, Filter, ShieldAlert } from "lucide-react";

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

  const getNodeColor = (type: string) => {
    switch (type) {
      case "query":
        return "from-indigo-500/20 to-purple-500/20 border-indigo-500/40 text-indigo-300";
      case "metric":
        return "from-emerald-500/20 to-teal-500/20 border-emerald-500/40 text-emerald-300";
      case "entity":
        return "from-sky-500/20 to-blue-500/20 border-sky-500/40 text-sky-300";
      case "filter":
        return "from-amber-500/20 to-orange-500/20 border-amber-500/40 text-amber-300";
      case "insight":
        return "from-rose-500/20 to-pink-500/20 border-rose-500/40 text-rose-300 shadow-[0_0_15px_rgba(244,63,94,0.15)]";
      default:
        return "from-gray-500/20 to-slate-500/20 border-gray-500/40 text-gray-300";
    }
  };

  const getNodeIcon = (type: string) => {
    switch (type) {
      case "query":
        return <Brain className="w-4 h-4" />;
      case "metric":
        return <BarChart3 className="w-4 h-4" />;
      case "entity":
        return <Database className="w-4 h-4" />;
      case "filter":
        return <Filter className="w-4 h-4" />;
      case "insight":
        return <Layers className="w-4 h-4" />;
      default:
        return <Layers className="w-4 h-4" />;
    }
  };

  if (!sessionId) {
    return (
      <div className="flex flex-col items-center justify-center p-8 border border-dashed border-[var(--border)] rounded-2xl bg-[var(--bg-glass)]">
        <Brain className="w-8 h-8 text-[var(--text-muted)] mb-3" />
        <p className="text-sm text-[var(--text-secondary)]">Start a query session to view memory connections.</p>
      </div>
    );
  }

  return (
    <div className="w-full rounded-2xl bg-gradient-to-br from-[var(--bg-glass)] to-[var(--bg-surface)] border border-[var(--border-glass)] shadow-xl p-6 relative overflow-hidden backdrop-blur-xl">
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-2.5">
          <div className="p-2 rounded-xl bg-purple-500/10 text-purple-400 border border-purple-500/20">
            <Brain className="w-5 h-5 animate-pulse" />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-[var(--text-primary)]">Multi-Turn Memory Graph</h3>
            <p className="text-[11px] text-[var(--text-muted)]">Visualizing context retention & entity relations</p>
          </div>
        </div>
        <button
          type="button"
          onClick={fetchGraph}
          className="p-1.5 rounded-lg hover:bg-[var(--bg-elevated)] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
        </button>
      </div>

      {loading ? (
        <div className="h-64 flex items-center justify-center">
          <div className="w-8 h-8 border-2 border-[var(--accent-blue)] border-t-transparent rounded-full animate-spin" />
        </div>
      ) : graphData ? (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {/* Visual Graph Nodes */}
          <div className="md:col-span-2 p-4 rounded-xl bg-[var(--bg-surface)] border border-[var(--border-glass)] relative min-h-[300px] flex flex-col justify-around">
            <div className="absolute top-3 left-3 text-[10px] font-mono text-[var(--text-muted)]">DAG Visual Workspace</div>
            <div className="flex flex-col gap-4 mt-6">
              {graphData.nodes.map((node) => (
                <div
                  key={node.id}
                  onClick={() => setSelectedNode(node)}
                  className={`p-3 rounded-xl bg-gradient-to-r ${getNodeColor(node.type)} border cursor-pointer hover:scale-[1.02] transition-all flex items-center justify-between group`}
                >
                  <div className="flex items-center gap-3">
                    <div className="p-1.5 rounded-lg bg-[var(--bg-elevated)] border border-[var(--border-glass)]">
                      {getNodeIcon(node.type)}
                    </div>
                    <div>
                      <span className="text-xs font-mono font-medium block">{node.label}</span>
                      <span className="text-[10px] text-[var(--text-muted)] capitalize">Type: {node.type}</span>
                    </div>
                  </div>
                  <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-[var(--bg-elevated)] text-[var(--text-muted)] border border-[var(--border-glass)]">
                    Turn {node.turn_index}
                  </span>
                </div>
              ))}
            </div>
          </div>

          {/* Relation & Inspector Details */}
          <div className="flex flex-col justify-between p-4 rounded-xl bg-[var(--bg-surface)] border border-[var(--border-glass)]">
            <div>
              <span className="text-xs font-mono text-[var(--accent-blue)] block mb-4">Memory Inspector</span>
              {selectedNode ? (
                <div className="space-y-4">
                  <div>
                    <span className="text-[10px] text-[var(--text-muted)] block font-mono">NODE IDENTIFIER</span>
                    <span className="text-sm font-semibold text-[var(--text-primary)]">{selectedNode.label}</span>
                  </div>
                  <div>
                    <span className="text-[10px] text-[var(--text-muted)] block font-mono">NODE CATEGORY</span>
                    <span className="text-xs capitalize font-mono px-2 py-1 rounded bg-[var(--bg-elevated)] border border-[var(--border-glass)] inline-block mt-1">
                      {selectedNode.type}
                    </span>
                  </div>
                  <div>
                    <span className="text-[10px] text-[var(--text-muted)] block font-mono">SESSION TURN</span>
                    <span className="text-xs font-mono">Retained from step {selectedNode.turn_index}</span>
                  </div>
                </div>
              ) : (
                <p className="text-xs text-[var(--text-secondary)] italic">Click any memory node to inspect relationships & active context.</p>
              )}
            </div>

            {/* Edge list */}
            <div className="pt-4 border-t border-[var(--border)] mt-6">
              <span className="text-[10px] font-mono text-[var(--text-muted)] block mb-2">Connected Transitions:</span>
              <div className="space-y-1.5 max-h-36 overflow-y-auto pr-1">
                {graphData.edges.map((edge, idx) => (
                  <div key={idx} className="text-[11px] flex items-center justify-between text-[var(--text-secondary)]">
                    <span className="font-mono">{edge.source.replace("node_", "")}</span>
                    <span className="text-[10px] text-[var(--accent-blue)] font-mono">--{edge.relation}{"-->"}</span>
                    <span className="font-mono">{edge.target.replace("node_", "")}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      ) : (
        <div className="h-64 flex items-center justify-center">
          <p className="text-sm text-[var(--text-secondary)]">No memory data found for this session.</p>
        </div>
      )}
    </div>
  );
}
