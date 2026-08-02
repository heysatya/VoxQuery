"use client";

import React, { useEffect, useState, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Mic, BarChart2, Download, TrendingUp, TrendingDown, X, Play, Sparkles, ChevronRight, AlertTriangle } from "lucide-react";
import { ExecutiveAudioPlayer } from "../insight/ExecutiveAudioPlayer";
import { FailureNotice } from "../notice/FailureNotice";
import { fetchBriefing as fetchBriefingApi, fetchAuthenticatedBlob, ApiRequestError } from "../../../lib/api";
import type { BriefingKpi, BriefingAnomaly, ExecutiveBriefingData } from "../../../lib/types";

export type { BriefingKpi, BriefingAnomaly, ExecutiveBriefingData };

type MorningBriefingCardProps = {
  token?: string | null;
  getToken?: (options?: { skipCache?: boolean }) => Promise<string | null>;
  briefing?: ExecutiveBriefingData | null;
  onBriefingLoaded?: (briefing: ExecutiveBriefingData) => void;
  onSelectInsight?: (query: string) => void;
  onAskFollowUp?: () => void;
  variant?: "compact" | "card" | "drawer";
  onClose?: () => void;
  onOpenFullBriefing?: () => void;
  onAuthExpired?: () => void;
  actionsDisabled?: boolean;
};

