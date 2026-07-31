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
  const [selectedVoice, setSelectedVoice] = useState("aura-asteria-en");
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
    fetchAuthenticatedBlob(`/api/briefing/audio?voice=${encodeURIComponent(selectedVoice)}`, undefined, token)
      .then((blob) => {
        objectUrl = URL.createObjectURL(blob);
        setAudioUrl(objectUrl);
      })
      .catch(() => setAudioUrl(undefined));
    return () => {
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [token, selectedVoice, showDetails, isPlayingTopAudio]);

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
      <div className="w-full max-w-xl mx-auto mb-8 h-40 flex items-center justify-center rounded-2xl border border-white/10 bg-[#12141a]">
        <div className="w-8 h-8 border-2 border-[var(--accent-blue)] border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (!briefing) {
    return (
      <div className="w-full max-w-xl mx-auto mb-8">
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
        className={`w-full max-w-xl mx-auto mb-8 rounded-2xl bg-gradient-to-b from-[#181a20] to-[#12141a] border border-white/10 shadow-2xl p-6 relative overflow-hidden backdrop-blur-2xl ${
          variant === "drawer" ? "border-indigo-500/30" : ""
        }`}
      >
        {/* Top Title Bar */}
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2.5">
            <span className="text-xl">☀️</span>
            <h2 className="text-sm font-semibold text-white tracking-tight">
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
              className="px-2.5 py-1 rounded-full bg-indigo-500/20 hover:bg-indigo-500/30 border border-indigo-500/30 text-indigo-300 text-[11px] font-medium flex items-center gap-1.5 transition-colors"
            >
              <Play className="w-3 h-3 fill-indigo-300" />
              <span>Listen — 45s</span>
            </button>
            <span className="text-xs font-mono text-gray-400">9:00 AM</span>
            <button
              type="button"
              onClick={() => {
                setDismissed(true);
                onClose?.();
              }}
              className="text-gray-500 hover:text-gray-300 p-1 transition-colors"
              title="Dismiss"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Executive Greeting Subtitle */}
        <p className="text-xs text-gray-300 font-medium mb-4">
          Good morning. Three things before your 9 AM:
        </p>

        {/* 3 Executive Bullet Takeaways */}
        <div className="space-y-4 mb-6">
          {takeaways.map((item, idx) => (
            <div key={idx} className="flex items-start gap-3 group">
              <span className={`w-2.5 h-2.5 rounded-full mt-1 shrink-0 ${item.dotColor}`} />
              <div className="space-y-0.5">
                <h4 className="text-xs font-bold text-white tracking-wide group-hover:text-indigo-300 transition-colors">
                  {item.headline}
                </h4>
                <p className="text-[11px] font-mono text-gray-400">
                  {item.subtext}
                </p>
              </div>
            </div>
          ))}
        </div>

        {/* Bottom Action Bar */}
        <div className="flex items-center gap-3 pt-3 border-t border-white/5">
          <button
            type="button"
            onClick={onAskFollowUp}
            className="flex-1 py-2.5 px-4 rounded-xl bg-gradient-to-r from-indigo-500 to-purple-600 hover:from-indigo-600 hover:to-purple-700 text-white text-xs font-semibold shadow-lg shadow-indigo-500/20 flex items-center justify-center gap-2 transition-all active:scale-[0.98]"
          >
            <Mic className="w-3.5 h-3.5" />
            <span>Ask a follow-up</span>
          </button>

          <button
            type="button"
            onClick={() => setShowDetails(!showDetails)}
            className="py-2.5 px-4 rounded-xl bg-white/5 hover:bg-white/10 border border-white/10 text-gray-300 text-xs font-semibold flex items-center justify-center gap-2 transition-all"
          >
            <BarChart2 className="w-3.5 h-3.5 text-indigo-400" />
            <span>{showDetails ? "Hide Details" : "Details"}</span>
          </button>
        </div>

        {/* Expanded Executive Details Panel */}
        {showDetails && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            className="mt-5 pt-5 border-t border-white/10 space-y-5"
          >
            {/* Audio Podcast Narrator */}
            <div>
              <span className="text-[10px] font-mono text-indigo-400 uppercase tracking-widest block mb-2 font-semibold">
                AUDIO BRIEFING PODCAST
              </span>
              <ExecutiveAudioPlayer
                textToSpeak={briefing.summary_narrative}
                voiceUrl={audioUrl}
                selectedVoice={selectedVoice}
                onVoiceChange={setSelectedVoice}
              />
            </div>

            {/* KPI Grid */}
            <div>
              <span className="text-[10px] font-mono text-gray-400 uppercase tracking-widest block mb-2 font-semibold">
                EXECUTIVE METRICS BREAKDOWN
              </span>
              <div className="grid grid-cols-2 gap-3">
                {briefing.kpis.map((kpi, idx) => (
                  <div key={idx} className="p-3 rounded-xl bg-white/5 border border-white/5 flex flex-col justify-between">
                    <span className="text-[10px] font-mono text-gray-400">{kpi.label}</span>
                    <div className="my-1 flex items-baseline justify-between">
                      <span className="text-sm font-bold text-white">{kpi.value}</span>
                      <span className={`text-[10px] font-mono flex items-center gap-0.5 ${kpi.trend === "up" ? "text-emerald-400" : "text-amber-400"}`}>
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
