"use client";

import React, { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { motion } from "framer-motion";
import { Loader2, ShieldAlert, Calendar, Database, ArrowLeft, Download, Terminal } from "lucide-react";
import Link from "next/link";
import { fetchSharedResult } from "../../../lib/api";
import type { SharedResultResponse } from "../../../lib/types";
import { VoxQueryLogo } from "../../components/brand/VoxQueryLogo";
import { cn } from "../../../lib/utils";

export default function SharePage() {
  const params = useParams();
  const token = params?.token as string;
  const [data, setData] = useState<SharedResultResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!token) return;
    async function load() {
      try {
        setLoading(true);
        const res = await fetchSharedResult(token);
        setData(res);
      } catch (err: any) {
        setError(err.message || "This share link is invalid or has expired.");
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [token]);

  if (loading) {
    return (
      <main className="min-h-screen bg-[#090B10] flex flex-col items-center justify-center p-4">
        <Loader2 className="w-8 h-8 text-[var(--accent-blue)] animate-spin mb-4" />
        <p className="text-xs text-[var(--text-muted)] font-mono">Loading shared executive insight...</p>
      </main>
    );
  }

  if (error || !data) {
    return (
      <main className="min-h-screen bg-[#090B10] flex flex-col items-center justify-center p-4">
        <div className="glass-card p-8 max-w-md w-full text-center space-y-6">
          <ShieldAlert className="w-12 h-12 text-[var(--accent-rose)] mx-auto" />
          <h1 className="text-xl font-bold text-white">Share Link Unavailable</h1>
          <p className="text-[var(--text-secondary)] text-sm">{error || "This shared report link is no longer accessible."}</p>
          <Link
            href="/"
            className="inline-flex items-center gap-2 px-5 py-2.5 bg-[var(--accent-blue)] text-white text-xs font-semibold rounded-xl hover:bg-[var(--accent-blue)]/80 transition-colors"
          >
            <ArrowLeft className="w-4 h-4" /> Go to VoxQuery
          </Link>
        </div>
      </main>
    );
  }

  const columns = data.full_result?.columns || [];
  const rows = data.full_result?.rows || [];

  return (
    <main className="min-h-screen bg-[#090B10] text-white flex flex-col">
      {/* Header */}
      <header className="px-6 py-4 border-b border-white/5 bg-[#10141C]/80 backdrop-blur-md flex items-center justify-between">
        <div className="flex items-center gap-3">
          <VoxQueryLogo variant="header" />
          <span className="text-xs font-mono px-2 py-0.5 rounded-full bg-[var(--accent-blue)]/10 text-[var(--accent-blue)] border border-[var(--accent-blue)]/20">
            Shared Report
          </span>
        </div>
        <Link
          href="/"
          className="text-xs text-[var(--text-secondary)] hover:text-white flex items-center gap-1.5 transition-colors"
        >
          Open App <ArrowLeft className="w-3.5 h-3.5 rotate-180" />
        </Link>
      </header>

      {/* Main Content */}
      <section className="flex-1 max-w-5xl mx-auto w-full p-6 md:p-10 space-y-8">
        {/* Title / Meta Card */}
        <div className="glass-card p-6 md:p-8 space-y-4">
          <div className="flex items-center gap-2 text-xs text-[var(--text-muted)] font-mono">
            <Calendar className="w-4 h-4 text-[var(--accent-blue)]" />
            <span>Shared on {new Date(data.created_at).toLocaleDateString()}</span>
            <span>•</span>
            <span>Expires {new Date(data.expires_at).toLocaleDateString()}</span>
          </div>

          <h1 className="text-xl md:text-2xl font-light tracking-tight text-white flex items-start gap-3">
            <Terminal className="w-6 h-6 text-[var(--accent-blue)] shrink-0 mt-1" />
            "{data.user_input}"
          </h1>

          {data.label && (
            <p className="text-xs text-[var(--text-secondary)] bg-white/5 px-3 py-1.5 rounded-lg border border-white/10 inline-block font-mono">
              Note: {data.label}
            </p>
          )}
        </div>

        {/* Data Snapshot Table */}
        <div className="glass-card overflow-hidden">
          <div className="p-5 border-b border-white/5 flex items-center justify-between">
            <div className="flex items-center gap-2 text-sm font-semibold text-white">
              <Database className="w-4 h-4 text-[var(--accent-blue)]" />
              <span>Data Snapshot</span>
            </div>
            <span className="text-xs font-mono text-[var(--text-muted)]">
              {rows.length} {rows.length === 1 ? "row" : "rows"}
            </span>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="bg-white/[0.02] border-b border-white/5">
                <tr>
                  {columns.map((col: string, idx: number) => (
                    <th key={idx} className="px-5 py-3.5 font-semibold text-[var(--text-muted)] uppercase tracking-wider text-xs">
                      {col}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {rows.length === 0 ? (
                  <tr>
                    <td colSpan={columns.length || 1} className="px-5 py-8 text-center text-[var(--text-muted)] italic text-xs">
                      No rows returned in snapshot.
                    </td>
                  </tr>
                ) : (
                  rows.map((row: any[], rIdx: number) => (
                    <tr key={rIdx} className="hover:bg-white/[0.02] transition-colors">
                      {row.map((cell: any, cIdx: number) => (
                        <td key={cIdx} className="px-5 py-3.5 text-white font-mono text-xs whitespace-nowrap">
                          {cell !== null && cell !== undefined ? String(cell) : "-"}
                        </td>
                      ))}
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      </section>
    </main>
  );
}
