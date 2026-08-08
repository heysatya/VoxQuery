"use client";

import React, { useEffect, useState, useCallback, useId } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Mic, BarChart2, Download, TrendingUp, TrendingDown, X, Play, Pause, ChevronRight, AlertTriangle } from "lucide-react";
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

/* ── Signature mark: a bespoke pulse-line glyph, standing in for the generic
   sparkle icon this card used to lead with. Ties literally to "Business
   Pulse" rather than borrowing a stock AI-chat icon. ─────────────────────── */
function PulseMark({ gradientId }: { gradientId: string }) {
  return (
    <span
      className="relative inline-flex items-center justify-center w-7 h-7 rounded-full bg-gradient-to-br from-sky-400/15 to-[#D4AF6A]/10 ring-1 ring-white/[0.08] shrink-0"
      aria-hidden="true"
    >
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none">
        <path
          d="M1.5 13h4.4l2-8.5L13 20l3.3-13.5L18 13h4.5"
          stroke={`url(#${gradientId})`}
          strokeWidth="1.9"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="24" y2="0">
            <stop offset="0%" stopColor="#38BDF8" />
            <stop offset="100%" stopColor="#D4AF6A" />
          </linearGradient>
        </defs>
      </svg>
    </span>
  );
}

const SEVERITY_TONE: Record<
  string,
  { fg: string; dot: string; ring: string; bg: string; glow: string }
> = {
  critical: {
    fg: "text-rose-300",
    dot: "bg-rose-400",
    ring: "ring-rose-500/30",
    bg: "bg-rose-500/10",
    glow: "shadow-[0_0_18px_-6px_rgba(244,63,94,0.6)]",
  },
  warning: {
    fg: "text-amber-300",
    dot: "bg-amber-400",
    ring: "ring-amber-500/25",
    bg: "bg-amber-500/10",
    glow: "shadow-[0_0_18px_-6px_rgba(245,158,11,0.5)]",
  },
  info: {
    fg: "text-emerald-300",
    dot: "bg-emerald-400",
    ring: "ring-emerald-500/25",
    bg: "bg-emerald-500/10",
    glow: "shadow-[0_0_16px_-6px_rgba(16,185,129,0.45)]",
  },
};

/* ── Ledger indicator: replaces the flat colored dot with a directional
   glyph + magnitude, when the anomaly carries structured direction/
   magnitude data. Falls back to a plain tone dot for synthetic "all clear"
   takeaways that have no meaningful direction to show. ────────────────── */
function SeverityGlyph({
  severity,
  direction,
  magnitudePct,
  compact = false,
}: {
  severity: string;
  direction?: "up" | "down" | null;
  magnitudePct?: number | null;
  compact?: boolean;
}) {
  const tone = SEVERITY_TONE[severity] ?? SEVERITY_TONE.info;
  const size = compact ? "w-8 h-8" : "w-11 h-11";

  if (direction && magnitudePct != null) {
    return (
      <div
        className={`shrink-0 flex flex-col items-center justify-center ${size} rounded-xl ${tone.bg} ring-1 ${tone.ring} ${tone.glow}`}
        aria-hidden="true"
      >
        <svg
          width="8"
          height="7"
          viewBox="0 0 9 8"
          className={tone.fg}
          style={{ transform: direction === "down" ? "rotate(180deg)" : undefined }}
        >
          <path d="M4.5 0L9 8H0L4.5 0Z" fill="currentColor" />
        </svg>
        <span className={`font-mono ${compact ? "text-[9px]" : "text-[10px]"} font-semibold tabular-nums mt-0.5 ${tone.fg}`}>
          {Math.round(magnitudePct)}%
        </span>
      </div>
    );
  }

  return (
    <div className={`shrink-0 ${size} rounded-xl ${tone.bg} ring-1 ${tone.ring} flex items-center justify-center`} aria-hidden="true">
      <span className={`w-1.5 h-1.5 rounded-full ${tone.dot}`} />
    </div>
  );
}