export function MorningBriefingCard({
  token,
  getToken,
  briefing: providedBriefing,
  onBriefingLoaded,
  onSelectInsight,
  onAskFollowUp,
  variant = "compact",
  onClose,
  onOpenFullBriefing,
  onAuthExpired,
  actionsDisabled = false,
}: MorningBriefingCardProps) {
  const [briefing, setBriefing] = useState<ExecutiveBriefingData | null>(providedBriefing ?? null);
  const [dismissed, setDismissed] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [audioUrl, setAudioUrl] = useState<string | undefined>();
  const [isDownloadingPdf, setIsDownloadingPdf] = useState(false);
  const [showDetails, setShowDetails] = useState(false);
  const [isPlayingTopAudio, setIsPlayingTopAudio] = useState(false);
  const [authExpired, setAuthExpired] = useState(false);

  const attemptFetch = useCallback(async (): Promise<ExecutiveBriefingData> => {
    if (!token) {
      throw new ApiRequestError(401, "Sign-in is required to load today's briefing.", "auth_missing");
    }
    try {
      return await fetchBriefingApi(token);
    } catch (error) {
      if (!(error instanceof ApiRequestError) || error.status !== 401 || !getToken) {
        throw error;
      }
      const refreshedToken = await getToken({ skipCache: true });
      if (!refreshedToken) {
        throw error;
      }
      return fetchBriefingApi(refreshedToken);
    }
  }, [getToken, token]);

  const loadBriefing = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const data = await attemptFetch();
      setBriefing(data);
      setAuthExpired(false);
      onBriefingLoaded?.(data);
    } catch (err) {
      setBriefing(null);
      const isAuthFailure = err instanceof ApiRequestError && err.status === 401;
      setAuthExpired(isAuthFailure);
      setLoadError(
        isAuthFailure
          ? "Your sign-in session expired. Sign in again to load today's briefing."
          : err instanceof ApiRequestError
          ? err.message
          : "Couldn't load today's briefing."
      );
    } finally {
      setLoading(false);
    }
  }, [attemptFetch, onBriefingLoaded]);

  useEffect(() => {
    if (providedBriefing) {
      setBriefing(providedBriefing);
      setLoading(false);
      return;
    }
    if (!token) return;
    void loadBriefing();
  }, [loadBriefing, providedBriefing, token]);

  const fetchBriefingBlob = useCallback(async (path: string): Promise<Blob> => {
    try {
      return await fetchAuthenticatedBlob(path, undefined, token);
    } catch (error) {
      if (!(error instanceof ApiRequestError) || error.status !== 401 || !getToken) {
        throw error;
      }
      const refreshedToken = await getToken({ skipCache: true });
      if (!refreshedToken) throw error;
      return fetchAuthenticatedBlob(path, undefined, refreshedToken);
    }
  }, [getToken, token]);

  useEffect(() => {
    if (!showDetails && !isPlayingTopAudio) return;
    let objectUrl: string | undefined;
    fetchBriefingBlob("/api/briefing/audio?voice=aura-asteria-en")
      .then((blob) => {
        objectUrl = URL.createObjectURL(blob);
        setAudioUrl(objectUrl);
      })
      .catch(() => setAudioUrl(undefined));
    return () => {
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [fetchBriefingBlob, showDetails, isPlayingTopAudio]);

  const handleDownloadPdf = async () => {
    try {
      setIsDownloadingPdf(true);
      const blob = await fetchBriefingBlob("/api/briefing/pdf");
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

  if (dismissed) return null;

  if (loading) {
    return (
      <div
        data-testid="briefing-summary"
        role="status"
        aria-live="polite"
        aria-label="Loading briefing"
        className="w-full max-w-xl mx-auto mb-6 p-5 rounded-2xl border border-white/10 bg-[var(--bg-surface)] space-y-3"
      >
        <div className="flex items-center justify-between">
          <div className="h-4 w-32 bg-white/10 rounded animate-pulse" />
          <div className="h-4 w-16 bg-white/10 rounded animate-pulse" />
        </div>
        <div className="h-3 w-48 bg-white/5 rounded animate-pulse" />
        <div className="space-y-2 pt-2">
          <div className="h-3 w-full bg-white/5 rounded animate-pulse" />
          <div className="h-3 w-4/5 bg-white/5 rounded animate-pulse" />
        </div>
        <span className="sr-only">Loading today's briefing...</span>
      </div>
    );
  }

  if (!briefing) {
    return (
      <div data-testid="briefing-summary" role="status" aria-live="polite" className="w-full max-w-xl mx-auto mb-6">
        <FailureNotice
          severity={authExpired ? "error" : "info"}
          message={loadError ?? "Couldn't load today's briefing."}
          action={{
            label: authExpired ? "Sign in again" : "Retry",
            onClick: authExpired && onAuthExpired ? onAuthExpired : () => void loadBriefing()
          }}
        />
      </div>
    );
  }

  const anomalyCount = briefing.anomalies?.length ?? 0;
  const isPreviewData = briefing.is_live !== true || briefing.data_source !== "live";
  const hasLiveData = briefing.is_live === true && briefing.kpis.length > 0;

  const takeaways = briefing.anomalies && briefing.anomalies.length > 0
    ? briefing.anomalies.map((anom) => ({
        severity: anom.severity || "warning",
        dotColor: anom.severity === "critical" ? "bg-rose-500" : "bg-amber-400",
        headline: anom.title,
        subtext: `→ ${anom.description}`,
      }))
    : [
        {
          severity: "info",
          dotColor: "bg-emerald-400",
          headline: briefing.kpis[0] ? `${briefing.kpis[0].label}: ${briefing.kpis[0].value}` : "All primary metrics on track",
          subtext: `→ ${briefing.kpis[0]?.insight || "Performance matches 30-day benchmarks"}`,
        },
        ...(briefing.kpis[1]
          ? [
              {
                severity: "info",
                dotColor: "bg-sky-400",
                headline: `${briefing.kpis[1].label}: ${briefing.kpis[1].value}`,
                subtext: `→ ${briefing.kpis[1].insight || "Stable trajectory"}`,
              },
            ]
          : []),
      ];

  /* ── COMPACT SUMMARY PRESENTATION (for Ready screen) ────────── */
  const visibleTakeaways = hasLiveData ? takeaways : [];

  if (variant === "compact") {
    return (
      <motion.div
        data-testid="briefing-summary"
        initial={{ opacity: 0, y: -8 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, height: 0 }}
        className="w-full max-w-xl mx-auto mb-6 rounded-2xl glass-card p-5 relative overflow-hidden border border-white/10 bg-[#10141C]/90 shadow-[0_12px_40px_rgba(0,0,0,0.22)] hover:border-[var(--accent-blue)]/30 transition-all"
      >
        {/* Compact Header Bar */}
        <div className="flex items-center justify-between mb-2.5">
          <div className="flex items-center gap-2">
            <Sparkles className="w-4 h-4 text-[var(--accent-amber)]" aria-hidden="true" />
            <h3 className="text-xs font-semibold text-white tracking-tight">
              Today's business pulse
            </h3>
            <span
              className={`text-[10px] font-mono px-2 py-0.5 rounded-full border font-medium ${
                !hasLiveData
                  ? "bg-amber-500/10 text-amber-400 border-amber-500/20"
                  : anomalyCount === 0
                  ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/20"
                  : anomalyCount === 1
                  ? "bg-amber-500/10 text-amber-400 border-amber-500/20"
                  : "bg-rose-500/10 text-rose-400 border-rose-500/20"
              }`}
            >
              {!hasLiveData ? "Unavailable" : anomalyCount === 0 ? "Clear" : `${anomalyCount} ${anomalyCount === 1 ? "flag" : "flags"}`}
            </span>
          </div>

          <button
            type="button"
            onClick={onOpenFullBriefing}
            className="px-2.5 py-1 rounded-full bg-[var(--accent-blue)]/15 hover:bg-[var(--accent-blue)]/25 border border-[var(--accent-blue)]/30 text-[var(--accent-blue)] text-[11px] font-medium flex items-center gap-1 transition-colors touch-target"
            aria-label="View full briefing details"
          >
            <span>View briefing</span>
            <ChevronRight className="w-3 h-3" />
          </button>
        </div>

        {/* Preview Data Notice */}
        {isPreviewData && (
          <div className="mb-2.5 px-2.5 py-1 rounded-md bg-[var(--accent-amber)]/10 border border-[var(--accent-amber)]/20 text-[var(--accent-amber)] text-[10px] font-medium flex items-center gap-1.5">
            <AlertTriangle className="w-3 h-3 shrink-0" />
            <span>Live workspace not connected - no business figures are being shown.</span>
          </div>
        )}

        {!hasLiveData && (
          <div className="mb-3 rounded-lg border border-white/10 bg-[var(--bg-base)]/50 px-3 py-3">
            <p className="text-xs font-medium text-white">Your business pulse is not available yet.</p>
            <p className="text-[11px] text-[var(--text-secondary)] mt-1">Connect a live workspace to see verified changes, risks, and recommended actions.</p>
          </div>
        )}

        {/* Key takeaways */}
        <div className="space-y-2 mb-3">
          {visibleTakeaways.slice(0, 2).map((item, idx) => (
            <button
              key={idx}
              type="button"
              className="w-full text-left flex items-start gap-2 group cursor-pointer rounded-lg focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--accent-blue)]"
              onClick={onOpenFullBriefing}
              aria-label={`Open details for ${item.headline}`}
            >
              <span className={`w-1.5 h-1.5 rounded-full mt-1.5 shrink-0 ${item.dotColor}`} />
              <div className="space-y-0.5 min-w-0 flex-1">
                <h4 className="text-xs font-medium text-white tracking-wide truncate group-hover:text-[var(--accent-blue)] transition-colors">
                  {item.headline}
                </h4>
                <p className="text-[11px] font-mono text-[var(--text-secondary)] font-normal truncate">
                  {item.subtext}
                </p>
              </div>
            </button>
          ))}
        </div>

        {/* Quick Actions */}
        <div className="flex items-center gap-2 pt-2.5 border-t border-white/5">
          <button
            type="button"
            onClick={onAskFollowUp}
            disabled={actionsDisabled}
            className="flex-1 py-1.5 px-3 rounded-lg bg-[var(--bg-elevated)] hover:bg-[var(--bg-elevated)]/80 border border-white/10 text-white text-[11px] font-medium flex items-center justify-center gap-1.5 transition-all touch-target disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <Mic className="w-3 h-3 text-[var(--accent-blue)]" />
            <span>Ask follow-up</span>
          </button>
          <button
            type="button"
            onClick={onOpenFullBriefing}
            className="py-1.5 px-3 rounded-lg bg-[var(--bg-surface)] hover:bg-[var(--bg-elevated)] border border-white/10 text-[var(--text-secondary)] hover:text-white text-[11px] font-medium flex items-center justify-center gap-1.5 transition-all touch-target"
          >
            <BarChart2 className="w-3 h-3 text-[var(--accent-blue)]" />
            <span>View details</span>
          </button>
        </div>
      </motion.div>
    );
  }

  /* ── FULL CARD & DRAWER PRESENTATION ──────────────────────────── */
  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0, y: -12 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, height: 0 }}
        className={`w-full max-w-xl mx-auto mb-6 rounded-2xl glass-card p-5 relative overflow-hidden ${
          variant === "drawer" ? "border-[var(--accent-blue)]/40 shadow-2xl bg-[#0F131C]" : ""
        }`}
      >
        {/* Top Title Bar */}
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <Sparkles className="w-4 h-4 text-[var(--accent-amber)]" aria-hidden="true" />
            <h2 className="text-sm font-semibold text-white tracking-tight">
              Today's business pulse
            </h2>
            <span
              className={`text-[10px] font-mono px-2 py-0.5 rounded-full border font-medium ${
                !hasLiveData
                  ? "bg-amber-500/10 text-amber-400 border-amber-500/20"
                  : anomalyCount === 0
                  ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/20"
                  : "bg-amber-500/10 text-amber-400 border-amber-500/20"
              }`}
            >
              {!hasLiveData ? "Unavailable" : anomalyCount === 0 ? "Clear" : `${anomalyCount} ${anomalyCount === 1 ? "flag" : "flags"}`}
            </span>
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
              <span>Listen - 45s</span>
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
        {isPreviewData && (
          <div className="mb-3 px-3 py-1.5 rounded-lg bg-[var(--accent-amber)]/10 border border-[var(--accent-amber)]/20 text-[var(--accent-amber)] text-[11px] font-medium flex items-center gap-2">
            <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
            <span>Live workspace not connected - no business figures are being shown.</span>
          </div>
        )}

        {/* Executive Greeting Subtitle */}
        <p className="text-xs text-[var(--text-secondary)] font-medium mb-3">
          {hasLiveData ? "What changed and what may need attention:" : "Connect your workspace to generate a verified business pulse."}
        </p>

        {!hasLiveData && (
          <div className="mb-5 rounded-xl border border-white/10 bg-[var(--bg-base)]/50 px-4 py-4">
            <p className="text-sm font-semibold text-white">No verified business figures are available.</p>
            <p className="text-xs text-[var(--text-secondary)] mt-1">Once a live workspace is connected, this briefing will summarize changes, risks, and recommended actions.</p>
          </div>
        )}

        {/* Executive Bullet Takeaways */}
        <div className="space-y-3 mb-5">
          {visibleTakeaways.map((item, idx) => (
            <div
              key={idx}
              className="flex items-start gap-2.5 group cursor-pointer"
              onClick={() => onSelectInsight?.(item.headline)}
            >
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
            disabled={actionsDisabled}
            className="flex-1 py-2 px-3.5 rounded-xl bg-gradient-to-r from-sky-500 to-indigo-600 hover:from-sky-600 hover:to-indigo-700 text-white text-xs font-semibold shadow-md flex items-center justify-center gap-2 transition-all active:scale-[0.98] touch-target disabled:opacity-50 disabled:cursor-not-allowed"
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
            <span>{showDetails ? "Hide Details" : "KPI Details"}</span>
          </button>
        </div>

        {/* Expanded Executive Details Panel */}
        {(showDetails || variant === "drawer") && (
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
                BUSINESS SIGNALS
              </span>
              <div className="grid grid-cols-2 gap-2.5">
                {briefing.kpis.map((kpi, idx) => (
                  <div
                    key={idx}
                    className="p-3 rounded-xl bg-[var(--bg-elevated)]/60 border border-white/10 flex flex-col justify-between hover:border-[var(--accent-blue)]/30 transition-colors cursor-pointer"
                    onClick={() => onSelectInsight?.(`Show breakdown for ${kpi.label}`)}
                  >
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
