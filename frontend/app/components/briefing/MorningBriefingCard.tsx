"use client";

import React, { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Sun, TrendingUp, TrendingDown, AlertTriangle, Sparkles, ChevronRight, X, Download } from "lucide-react";
import { ExecutiveAudioPlayer } from "../insight/ExecutiveAudioPlayer";
import { fetchAuthenticatedBlob } from "../../../lib/api";

export type BriefingKpi = {
  label: string;
  value: string;
  change_pct: number;
  trend: "up" | "down" | "neutral";
  insight: string;
};

export type BriefingAnomaly = {
  severity: "warning" | "critical" | "info";
  title: string;
  description: string;
};

export type ExecutiveBriefingData = {
  date: string;
  greeting: string;
  kpis: BriefingKpi[];
  summary_narrative: string;
  anomalies: BriefingAnomaly[];
  proactive_insights: string[];
};

type MorningBriefingCardProps = {
  apiUrl?: string;
  token?: string | null;
  onSelectInsight?: (query: string) => void;
};

export function MorningBriefingCard({ apiUrl = "http://127.0.0.1:8000", token, onSelectInsight }: MorningBriefingCardProps) {
  const [briefing, setBriefing] = useState<ExecutiveBriefingData | null>(null);
  const [dismissed, setDismissed] = useState(false);
  const [loading, setLoading] = useState(true);
  const [audioUrl, setAudioUrl] = useState<string | undefined>();
  const [isDownloadingPdf, setIsDownloadingPdf] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function fetchBriefing() {
      try {
        const res = await fetch(`${apiUrl}/api/briefing`, {
          headers: {
            "Authorization": token ? `Bearer ${token}` : "Bearer fake",
            "X-Fake-User-Id": "00000000-0000-0000-0000-000000000001",
            "X-Fake-Tenant-Id": "00000000-0000-0000-0000-000000000101",
            "X-Fake-Role": "admin",
          },
        });
        if (res.ok) {
          const data = await res.json();
          if (!cancelled) {
            setBriefing(data);
          }
        }
      } catch (err) {
        console.error("Could not fetch morning briefing", err);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void fetchBriefing();
    return () => {
      cancelled = true;
    };
  }, [apiUrl, token]);

  useEffect(() => {
    let objectUrl: string | undefined;
    fetchAuthenticatedBlob("/api/briefing/audio", apiUrl, token)
      .then((blob) => {
        objectUrl = URL.createObjectURL(blob);
        setAudioUrl(objectUrl);
      })
      .catch(() => setAudioUrl(undefined));
    return () => {
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [apiUrl, token]);

  const handleDownloadPdf = async () => {
    try {
      setIsDownloadingPdf(true);
      const blob = await fetchAuthenticatedBlob("/api/briefing/pdf", apiUrl, token);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "briefing.pdf";
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      console.error("Failed to download briefing PDF", err);
    } finally {
      setIsDownloadingPdf(false);
    }
  };

  if (dismissed || loading || !briefing) return null;

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0, y: -20 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, height: 0 }}
        className="w-full max-w-4xl mx-auto mb-8 p-6 rounded-2xl bg-gradient-to-br from-[var(--bg-glass)] to-[var(--bg-surface)] border border-[var(--border-glass)] shadow-2xl backdrop-blur-xl relative overflow-hidden"
      >
        {/* Glow Header Accent */}
        <div className="absolute -top-24 -right-24 w-48 h-48 rounded-full bg-amber-500/10 blur-3xl pointer-events-none" />

        {/* Top Header Row */}
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-xl bg-amber-500/10 text-amber-400 border border-amber-500/20">
              <Sun className="w-5 h-5 animate-pulse" />
            </div>
            <div>
              <h2 className="text-base font-medium text-[var(--text-primary)]">{briefing.greeting}</h2>
              <p className="text-xs text-[var(--text-muted)]">Logon KPI summary & anomaly report</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={handleDownloadPdf}
              disabled={isDownloadingPdf}
              className="text-xs px-3 py-1.5 rounded-lg bg-[var(--bg-elevated)] hover:bg-[var(--accent-blue)]/15 border border-[var(--border-glass)] text-[var(--text-secondary)] hover:text-[var(--accent-blue)] transition-all flex items-center gap-1.5 disabled:opacity-50"
            >
              <Download className="w-3.5 h-3.5" />
              <span>{isDownloadingPdf ? "Downloading..." : "Download PDF Report"}</span>
            </button>
            <button
              type="button"
              onClick={() => setDismissed(true)}
              aria-label="Dismiss Briefing"
              className="text-[var(--text-muted)] hover:text-[var(--text-primary)] p-1.5 rounded-lg hover:bg-[var(--bg-elevated)] transition-colors"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Executive Summary Narrative */}
        <div className="p-4 rounded-xl bg-[var(--bg-elevated)]/40 border border-[var(--border)] mb-6 text-sm md:text-base text-[var(--text-secondary)] leading-relaxed">
          <p>{briefing.summary_narrative}</p>
        </div>

        {/* Executive Audio Briefing Player */}
        <div className="mb-6">
          <ExecutiveAudioPlayer textToSpeak={briefing.summary_narrative} voiceUrl={audioUrl} />
        </div>

        {/* KPI Grid */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
          {briefing.kpis.map((kpi, idx) => (
            <div
              key={idx}
              className="p-3.5 rounded-xl bg-[var(--bg-surface)] border border-[var(--border-glass)] flex flex-col justify-between"
            >
              <span className="text-xs font-mono text-[var(--text-muted)]">{kpi.label}</span>
              <div className="my-1.5 flex items-baseline justify-between">
                <span className="text-lg font-semibold text-[var(--text-primary)]">{kpi.value}</span>
                <span
                  className={`text-xs font-mono flex items-center gap-0.5 ${
                    kpi.trend === "up" ? "text-emerald-400" : "text-amber-400"
                  }`}
                >
                  {kpi.trend === "up" ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />}
                  {kpi.change_pct > 0 ? `+${kpi.change_pct}%` : `${kpi.change_pct}%`}
                </span>
              </div>
              <p className="text-[11px] text-[var(--text-secondary)] line-clamp-2">{kpi.insight}</p>
            </div>
          ))}
        </div>

        {/* Anomaly Alerts */}
        {briefing.anomalies.length > 0 && (
          <div className="mb-6 space-y-2">
            {briefing.anomalies.map((anom, idx) => (
              <div
                key={idx}
                className="p-3 rounded-xl bg-amber-500/10 border border-amber-500/20 flex items-start gap-3 text-xs md:text-sm text-amber-200"
              >
                <AlertTriangle className="w-4 h-4 text-amber-400 flex-shrink-0 mt-0.5" />
                <div>
                  <span className="font-semibold">{anom.title}: </span>
                  <span>{anom.description}</span>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Proactive Insight Prompts */}
        <div className="pt-2 border-t border-[var(--border)]">
          <span className="text-xs font-mono text-[var(--accent-blue)] flex items-center gap-1.5 mb-2">
            <Sparkles className="w-3.5 h-3.5" /> Recommended Follow-up Queries:
          </span>
          <div className="flex flex-wrap gap-2">
            {briefing.proactive_insights.map((query, idx) => (
              <button
                key={idx}
                type="button"
                onClick={() => onSelectInsight?.(query)}
                className="text-xs px-3 py-1.5 rounded-lg bg-[var(--bg-glass)] hover:bg-[var(--accent-blue)]/15 border border-[var(--border-glass)] hover:border-[var(--accent-blue)]/40 text-[var(--text-secondary)] hover:text-[var(--accent-blue)] transition-all flex items-center gap-1 group"
              >
                <span>{query}</span>
                <ChevronRight className="w-3 h-3 text-[var(--text-muted)] group-hover:text-[var(--accent-blue)] transition-colors" />
              </button>
            ))}
          </div>
        </div>
      </motion.div>
    </AnimatePresence>
  );
}