type Takeaway = {
  severity: "warning" | "critical" | "info";
  direction?: "up" | "down" | null;
  magnitudePct?: number | null;
  headline: string;
  subtext: string;
  // The query fired when this takeaway is clicked. Falls back to `headline`
  // for KPI-derived takeaways and older anomaly producers that don't set
  // BriefingAnomaly.follow_up_query — but for anomaly-derived takeaways this
  // MUST be the richer, date-anchored prompt, not the bare ranked title
  // ("Biggest revenue spike" alone gives the query pipeline no timeframe to
  // anchor on and reliably produces an unaggregated, duplicate-inflated
  // result instead of a real answer).
  query: string;
  // True for the synthetic "+N more" overflow row, which represents "open
  // the full briefing," not a question — it must never be sent as a query.
  isOverflow?: boolean;
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
  const gradientId = useId();

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

  const [isLoadingAudio, setIsLoadingAudio] = useState(false);

  const handleTogglePlayAudio = async () => {
    if (isPlayingTopAudio) {
      setIsPlayingTopAudio(false);
      return;
    }

    if (!showDetails) setShowDetails(true);

    if (!audioUrl) {
      try {
        setIsLoadingAudio(true);
        const blob = await fetchBriefingBlob("/api/briefing/audio?voice=aura-asteria-en");
        const objectUrl = URL.createObjectURL(blob);
        setAudioUrl(objectUrl);
        setIsPlayingTopAudio(true);
      } catch (err) {
        console.warn("Failed to load briefing audio:", err);
        setIsPlayingTopAudio(false);
      } finally {
        setIsLoadingAudio(false);
      }
    } else {
      setIsPlayingTopAudio(true);
    }
  };

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
        className="w-full max-w-xl mx-auto mb-6 p-5 rounded-2xl border border-white/10 bg-[var(--bg-surface)] relative overflow-hidden space-y-3"
      >
        <div className="pulse-sheen" />
        <div className="flex items-center justify-between relative">
          <div className="h-4 w-36 bg-white/10 rounded-full animate-pulse" />
          <div className="h-4 w-16 bg-white/10 rounded-full animate-pulse" />
        </div>
        <div className="h-3 w-48 bg-white/5 rounded-full animate-pulse relative" />
        <div className="space-y-2 pt-2 relative">
          <div className="h-3 w-full bg-white/5 rounded-full animate-pulse" />
          <div className="h-3 w-4/5 bg-white/5 rounded-full animate-pulse" />
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

  const displayedAnomalies = briefing.anomalies ? briefing.anomalies.slice(0, 3) : [];
  const hiddenAnomalyCount = Math.max(0, (briefing.anomalies?.length ?? 0) - 3);

  const takeaways: Takeaway[] = briefing.anomalies && briefing.anomalies.length > 0
    ? [
        ...displayedAnomalies.map((anom) => ({
          severity: anom.severity || "warning",
          direction: anom.direction ?? null,
          magnitudePct: anom.magnitude_pct ?? null,
          headline: anom.title,
          subtext: anom.description,
          query: anom.follow_up_query ?? anom.title,
        })),
        ...(hiddenAnomalyCount > 0
          ? [
              {
                severity: "info" as const,
                direction: null,
                magnitudePct: null,
                headline: `+${hiddenAnomalyCount} more`,
                subtext: `${hiddenAnomalyCount} additional anomaly flag${hiddenAnomalyCount > 1 ? "s" : ""} recorded`,
                query: "",
                isOverflow: true,
              },
            ]
          : []),
      ]
    : briefing.kpis && briefing.kpis.length > 0
    ? briefing.kpis.slice(0, 3).map((kpi) => {
        const normalized = kpi.label.toLowerCase();
        let followUp = `Show top 5 breakdown for ${kpi.label}`;
        if (normalized.includes("revenue")) {
          followUp = "Show top 5 product categories by total revenue with monthly totals";
        } else if (normalized.includes("account") || normalized.includes("customer")) {
          followUp = "Show top 5 customer states by active account count";
        } else if (normalized.includes("order value") || normalized.includes("aov")) {
          followUp = "Show top 5 product categories by average order value";
        } else if (normalized.includes("order")) {
          followUp = "Show top 5 payment types by total order count";
        }
        return {
          severity: "info" as const,
          direction: (kpi.trend === "up" || kpi.trend === "down") ? kpi.trend : null,
          magnitudePct: kpi.change_pct != null ? Math.abs(kpi.change_pct) : null,
          headline: `${kpi.label}: ${kpi.value}`,
          subtext: kpi.insight || "Performance matches 30-day benchmarks",
          query: followUp,
        };
      })
    : [
        {
          severity: "info" as const,
          direction: null,
          magnitudePct: null,
          headline: "All primary metrics on track",
          subtext: "Performance matches 30-day benchmarks",
          query: "How are we tracking against our usual benchmarks?",
        },
      ];

  const statusBadgeTone = !hasLiveData
    ? "border-amber-500/25 text-amber-300/90"
    : anomalyCount === 0
    ? "border-emerald-500/25 text-emerald-300/90"
    : anomalyCount === 1
    ? "border-amber-500/25 text-amber-300/90"
    : "border-rose-500/25 text-rose-300/90";

  const statusBadgeText = !hasLiveData ? "Unavailable" : anomalyCount === 0 ? "Clear" : `${anomalyCount} ${anomalyCount === 1 ? "flag" : "flags"}`;

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
        <div className="pulse-sheen" />
        <div className="absolute top-0 left-5 right-5 h-px pulse-hairline" />

        {/* Compact Header Bar */}
        <div className="flex items-center justify-between mb-2.5 relative">
          <div className="flex items-center gap-2">
            <PulseMark gradientId={`${gradientId}-compact`} />
            <h3 className="font-pulse-display italic text-[15px] font-medium text-white tracking-tight">
              Business Pulse
            </h3>
            <span className={`text-[9px] font-mono uppercase tracking-widest px-2 py-0.5 rounded-full border font-medium ${statusBadgeTone}`}>
              {statusBadgeText}
            </span>
          </div>

          <button
            type="button"
            onClick={onOpenFullBriefing}
            className="px-2.5 py-1 rounded-full border border-white/10 hover:border-[var(--accent-blue)]/40 text-[var(--text-secondary)] hover:text-[var(--accent-blue)] text-[11px] font-medium flex items-center gap-1 transition-colors touch-target"
            aria-label="View full briefing details"
          >
            <span>View briefing</span>
            <ChevronRight className="w-3 h-3" />
          </button>
        </div>

        {/* Preview Data Notice */}
        {isPreviewData && (
          <div className="mb-2.5 px-2.5 py-1 rounded-md bg-[var(--accent-amber)]/10 border border-[var(--accent-amber)]/20 text-[var(--accent-amber)] text-[10px] font-medium flex items-center gap-1.5 relative">
            <AlertTriangle className="w-3 h-3 shrink-0" />
            <span>Live workspace not connected - no business figures are being shown.</span>
          </div>
        )}

        {!hasLiveData && (
          <div className="mb-3 rounded-lg border border-white/10 bg-[var(--bg-base)]/50 px-3 py-3 relative">
            <p className="text-xs font-medium text-white">Your business pulse is not available yet.</p>
            <p className="text-[11px] text-[var(--text-secondary)] mt-1">Connect a live workspace to see verified changes, risks, and recommended actions.</p>
          </div>
        )}

        {/* Key takeaways — instrument ledger, not a bullet list */}
        <div className="relative">
          {visibleTakeaways.slice(0, 3).map((item, idx) => (
            <button
              key={idx}
              type="button"
              className={`w-full text-left flex items-center gap-2.5 group cursor-pointer py-2 -mx-1 px-1 rounded-lg hover:bg-white/[0.03] transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--accent-blue)] ${
                idx > 0 ? "border-t border-white/[0.06]" : ""
              }`}
              onClick={() =>
                item.isOverflow ? onOpenFullBriefing?.() : onSelectInsight?.(item.query)
              }
              aria-label={item.isOverflow ? "Open full briefing" : `Open details for ${item.headline}`}
            >
              <SeverityGlyph severity={item.severity} direction={item.direction} magnitudePct={item.magnitudePct} compact />
              <div className="space-y-0.5 min-w-0 flex-1">
                <h4 className="text-xs font-medium text-white tracking-wide truncate group-hover:text-[var(--accent-blue)] transition-colors">
                  {item.headline}
                </h4>
                <p className="text-[11px] text-[var(--text-secondary)] font-normal truncate">
                  {item.subtext}
                </p>
              </div>
              <ChevronRight className="w-3.5 h-3.5 text-white/0 group-hover:text-white/30 transition-colors shrink-0" />
            </button>
          ))}
        </div>

        {/* Quick Actions */}
        <div className="flex items-center gap-2 pt-2.5 mt-2.5 border-t border-white/5 relative">
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
        <div className="pulse-sheen" />
        <div className="absolute top-0 left-5 right-5 h-px pulse-hairline" />

        {/* Top Title Bar */}
        <div className="flex items-center justify-between mb-1 relative">
          <div className="flex items-center gap-2.5">
            <PulseMark gradientId={`${gradientId}-full`} />
            <div>
              <h2 className="font-pulse-display italic text-[19px] leading-none font-medium text-white tracking-tight">
                Business Pulse
              </h2>
              <p className="text-[10px] font-mono uppercase tracking-widest text-[var(--text-muted)] mt-1">
                {briefing.date}
              </p>
            </div>
            <span className={`self-start text-[9px] font-mono uppercase tracking-widest px-2 py-0.5 rounded-full border font-medium ${statusBadgeTone}`}>
              {statusBadgeText}
            </span>
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => void handleTogglePlayAudio()}
              disabled={isLoadingAudio}
              className="px-2.5 py-1 rounded-full bg-[var(--accent-blue)]/10 hover:bg-[var(--accent-blue)]/20 border border-[var(--accent-blue)]/25 text-[var(--accent-blue)] text-[11px] font-medium flex items-center gap-1.5 transition-colors touch-target disabled:opacity-50"
            >
              {isLoadingAudio ? (
                <span>Loading audio...</span>
              ) : isPlayingTopAudio ? (
                <>
                  <Pause className="w-3 h-3 fill-[var(--accent-blue)]" />
                  <span>Pause</span>
                </>
              ) : (
                <>
                  <Play className="w-3 h-3 fill-[var(--accent-blue)]" />
                  <span>Listen · 45s</span>
                </>
              )}
            </button>
            {variant !== "drawer" && (
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
            )}
          </div>
        </div>

        {/* Fallback Mode Data Source Indicator */}
        {isPreviewData && (
          <div className="mt-4 mb-3 px-3 py-1.5 rounded-lg bg-[var(--accent-amber)]/10 border border-[var(--accent-amber)]/20 text-[var(--accent-amber)] text-[11px] font-medium flex items-center gap-2 relative">
            <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
            <span>Live workspace not connected - no business figures are being shown.</span>
          </div>
        )}

        {/* Executive Greeting Subtitle */}
        <p className={`text-xs text-[var(--text-secondary)] font-medium mb-1 relative ${isPreviewData ? "" : "mt-4"}`}>
          {hasLiveData ? "What changed and what may need attention" : "Connect your workspace to generate a verified business pulse."}
        </p>

        {!hasLiveData && (
          <div className="mt-3 mb-5 rounded-xl border border-white/10 bg-[var(--bg-base)]/50 px-4 py-4 relative">
            <p className="text-sm font-semibold text-white">No verified business figures are available.</p>
            <p className="text-xs text-[var(--text-secondary)] mt-1">Once a live workspace is connected, this briefing will summarize changes, risks, and recommended actions.</p>
          </div>
        )}

        {/* Executive Ledger — directional glyph + magnitude, not a bullet dot */}
        <div className="mb-1 mt-3 relative rounded-xl border border-white/[0.06] bg-black/10 overflow-hidden">
          {visibleTakeaways.map((item, idx) => (
            <motion.div
              key={idx}
              initial={{ opacity: 0, x: -6 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: idx * 0.05, duration: 0.25 }}
              className={`flex items-start gap-3 group cursor-pointer px-3.5 py-3 hover:bg-white/[0.03] transition-colors ${
                idx > 0 ? "border-t border-white/[0.06]" : ""
              }`}
              onClick={() =>
                item.isOverflow ? onOpenFullBriefing?.() : onSelectInsight?.(item.query)
              }
            >
              <SeverityGlyph severity={item.severity} direction={item.direction} magnitudePct={item.magnitudePct} />
              <div className="space-y-0.5 min-w-0 flex-1 pt-0.5">
                <h4 className="text-[13px] font-semibold text-white tracking-wide group-hover:text-[var(--accent-blue)] transition-colors">
                  {item.headline}
                </h4>
                <p className="text-[12px] text-[var(--text-secondary)] font-normal leading-relaxed">
                  {item.subtext}
                </p>
              </div>
              <ChevronRight className="w-3.5 h-3.5 text-white/0 group-hover:text-white/30 transition-colors shrink-0 mt-2" />
            </motion.div>
          ))}
        </div>

        {/* Bottom Action Bar */}
        <div className="flex items-center gap-2.5 pt-4 mt-4 border-t border-white/10 relative">
          <button
            type="button"
            onClick={onAskFollowUp}
            disabled={actionsDisabled}
            className="flex-1 py-2 px-3.5 rounded-xl bg-gradient-to-r from-sky-500 to-indigo-600 hover:from-sky-600 hover:to-indigo-700 text-white text-xs font-semibold shadow-[0_4px_20px_-4px_rgba(56,189,248,0.4)] ring-1 ring-white/10 flex items-center justify-center gap-2 transition-all active:scale-[0.98] touch-target disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <Mic className="w-3.5 h-3.5" />
            <span>Ask a follow-up</span>
          </button>

          {variant !== "drawer" && (
            <button
              type="button"
              onClick={() => setShowDetails(!showDetails)}
              className="py-2 px-3.5 rounded-xl bg-[var(--bg-elevated)] hover:bg-[var(--bg-elevated)]/80 border border-white/10 text-white text-xs font-semibold flex items-center justify-center gap-2 transition-all touch-target"
            >
              <BarChart2 className="w-3.5 h-3.5 text-[var(--accent-blue)]" />
              <span>{showDetails ? "Hide Details" : "KPI Details"}</span>
            </button>
          )}
        </div>

        {/* Expanded Executive Details Panel */}
        {(showDetails || variant === "drawer") && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            className="mt-4 pt-4 border-t border-white/10 space-y-4 relative"
          >
            {/* Audio Podcast Narrator */}
            <div>
              <span className="text-[10px] font-mono text-[var(--accent-blue)] uppercase tracking-widest block mb-2 font-semibold">
                Audio briefing
              </span>
              <ExecutiveAudioPlayer
                textToSpeak={briefing.summary_narrative}
                voiceUrl={audioUrl}
                isPlaying={isPlayingTopAudio}
                onPlayStateChange={setIsPlayingTopAudio}
              />
            </div>

            {/* KPI Grid */}
            <div>
              <span className="text-[10px] font-mono text-[var(--text-muted)] uppercase tracking-widest block mb-2 font-semibold">
                Business signals
              </span>
              <div className="grid grid-cols-2 gap-2.5">
                {briefing.kpis.map((kpi, idx) => (
                  <div
                    key={idx}
                    className="p-3 rounded-xl bg-[var(--bg-elevated)]/60 border border-white/10 flex flex-col justify-between hover:border-[var(--accent-blue)]/30 transition-colors cursor-pointer relative overflow-hidden"
                    onClick={() => onSelectInsight?.(`Show breakdown for ${kpi.label}`)}
                  >
                    <div className="absolute top-0 left-0 right-0 h-px bg-gradient-to-r from-transparent via-white/10 to-transparent" />
                    <span className="text-[10px] font-mono text-[var(--text-muted)] font-medium">{kpi.label}</span>
                    <div className="my-1 flex items-baseline justify-between">
                      <span className="text-sm font-bold text-white font-mono tabular-nums">{kpi.value}</span>
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
