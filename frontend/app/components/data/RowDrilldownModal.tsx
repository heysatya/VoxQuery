"use client";

import React, { useEffect, useState, useCallback } from "react";
import { X, Table, Download, RefreshCw } from "lucide-react";
import { fetchDrilldown as fetchDrilldownApi, ApiRequestError } from "../../../lib/api";
import { FailureNotice } from "../notice/FailureNotice";

type RowDrilldownModalProps = {
  isOpen: boolean;
  onClose: () => void;
  turnId: string | null;
  authToken?: string | null;
};

export function RowDrilldownModal({
  isOpen,
  onClose,
  turnId,
  authToken,
}: RowDrilldownModalProps) {
  const [rows, setRows] = useState<Record<string, any>[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  const attemptFetch = useCallback(async (tid: string): Promise<Record<string, any>[]> => {
    return fetchDrilldownApi(tid, authToken);
  }, [authToken]);

  const fetchDrilldownData = useCallback(async () => {
    if (!turnId) return;
    setLoading(true);
    setLoadError(null);
    try {
      const data = await attemptFetch(turnId);
      setRows(data);
    } catch (err) {
      setRows([]);
      setLoadError(err instanceof ApiRequestError ? err.message : "Couldn't load drilldown data.");
    } finally {
      setLoading(false);
    }
  }, [turnId, attemptFetch]);

  useEffect(() => {
    if (isOpen && turnId) {
      void fetchDrilldownData();
    }
  }, [isOpen, turnId, fetchDrilldownData]);

  if (!isOpen) return null;

  const keys = rows.length > 0 ? Object.keys(rows[0]) : [];

  const handleDownloadCSV = () => {
    if (rows.length === 0) return;
    const headers = Object.keys(rows[0]).join(",");
    const csvRows = rows.map((row) =>
      Object.values(row)
        .map((value) => `"${String(value).replace(/"/g, '""')}"`)
        .join(",")
    );
    const csvContent = [headers, ...csvRows].join("\n");
    const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.setAttribute("href", url);
    link.setAttribute("download", `drilldown_${turnId}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-md p-4">
      <div className="w-full max-w-4xl bg-gradient-to-br from-[var(--bg-glass)] to-[var(--bg-surface)] border border-[var(--border-glass)] rounded-2xl shadow-2xl overflow-hidden flex flex-col max-h-[85vh] backdrop-blur-xl">
        {/* Header */}
        <div className="flex items-center justify-between p-5 border-b border-[var(--border-glass)]">
          <div className="flex items-center gap-2.5">
            <div className="p-2 rounded-xl bg-blue-500/10 text-blue-400 border border-blue-500/20">
              <Table className="w-5 h-5" />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-[var(--text-primary)]">Raw Transaction Drilldown</h3>
              <p className="text-[11px] text-[var(--text-muted)]">Validating Snowflake query records</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={handleDownloadCSV}
              disabled={rows.length === 0}
              className="p-1.5 rounded-lg hover:bg-[var(--bg-elevated)] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors flex items-center gap-1 text-xs"
            >
              <Download className="w-3.5 h-3.5" />
              <span>Export CSV</span>
            </button>
            <button
              onClick={onClose}
              className="p-1.5 rounded-lg hover:bg-[var(--bg-elevated)] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-auto p-6">
          {loading ? (
            <div className="h-64 flex flex-col items-center justify-center gap-3">
              <RefreshCw className="w-8 h-8 text-[var(--accent-blue)] animate-spin" />
              <p className="text-xs text-[var(--text-muted)]">Querying transaction log...</p>
            </div>
          ) : loadError ? (
            <div className="p-4">
              <FailureNotice
                severity="info"
                message={loadError}
                action={{ label: "Retry", onClick: () => void fetchDrilldownData() }}
              />
            </div>
          ) : rows.length > 0 ? (
            <div className="overflow-x-auto rounded-xl border border-[var(--border-glass)] bg-[var(--bg-surface)]">
              <table className="min-w-full divide-y divide-[var(--border)]">
                <thead className="bg-[var(--bg-elevated)]">
                  <tr>
                    {keys.map((key) => (
                      <th
                        key={key}
                        className="px-4 py-3 text-left text-[10px] font-mono font-semibold uppercase tracking-wider text-[var(--text-secondary)]"
                      >
                        {key.replace("_", " ")}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-[var(--border)] bg-transparent">
                  {rows.map((row, idx) => (
                    <tr key={idx} className="hover:bg-[var(--bg-elevated)]/50 transition-colors">
                      {keys.map((key) => (
                        <td key={key} className="px-4 py-3 text-xs font-mono text-[var(--text-primary)]">
                          {row[key] !== null ? String(row[key]) : <span className="text-gray-500 italic">null</span>}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="h-64 flex flex-col items-center justify-center">
              <p className="text-xs text-[var(--text-secondary)]">No raw records found for this query.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
