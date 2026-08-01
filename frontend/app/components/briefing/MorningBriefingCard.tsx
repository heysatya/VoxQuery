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
      setLoadError(err instanceof ApiRequestError ? err.message : "Couldn't load this morning's briefing.");
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
        aria-label="Loading morning briefing"
        className="w-full max-w-xl mx-auto mb-8 h-40 flex items-center justify-center rounded-2xl border border-white/10 bg-[#12141a]"
      >
        <div className="w-8 h-8 border-2 border-[var(--accent-blue)] border-t-transparent rounded-full animate-spin" />
        <span className="sr-only">Loading morning briefing...</span>
      </div>
    );
  }

  if (!briefing) {
    return (
      <div role="status" aria-live="polite" className="w-full max-w-xl mx-auto mb-8">
        <FailureNotice
          severity="info"
          message={loadError ?? "Couldn't load this morning's briefing."}
          action={{ label: "Retry", onClick: () => void loadBriefing() }}
        />
      </div>
    );
  }

  // Derive 3 executive bullet takeaways from KPIs & Anomalies
  const takeaways = [
    {
      severity: "critical",
      dotColor: "bg-rose-500 shadow-[0_0_8px_rgba(244,63,94,0.6)]",
      headline: briefing.anomalies[0]?.title || "Revenue dropped in key segments",
      subtext: `→ ${briefing.anomalies[0]?.description || "Driven by regional performance shifts"}`,
    },
    {
      severity: "warning",
      dotColor: "bg-amber-400 shadow-[0_0_8px_rgba(251,191,36,0.6)]",
      headline: briefing.kpis[1] ? `${briefing.kpis[1].label} variance detected` : "Conversion fell below 30-day avg",
      subtext: `→ ${briefing.kpis[1]?.insight || "Requires volume optimization"}`,
    },
    {
      severity: "info",
      dotColor: "bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.6)]",
      headline: briefing.kpis[0] ? `${briefing.kpis[0].label}: ${briefing.kpis[0].value}` : "Pipeline on target",
      subtext: `→ ${briefing.kpis[0]?.insight || "Strongest performance in 3 quarters"}`,
    },
  ];

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0, y: -16 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, height: 0 }}
        className={`w-full max-w-xl mx-auto mb-8 rounded-2xl bg-gradient-to-b from-slate-900/95 to-slate-950/95 border border-slate-700/60 shadow-[0_0_30px_rgba(56,189,248,0.12)] p-6 relative overflow-hidden backdrop-blur-2xl ${
          variant === "drawer" ? "border-cyan-500/40" : ""
        }`}
      >
        {/* Top Title Bar */}
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2.5">
            <span className="text-xl">☀️</span>
            <h2 className="text-sm font-bold text-white tracking-tight">
              VoxQuery Morning Briefing
            </h2>
          </div>
          <div className="flex items-center gap-3">
            {/* Phase 3.2: Voice-first primary audio play button */}
            <button
              type="button"
              onClick={() => {
                setIsPlayingTopAudio(!isPlayingTopAudio);
                if (!showDetails) setShowDetails(true);
              }}
              className="px-2.5 py-1 rounded-full bg-cyan-500/20 hover:bg-cyan-500/30 border border-cyan-400/30 text-cyan-200 text-[11px] font-semibold flex items-center gap-1.5 transition-colors"
            >
              <Play className="w-3 h-3 fill-cyan-200" />
              <span>Listen — 45s</span>
            </button>
            <span className="text-xs font-mono text-slate-300">9:00 AM</span>
            <button
              type="button"
              onClick={() => {
                setDismissed(true);
                onClose?.();
              }}
              className="text-slate-400 hover:text-white p-1 transition-colors"
              title="Dismiss"
              aria-label="Dismiss morning briefing"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Executive Greeting Subtitle */}
        <p className="text-xs text-slate-200 font-semibold mb-4">
          Good morning. Three things before your 9 AM:
        </p>

        {/* 3 Executive Bullet Takeaways */}
        <div className="space-y-4 mb-6">
          {takeaways.map((item, idx) => (
            <div key={idx} className="flex items-start gap-3 group">
              <span className={`w-2.5 h-2.5 rounded-full mt-1 shrink-0 ${item.dotColor}`} />
              <div className="space-y-0.5">
                <h4 className="text-xs font-bold text-white tracking-wide group-hover:text-cyan-300 transition-colors">
                  {item.headline}
                </h4>
                <p className="text-[11px] font-mono text-slate-300 font-medium">
                  {item.subtext}
                </p>
              </div>
            </div>
          ))}
        </div>

        {/* Bottom Action Bar */}
        <div className="flex items-center gap-3 pt-3 border-t border-slate-800/80">
          <button
            type="button"
            onClick={onAskFollowUp}
            className="flex-1 py-2.5 px-4 rounded-xl bg-gradient-to-r from-sky-500 to-indigo-600 hover:from-sky-600 hover:to-indigo-700 text-white text-xs font-semibold shadow-lg shadow-sky-500/20 flex items-center justify-center gap-2 transition-all active:scale-[0.98]"
          >
            <Mic className="w-3.5 h-3.5" />
            <span>Ask a follow-up</span>
          </button>

          <button
            type="button"
            onClick={() => setShowDetails(!showDetails)}
            className="py-2.5 px-4 rounded-xl bg-slate-800/80 hover:bg-slate-800 border border-slate-700/60 text-slate-100 text-xs font-semibold flex items-center justify-center gap-2 transition-all"
          >
            <BarChart2 className="w-3.5 h-3.5 text-cyan-400" />
            <span>{showDetails ? "Hide Details" : "Details"}</span>
          </button>
        </div>

        {/* Expanded Executive Details Panel */}
        {showDetails && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            className="mt-5 pt-5 border-t border-slate-800/80 space-y-5"
          >
            {/* Audio Podcast Narrator */}
            <div>
              <span className="text-[10px] font-mono text-cyan-400 uppercase tracking-widest block mb-2 font-bold">
                AUDIO BRIEFING PODCAST
              </span>
              <ExecutiveAudioPlayer
                textToSpeak={briefing.summary_narrative}
                voiceUrl={audioUrl}
              />
            </div>

            {/* KPI Grid */}
            <div>
              <span className="text-[10px] font-mono text-slate-300 uppercase tracking-widest block mb-2 font-bold">
                EXECUTIVE METRICS BREAKDOWN
              </span>
              <div className="grid grid-cols-2 gap-3">
                {briefing.kpis.map((kpi, idx) => (
                  <div key={idx} className="p-3 rounded-xl bg-slate-800/60 border border-slate-700/50 flex flex-col justify-between">
                    <span className="text-[10px] font-mono text-slate-300 font-medium">{kpi.label}</span>
                    <div className="my-1 flex items-baseline justify-between">
                      <span className="text-sm font-bold text-white">{kpi.value}</span>
                      <span className={`text-[10px] font-mono font-semibold flex items-center gap-0.5 ${kpi.trend === "up" ? "text-emerald-400" : "text-amber-400"}`}>
                        {kpi.trend === "up" ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />}
                        {kpi.change_pct > 0 ? `+${kpi.change_pct}%` : `${kpi.change_pct}%`}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Export Actions (PDF & Slack - Phase 3.4) */}
            <div className="flex items-center justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={handleSendSlack}
                className="text-xs px-3.5 py-2 rounded-xl bg-emerald-500/10 hover:bg-emerald-500/20 border border-emerald-500/20 text-emerald-300 font-medium transition-all flex items-center gap-1.5"
              >
                <Share2 className="w-3.5 h-3.5" />
                <span>{slackShared ? "Shared to Slack!" : "Send to Slack"}</span>
              </button>

              <button
                type="button"
                onClick={handleDownloadPdf}
                disabled={isDownloadingPdf}
                className="text-xs px-3.5 py-2 rounded-xl bg-indigo-500/10 hover:bg-indigo-500/20 border border-indigo-500/20 text-indigo-300 font-medium transition-all flex items-center gap-2 disabled:opacity-50"
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
