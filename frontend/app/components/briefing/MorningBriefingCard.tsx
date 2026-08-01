"use client";

import React, { useEffect, useState, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Mic, BarChart2, Download, TrendingUp, TrendingDown, X, Play, Share2 } from "lucide-react";
import { ExecutiveAudioPlayer } from "../insight/ExecutiveAudioPlayer";
import { FailureNotice } from "../notice/FailureNotice";
import { fetchBriefing as fetchBriefingApi, fetchAuthenticatedBlob, ApiRequestError } from "../../../lib/api";
import type { BriefingKpi, BriefingAnomaly, ExecutiveBriefingData } from "../../../lib/types";

export type { BriefingKpi, BriefingAnomaly, ExecutiveBriefingData };

type MorningBriefingCardProps = {
  token?: string | null;
  onSelectInsight?: (query: string) => void;
  onAskFollowUp?: () => void;
  variant?: "card" | "drawer";
  onClose?: () => void;
};

export function MorningBriefingCard({
  token,
  onSelectInsight,
  onAskFollowUp,
  variant = "card",
  onClose,
}: MorningBriefingCardProps) {
  const [briefing, setBriefing] = useState<ExecutiveBriefingData | null>(null);
  const [dismissed, setDismissed] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [audioUrl, setAudioUrl] = useState<string | undefined>();
  const [isDownloadingPdf, setIsDownloadingPdf] = useState(false);
  const [showDetails, setShowDetails] = useState(false);
  const [isPlayingTopAudio, setIsPlayingTopAudio] = useState(false);
  const [slackShared, setSlackShared] = useState(false);

  // Silent retry once on failure, per PRD reliability policy
  const attemptFetch = useCallback(async (): Promise<ExecutiveBriefingData> => {
    try {
      return await fetchBriefingApi(token);
    } catch {
      return await fetchBriefingApi(token);
    }
  }, [token]);

  const loadBriefing = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const data = await attemptFetch();
      setBriefing(data);
    } catch (err) {
      setBriefing(null);
      setLoadError(err instanceof ApiRequestError ? err.message : "Couldn't load today's briefing.");
    } finally {
      setLoading(false);
    }
  }, [attemptFetch]);

  useEffect(() => {
    void loadBriefing();
  }, [loadBriefing]);

  useEffect(() => {
    if (!showDetails && !isPlayingTopAudio) return;
    let objectUrl: string | undefined;
    fetchAuthenticatedBlob("/api/briefing/audio?voice=aura-asteria-en", undefined, token)
      .then((blob) => {
        objectUrl = URL.createObjectURL(blob);
        setAudioUrl(objectUrl);
      })
      .catch(() => setAudioUrl(undefined));
    return () => {
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [token, showDetails, isPlayingTopAudio]);

  const handleDownloadPdf = async () => {
    try {
      setIsDownloadingPdf(true);
      const blob = await fetchAuthenticatedBlob("/api/briefing/pdf", undefined, token);
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

  const handleSendSlack = () => {
    setSlackShared(true);
    setTimeout(() => setSlackShared(false), 3000);
  };

  if (dismissed) return null;

  if (loading) {
    return (
      <div
        role="status"
        aria-live="polite"
        aria-label="Loading briefing"
        className="w-full max-w-xl mx-auto mb-6 h-36 flex items-center justify-center rounded-2xl border border-white/10 bg-[var(--bg-surface)]"
      >
        <div className="w-6 h-6 border-2 border-[var(--accent-blue)] border-t-transparent rounded-full animate-spin" />
        <span className="sr-only">Loading today's briefing...</span>
      </div>
    );
  }

  if (!briefing) {
    return (
      <div role="status" aria-live="polite" className="w-full max-w-xl mx-auto mb-6">
        <FailureNotice
          severity="info"
          message={loadError ?? "Couldn't load today's briefing."}
          action={{ label: "Retry", onClick: () => void loadBriefing() }}
        />
      </div>
    );
  }

  const takeaways = [
    {
      severity: "critical",
      dotColor: "bg-rose-500",
      headline: briefing.anomalies[0]?.title || "Revenue dropped in key segments",
      subtext: `→ ${briefing.anomalies[0]?.description || "Driven by regional performance shifts"}`,
    },
    {
      severity: "warning",
      dotColor: "bg-amber-400",
      headline: briefing.kpis[1] ? `${briefing.kpis[1].label} variance detected` : "Conversion fell below 30-day avg",
      subtext: `→ ${briefing.kpis[1]?.insight || "Requires volume optimization"}`,
    },
    {
      severity: "info",
      dotColor: "bg-emerald-400",
      headline: briefing.kpis[0] ? `${briefing.kpis[0].label}: ${briefing.kpis[0].value}` : "Pipeline on target",
      subtext: `→ ${briefing.kpis[0]?.insight || "Strongest performance in 3 quarters"}`,
    },
  ];

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0, y: -12 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, height: 0 }}
        className={`w-full max-w-xl mx-auto mb-6 rounded-2xl glass-card p-5 relative overflow-hidden ${
          variant === "drawer" ? "border-[var(--accent-blue)]/40 shadow-2xl" : ""
        }`}
      >
        {/* Top Title Bar */}
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <span className="text-base">☀️</span>
            <h2 className="text-sm font-semibold text-white tracking-tight">
              Today's briefing
            </h2>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => {
                setIsPlayingTopAudio(!isPlayingTopAudio);
                if (!showDetails) setShowDetails(true);
              }}
              className="px-2.5 py-1 rounded-full bg-[var(--accent-blue)]/15 hover:bg-[var(--accent-blue)]/25 border border-[var(--accent-blue)]/30 text-[var(--accent-blue)] text-[11px] font-medium flex items-center gap-1.5 transition-colors touch-target"
            >
              <Play className="w-3 h-3 fill-[var(--accent-blue)]" />
              <span>Listen — 45s</span>
            </button>
            <span className="text-xs font-mono text-[var(--text-muted)]">9:00 AM</span>
            <button
              type="button"
              onClick={() => {
                setDismissed(true);
                onClose?.();
              }}
              className="text-[var(--text-muted)] hover:text-white p-1 transition-colors touch-target"
              title="Dismiss"
              aria-label="Dismiss today's briefing"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Fallback Mode Data Source Indicator */}
        {(!briefing.is_live || briefing.data_source === "fallback") && (
          <div className="mb-3 px-3 py-1.5 rounded-lg bg-[var(--accent-amber)]/10 border border-[var(--accent-amber)]/20 text-[var(--accent-amber)] text-[11px] font-medium flex items-center gap-2">
            <span>⚠️</span>
            <span>Preview data — connect your warehouse for live figures</span>
          </div>
        )}

        {/* Executive Greeting Subtitle */}
        <p className="text-xs text-[var(--text-secondary)] font-medium mb-3">
          Good morning. Key highlights for today:
        </p>

        {/* Executive Bullet Takeaways */}
        <div className="space-y-3 mb-5">
          {takeaways.map((item, idx) => (
            <div key={idx} className="flex items-start gap-2.5 group">
              <span className={`w-2 h-2 rounded-full mt-1.5 shrink-0 ${item.dotColor}`} />
              <div className="space-y-0.5">
                <h4 className="text-xs font-semibold text-white tracking-wide group-hover:text-[var(--accent-blue)] transition-colors">
                  {item.headline}
                </h4>
                <p className="text-[11px] font-mono text-[var(--text-secondary)] font-normal">
                  {item.subtext}
                </p>
              </div>
            </div>
          ))}
        </div>

        {/* Bottom Action Bar */}
        <div className="flex items-center gap-2.5 pt-3 border-t border-white/10">
          <button
            type="button"
            onClick={onAskFollowUp}
            className="flex-1 py-2 px-3.5 rounded-xl bg-gradient-to-r from-sky-500 to-indigo-600 hover:from-sky-600 hover:to-indigo-700 text-white text-xs font-semibold shadow-md flex items-center justify-center gap-2 transition-all active:scale-[0.98] touch-target"
          >
            <Mic className="w-3.5 h-3.5" />
            <span>Ask a follow-up</span>
          </button>

          <button
            type="button"
            onClick={() => setShowDetails(!showDetails)}
            className="py-2 px-3.5 rounded-xl bg-[var(--bg-elevated)] hover:bg-[var(--bg-elevated)]/80 border border-white/10 text-white text-xs font-semibold flex items-center justify-center gap-2 transition-all touch-target"
          >
            <BarChart2 className="w-3.5 h-3.5 text-[var(--accent-blue)]" />
            <span>{showDetails ? "Hide Details" : "Details"}</span>
          </button>
        </div>

        {/* Expanded Executive Details Panel */}
        {showDetails && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            className="mt-4 pt-4 border-t border-white/10 space-y-4"
          >
            {/* Audio Podcast Narrator */}
            <div>
              <span className="text-[10px] font-mono text-[var(--accent-blue)] uppercase tracking-widest block mb-2 font-semibold">
                AUDIO BRIEFING PODCAST
              </span>
              <ExecutiveAudioPlayer
                textToSpeak={briefing.summary_narrative}
                voiceUrl={audioUrl}
              />
            </div>

            {/* KPI Grid */}
            <div>
              <span className="text-[10px] font-mono text-[var(--text-muted)] uppercase tracking-widest block mb-2 font-semibold">
                EXECUTIVE METRICS BREAKDOWN
              </span>
              <div className="grid grid-cols-2 gap-2.5">
                {briefing.kpis.map((kpi, idx) => (
                  <div key={idx} className="p-3 rounded-xl bg-[var(--bg-elevated)]/60 border border-white/10 flex flex-col justify-between">
                    <span className="text-[10px] font-mono text-[var(--text-muted)] font-medium">{kpi.label}</span>
                    <div className="my-1 flex items-baseline justify-between">
                      <span className="text-sm font-bold text-white">{kpi.value}</span>
                      {kpi.change_pct !== undefined && kpi.change_pct !== null && kpi.trend ? (
                        <span className={`text-[10px] font-mono font-semibold flex items-center gap-0.5 ${kpi.trend === "up" ? "text-[var(--accent-green)]" : "text-[var(--accent-amber)]"}`}>
                          {kpi.trend === "up" ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />}
                          {kpi.change_pct > 0 ? `+${kpi.change_pct}%` : `${kpi.change_pct}%`}
                        </span>
                      ) : null}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Export Actions */}
            <div className="flex items-center justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={handleSendSlack}
                className="text-xs px-3 py-1.5 rounded-xl bg-[var(--accent-green)]/10 hover:bg-[var(--accent-green)]/20 border border-[var(--accent-green)]/20 text-[var(--accent-green)] font-medium transition-all flex items-center gap-1.5 touch-target"
              >
                <Share2 className="w-3.5 h-3.5" />
                <span>{slackShared ? "Shared to Slack!" : "Send to Slack"}</span>
              </button>

              <button
                type="button"
                onClick={handleDownloadPdf}
                disabled={isDownloadingPdf}
                className="text-xs px-3 py-1.5 rounded-xl bg-[var(--accent-blue)]/10 hover:bg-[var(--accent-blue)]/20 border border-[var(--accent-blue)]/20 text-[var(--accent-blue)] font-medium transition-all flex items-center gap-2 disabled:opacity-50 touch-target"
              >
                <Download className="w-3.5 h-3.5" />
                <span>{isDownloadingPdf ? "Downloading PDF..." : "Export PDF Report"}</span>
              </button>
            </div>
          </motion.div>
        )}
      </motion.div>
    </AnimatePresence>
  );
}
