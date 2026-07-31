"use client";

import React, { useState } from "react";
import { Grid, Pin, Trash2, LayoutGrid, Check } from "lucide-react";
import { type LastResult } from "../../../lib/types";

type PinnedWidget = {
  id: string;
  title: string;
  result: LastResult;
};

type ExecutiveWorkspaceProps = {
  pinnedWidgets?: PinnedWidget[];
  onRemoveWidget?: (id: string) => void;
};

export function ExecutiveWorkspace({
  pinnedWidgets = [],
  onRemoveWidget,
}: ExecutiveWorkspaceProps) {
  return (
    <div className="w-full rounded-2xl bg-gradient-to-br from-[var(--bg-glass)] to-[var(--bg-surface)] border border-[var(--border-glass)] shadow-2xl p-6 backdrop-blur-xl relative overflow-hidden">
      <div className="flex items-center gap-2.5 mb-6">
        <div className="p-2 rounded-xl bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
          <LayoutGrid className="w-5 h-5" />
        </div>
        <div>
          <h3 className="text-sm font-semibold text-[var(--text-primary)]">Executive Grid Workspace</h3>
          <p className="text-[11px] text-[var(--text-muted)]">Pinned metrics & side-by-side transaction dashboards</p>
        </div>
      </div>

      {pinnedWidgets.length === 0 ? (
        <div className="h-44 flex flex-col items-center justify-center border border-dashed border-[var(--border)] rounded-xl bg-[var(--bg-glass)] p-4 text-center">
          <Pin className="w-6 h-6 text-[var(--text-muted)] mb-2" />
          <p className="text-xs text-[var(--text-secondary)] font-medium">No pinned widgets yet.</p>
          <p className="text-[10px] text-[var(--text-muted)] mt-1">Pin charts and query results here to construct your custom dashboard.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {pinnedWidgets.map((widget) => (
            <div
              key={widget.id}
              className="p-5 rounded-xl bg-[var(--bg-surface)] border border-[var(--border-glass)] shadow-md flex flex-col justify-between relative group"
            >
              <div className="absolute top-3 right-3 opacity-0 group-hover:opacity-100 transition-opacity">
                {onRemoveWidget && (
                  <button
                    type="button"
                    onClick={() => onRemoveWidget(widget.id)}
                    className="p-1 rounded bg-rose-500/10 text-rose-400 hover:bg-rose-500/20 border border-rose-500/20 transition-colors"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                )}
              </div>

              <div>
                <span className="text-[10px] font-mono text-[var(--text-muted)] uppercase tracking-wider block mb-1">
                  Pinned Widget
                </span>
                <h4 className="text-xs font-semibold text-[var(--text-primary)] mb-3">{widget.title}</h4>
                <div className="text-sm font-semibold text-[var(--accent-blue)]">
                  {widget.result?.resultData?.result?.rows?.length ?? widget.result?.result?.rows?.length ?? widget.result?.result?.row_count ?? 0} rows retrieved
                </div>
              </div>

              <div className="mt-4 pt-3 border-t border-[var(--border)] text-[10px] text-[var(--text-muted)] font-mono">
                Source turn ID: {(widget.result?.turnId || widget.result?.turn_id || widget.id).slice(0, 8)}...
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
