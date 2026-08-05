"use client";

import { OrganizationList, OrganizationSwitcher, SignInButton, UserButton, useAuth, useOrganization } from "@clerk/nextjs";
import React, { useMemo, useEffect, useState, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { RotateCcw, CheckCircle2, X } from "lucide-react";
import { useVoxQuerySession, type VoxQueryAuthRelay } from "../hooks/useVoxQuerySession";
import { VoiceVisualizer } from "../components/hero/VoiceVisualizer";
import { MorningBriefingCard, type ExecutiveBriefingData } from "../components/briefing/MorningBriefingCard";
import { ExecutiveMemoryGraph } from "../components/memory/ExecutiveMemoryGraph";
import { DataGlassPanel } from "../components/data/DataGlassPanel";
import { ExecutiveWorkspace } from "../components/workspace/ExecutiveWorkspace";
import { RowDrilldownModal } from "../components/data/RowDrilldownModal";
import { InsightNarrative } from "../components/insight/InsightNarrative";
import { FollowUpSuggestions } from "../components/insight/FollowUpSuggestions";
import { ClarificationOverlay } from "../components/clarification/ClarificationOverlay";
import { QueryDock } from "../components/query/QueryDock";
import { TranscriptReviewPanel } from "../components/transcript/TranscriptReviewPanel";
import { ThreadHistory } from "../components/thread/ThreadHistory";
import { InlineAnomalyNudge } from "../components/insight/InlineAnomalyNudge";
import { FailureNotice } from "../components/notice/FailureNotice";
import { PriorSessionMemoryCard } from "../components/memory/PriorSessionMemoryCard";
import { VoxQueryLogo } from "../components/brand/VoxQueryLogo";
import { getStatusLabel } from "../state/interactionState";
import { fetchWorkspaceWidgets, pinWorkspaceWidget, deleteWorkspaceWidget, updateWorkspaceWidgetNote, fetchVersion, fetchPriorSessionSummary, setAuthTokenRefresher } from "../../lib/api";
import { extractHeadline } from "../../lib/resultMetrics";
import type { LastResult, PinnedAnalysis } from "../../lib/types";

const authMode = process.env.NEXT_PUBLIC_AUTH_MODE ?? "fake";
const showDebugUi = process.env.NEXT_PUBLIC_SHOW_DEBUG_UI === "true";

/* ── Auth wrappers ────────────────────────────────────────────── */

export default function HomePage() {
  if (authMode === "clerk") return <ClerkHomePage />;
  return <VoxQueryApp auth={fakeAuthRelay} />;
}

function ClerkHomePage() {
  const { isLoaded: isAuthLoaded, isSignedIn, orgId, getToken } = useAuth();
  // useOrganization provides richer org data but resolves in a second round-trip.
  // We only need it for the org-picker screen — don't block auth on it.
  const { isLoaded: isOrgLoaded, organization } = useOrganization();

  const hasActiveOrg = Boolean(orgId || organization);

  useEffect(() => {
    setAuthTokenRefresher(getToken);
    return () => setAuthTokenRefresher(null);
  }, [getToken]);

  const auth = useMemo<VoxQueryAuthRelay>(
    () => ({
      mode: "clerk",
      // Engine is ready once both auth + org are confirmed.
      ready: isAuthLoaded && isOrgLoaded && hasActiveOrg,
      signedIn: Boolean(isSignedIn) && hasActiveOrg,
      getToken
    }),
    [getToken, isAuthLoaded, isOrgLoaded, isSignedIn, hasActiveOrg]
  );

  // Block ONLY on auth load — org load (second round-trip) must not gate the
  // loading splash. Once auth resolves we know sign-in status and can branch.
  if (!isAuthLoaded) {
    return (
      <main className="min-h-screen bg-[#090B10] flex items-center justify-center">
        <div className="text-[var(--text-muted)] text-sm font-medium animate-pulse">Loading workspace...</div>
      </main>
    );
  }

  if (!isSignedIn) {
    return (
      <main className="min-h-screen bg-[#090B10] flex flex-col items-center justify-center p-4">
        <section className="glass-card p-8 max-w-md w-full text-center space-y-6">
          <VoxQueryLogo variant="auth" />
          <p className="text-sm text-[var(--text-secondary)]">Sign in to start your secure voice analytics session.</p>
          <SignInButton
            mode="modal"
            forceRedirectUrl="/app"
            fallbackRedirectUrl="/app"
            signUpForceRedirectUrl="/app"
            signUpFallbackRedirectUrl="/app"
          >
            <button className="w-full py-3 px-4 bg-[var(--accent-blue)] hover:bg-[var(--accent-blue)]/80 text-white font-semibold rounded-xl transition-colors touch-target">
              Sign In
            </button>
          </SignInButton>
        </section>
      </main>
    );
  }

  if (!hasActiveOrg) {
    // If org data is still loading (second round-trip), wait quietly instead of
    // flashing the org-picker — which would be a false alarm while org resolves.
    if (!isOrgLoaded) {
      return (
        <main className="min-h-screen bg-[#090B10] flex items-center justify-center">
          <div className="text-[var(--text-muted)] text-sm font-medium animate-pulse">Loading workspace...</div>
        </main>
      );
    }
    return (
      <main className="min-h-screen bg-[#090B10] flex flex-col items-center justify-center p-4">
        <div className="fixed top-4 right-4 z-50">
          <div className="glass-card p-1 rounded-full"><UserButton /></div>
        </div>
        <section className="glass-card p-8 max-w-lg w-full text-center space-y-6">
          <VoxQueryLogo variant="auth" />
          <h1 className="text-xl font-bold text-white">Select or Create an Organization</h1>
          <p className="text-[var(--text-secondary)] text-sm">VoxQuery requires an active Organization to isolate your company data.</p>
          <div className="flex justify-center pt-2">
            <OrganizationList
              hidePersonal={true}
              afterSelectOrganizationUrl="/app"
              afterCreateOrganizationUrl="/app"
              appearance={{
                elements: {
                  card: "bg-[#10141C] border border-white/10 text-white shadow-2xl rounded-2xl",
                  headerTitle: "text-white font-bold",
                  headerSubtitle: "text-slate-300",
                  organizationPreviewMainIdentifier: "text-white font-semibold",
                  organizationPreviewSecondaryIdentifier: "text-slate-400"
                }
              }}
            />
          </div>
        </section>
      </main>
    );
  }


  return <VoxQueryApp auth={auth} />;
}

const fakeAuthRelay: VoxQueryAuthRelay = {
  mode: "fake",
  ready: true,
  signedIn: true,
  getToken: async () => "fake"
};

/* ── Starter questions ───────────────────────────────────────── */

const STARTER_QUESTIONS = [
  "How has monthly revenue trended over time?",
  "Which product categories drive the most revenue?",
  "Which states have the most active customers?",
];

/* ── Main App ────────────────────────────────────────────────── */

function VoxQueryApp({ auth }: { auth: VoxQueryAuthRelay }) {
  const engine = useVoxQuerySession(auth);
  const [drilldownTurnId, setDrilldownTurnId] = useState<string | null>(null);
  const [pinnedWidgets, setPinnedWidgets] = useState<PinnedAnalysis[]>([]);
  const [token, setToken] = useState<string | null>(null);
  const [briefingDrawerOpen, setBriefingDrawerOpen] = useState(false);
  const [gitSha, setGitSha] = useState<string>("unknown");
  const [briefingData, setBriefingData] = useState<ExecutiveBriefingData | null>(null);
  const [priorQuestions, setPriorQuestions] = useState<string[]>([]);

  useEffect(() => {
    let active = true;
    auth.getToken({ skipCache: true }).then((t) => {
      if (active) {
        setToken(t);
        if (showDebugUi) {
          fetchVersion(t).then((v) => {
            if (active && v?.git_sha) setGitSha(v.git_sha);
          }).catch(() => {});
        }
        if (t) {
          fetchPriorSessionSummary(engine.session.sessionId ?? undefined, t).then((res) => {
            if (active && res?.questions) {
              setPriorQuestions(res.questions);
            }
          }).catch(() => {});
        }
      }
    });
    return () => { active = false; };
  }, [auth, engine.session.sessionId]);

  useEffect(() => {
    let cancelled = false;
    auth.getToken({ skipCache: true }).then((token) => {
      fetchWorkspaceWidgets(token).then((widgets) => {
        if (!cancelled && Array.isArray(widgets)) {
          setPinnedWidgets(widgets);
        }
      }).catch((err) => {
        console.warn("Could not fetch workspace widgets", err);
      });
    });
    return () => { cancelled = true; };
  }, [auth]);

  useEffect(() => {
    if (!briefingDrawerOpen) return;
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setBriefingDrawerOpen(false);
    };
    document.addEventListener("keydown", handleEscape);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", handleEscape);
      document.body.style.overflow = previousOverflow;
    };
  }, [briefingDrawerOpen]);

  const handlePinWidget = async (result: LastResult) => {
    if (!result?.turnId) {
      console.error("Cannot pin widget: turn_id is missing");
      return;
    }
    const title = result.submittedText
      || result.resultData?.tts_text?.split(".")[0]
      || "Saved finding";
    try {
      const token = await auth.getToken();
      const { value: headlineValue, label: headlineLabel } = extractHeadline(result.resultData?.result);
      const newWidget = await pinWorkspaceWidget(
        {
          turn_id: result.turnId,
          title: title.slice(0, 200),
          headline_value: headlineValue,
          headline_label: headlineLabel,
          layout_x: 0,
          layout_y: 0,
          layout_w: 4,
          layout_h: 3,
        },
        token
      );
      setPinnedWidgets((prev) => {
        if (prev.some((w) => w.id === newWidget.id || w.id === result.turnId)) return prev;
        return [...prev, newWidget];
      });
    } catch (err: any) {
      console.error("Failed to pin widget", err?.status, err?.message, err?.response?.data?.detail ?? err);
    }
  };

  const handleUpdateWidgetNote = async (widgetId: string, note: string | null) => {
    try {
      const token = await auth.getToken();
      await updateWorkspaceWidgetNote(widgetId, note, token);
      setPinnedWidgets((prev) =>
        prev.map((w) => w.id === widgetId ? { ...w, note } : w)
      );
    } catch (err) {
      console.error("Failed to update note", err);
    }
  };

  const handleRemoveWidget = async (id: string) => {
    try {
      const token = await auth.getToken();
      await deleteWorkspaceWidget(id, token);
      setPinnedWidgets((prev) => prev.filter((w) => w.id !== id));
    } catch (err) {
      console.error("Failed to remove widget", err);
    }
  };

  const handleRerunPinnedAnalysis = useCallback((query: string) => {
    engine.setSubmittedText(query);
    void engine.submitQuery(query);
  }, [engine]);

  const isReviewing = engine.voiceState === "reviewing";
  const isActive = engine.recordingState !== "idle" || engine.pipelineInFlight;
  const hasResult = !!engine.lastResult;
  const isError = engine.turnState === "recoverable_error" || engine.turnState === "fatal_error";
  const anomalyCount = briefingData?.anomalies?.length;
  const briefingLabel = briefingData === null
    ? "Business pulse"
    : briefingData.is_live !== true
    ? "Business pulse unavailable"
    : anomalyCount === 0
    ? "Business pulse - Clear"
    : `Business pulse - ${anomalyCount} ${anomalyCount === 1 ? "flag" : "flags"}`;
  const handleAuthExpired = useCallback(() => {
    window.location.reload();
  }, []);

  const uiState: "ready" | "reviewing" | "active" | "insight" =
    isReviewing ? "reviewing" :
    isActive ? "active" :
    hasResult ? "insight" : "ready";

  const rawStatusLabel = getStatusLabel(engine.voiceState, engine.turnState, engine.ttsState);

  // Executive human-readable status mapping
  const humanStatusLabel =
    engine.recordingState === "recording" ? "Listening..." :
    engine.pipelineInFlight ? "Analyzing your data..." :
    engine.ttsState === "playing" ? "Speaking..." :
    rawStatusLabel;

  return (
    <main className="min-h-screen flex flex-col relative bg-[#090B10]">
      {/* Shared Application Header Bar */}
      <header className="w-full px-4 md:px-6 py-3.5 flex items-center justify-between z-40 relative border-b border-white/5 bg-[#090B10]/80 backdrop-blur-xl">
        <div className="flex items-center gap-3">
          <VoxQueryLogo variant="header" />
        </div>

        <div className="flex items-center gap-2.5 md:gap-3">
          <button
            type="button"
            onClick={() => setBriefingDrawerOpen(true)}
            className="px-3 py-1.5 rounded-full glass-card text-white text-xs font-semibold hover:border-[var(--accent-blue)]/50 transition-all flex items-center gap-1.5 touch-target"
            aria-label="Open today's briefing drawer"
          >
            <span>{briefingLabel}</span>
          </button>

          {auth.mode === "clerk" && (
            <div className="flex items-center gap-2 pl-2 border-l border-white/10">
              <div className="glass-card px-2.5 py-1 rounded-full flex items-center">
                <OrganizationSwitcher
                  hidePersonal={true}
                  afterSelectOrganizationUrl="/"
                  afterLeaveOrganizationUrl="/"
                  appearance={{
                    elements: {
                      organizationSwitcherTrigger: "text-white font-semibold hover:text-[var(--accent-blue)] transition-colors text-xs md:text-sm",
                      organizationSwitcherTriggerIcon: "text-slate-300",
                      organizationPreviewTextContainer: "text-white font-semibold",
                      organizationPreviewMainIdentifier: "text-white font-semibold",
                      organizationPreviewSecondaryIdentifier: "text-slate-400"
                    }
                  }}
                />
              </div>
              <div className="glass-card p-0.5 rounded-full flex items-center">
                <UserButton />
              </div>
            </div>
          )}
        </div>
      </header>

      {/* Scrollable content area with sufficient bottom padding for fixed query dock */}
      <div className="flex-1 flex flex-col items-center px-4 md:px-8 pb-48 overflow-y-auto scrollbar-hide">

        <AnimatePresence mode="wait">

          {/* ── STATE 1: READY ──────────────────────────────────── */}
          {uiState === "ready" && (
            <motion.div
              key="ready"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0, y: -20 }}
              transition={{ duration: 0.4 }}
              className="flex-1 flex flex-col items-center justify-start max-w-2xl w-full py-8 md:py-10"
            >
              <VoxQueryLogo variant="hero" className="mb-5" />

              {/* Voice Visualizer Orb - Primary Interaction */}
              <div className="my-2 flex flex-col items-center">
                <VoiceVisualizer
                  state={engine.recordingState}
                  analyser={engine.audioAnalyserNode}
                  disabled={!engine.isReady || engine.pipelineInFlight}
                  pipelineStage={engine.pipelineStage}
                  partialTranscript={engine.partialTranscript}
                  onPrimaryAction={engine.startRecording}
                  onStop={engine.stopRecording}
                  size="hero"
                />
              </div>

              <h2 className="mt-6 text-2xl md:text-3xl font-extrabold text-white text-center tracking-tight">
                What would you like to know?
              </h2>
              <p className="mt-2 text-xs md:text-sm text-[var(--text-secondary)] font-medium text-center">
                Tap the orb to speak, or try one of these:
              </p>

              {/* Starter questions */}
              <div className="mt-4 flex flex-wrap justify-center gap-2.5 max-w-lg">
                {STARTER_QUESTIONS.map((q) => (
                  <button
                    key={q}
                    type="button"
                    onClick={() => {
                      engine.setSubmittedText(q);
                      engine.submitQuery(q);
                    }}
                    disabled={!engine.isReady}
                    className="px-4 py-2 rounded-full border border-white/10 bg-[var(--bg-surface)] text-xs font-medium text-[var(--text-secondary)] hover:text-white hover:border-[var(--accent-blue)]/40 hover:bg-[var(--bg-elevated)] transition-all disabled:opacity-50 touch-target flex items-center"
                  >
                    {q}
                  </button>
                ))}
              </div>

              {/* Honest workspace connection status indicator */}
              <div className="mt-4 flex items-center justify-center gap-2 text-xs font-medium">
                {engine.connectionState === "connected" ? (
                  <CheckCircle2 className="w-3.5 h-3.5 text-[var(--accent-green)]" />
                ) : engine.connectionState === "connecting" || engine.connectionState === "disconnected" ? (
                  <span className="w-2 h-2 rounded-full bg-[var(--accent-amber)] animate-pulse" />
                ) : (
                  <span className="w-2 h-2 rounded-full bg-rose-500" />
                )}
                <span className={
                  engine.connectionState === "connected"
                    ? "text-[var(--text-muted)]"
                    : engine.connectionState === "error"
                    ? "text-rose-400 font-semibold"
                    : "text-[var(--accent-amber)] font-medium"
                }>
                  {engine.connectionStatusLabel}
                </span>
                {engine.connectionState === "error" && (
                  <button
                    type="button"
                    onClick={engine.retryConnection}
                    className="ml-1 rounded-full border border-rose-400/30 px-2.5 py-1 text-[11px] font-semibold text-rose-300 hover:bg-rose-400/10 transition-colors touch-target"
                  >
                    Retry connection
                  </button>
                )}
              </div>

              {/* Home Screen Briefing Summary Card */}
              <div className="mt-5 w-full max-w-xl">
                <MorningBriefingCard
                  token={token}
                  getToken={auth.getToken}
                  briefing={briefingData}
                  onBriefingLoaded={setBriefingData}
                  onAuthExpired={handleAuthExpired}
                  actionsDisabled={!engine.isReady}
                  variant="compact"
                  onSelectInsight={(q) => {
                    engine.setSubmittedText(q);
                    engine.submitQuery(q);
                  }}
                  onAskFollowUp={engine.toggleRecording}
                  onOpenFullBriefing={() => setBriefingDrawerOpen(true)}
                />
              </div>

              {/* Prior session memory */}
              <div className="mt-6 w-full">
                <PriorSessionMemoryCard
                  questions={priorQuestions}
                  onSelectQuestion={(q) => {
                    engine.setSubmittedText(q);
                    engine.submitQuery(q);
                  }}
                />
              </div>

              {/* Saved findings workspace */}
              <div className="mt-6 w-full">
                <ExecutiveWorkspace
                  pinnedWidgets={pinnedWidgets}
                  onRemoveWidget={handleRemoveWidget}
                  onRerunAnalysis={handleRerunPinnedAnalysis}
                  onUpdateNote={handleUpdateWidgetNote}
                  token={token}
                />
              </div>

              {isError && (
                <div className="mt-6 w-full max-w-xl">
                  <FailureNotice
                    severity={engine.notice.severity}
                    message={engine.notice.message}
                    action={{ label: "Try again", onClick: engine.submitCurrentQuery }}
                  />
                </div>
              )}
            </motion.div>
          )}

          {/* ── STATE 2: REVIEWING ──────────────────────────────── */}
          {uiState === "reviewing" && (
            <motion.div
              key="reviewing"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0, y: -16 }}
              transition={{ duration: 0.3 }}
              className="flex-1 flex flex-col items-center justify-center min-h-[60vh] max-w-2xl w-full pt-10"
            >
              <h2 className="text-xl font-normal text-white text-center mb-6 tracking-tight">
                Review before sending
              </h2>
              <TranscriptReviewPanel
                rawTranscript={engine.voiceDraft?.rawTranscript ?? engine.submittedText}
                editedText={engine.submittedText}
                disabled={!engine.isReady}
                onChange={engine.setSubmittedText}
                onReRecord={engine.reRecord}
                onSubmit={engine.submitCurrentQuery}
              />
            </motion.div>
          )}

          {/* ── STATE 3: ACTIVE ─────────────────────────────────── */}
          {uiState === "active" && (
            <motion.div
              key="active"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0, y: -20 }}
              transition={{ duration: 0.4 }}
              className="flex-1 flex flex-col items-center justify-center min-h-[75vh] max-w-2xl w-full"
            >
              <VoiceVisualizer
                state={engine.recordingState}
                analyser={engine.audioAnalyserNode}
                disabled={!engine.isReady}
                pipelineStage={engine.pipelineStage}
                partialTranscript={engine.partialTranscript}
                onPrimaryAction={engine.startRecording}
                onStop={engine.stopRecording}
                size="hero"
              />

              <motion.p
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                className="mt-8 text-xl md:text-2xl text-white text-center font-light max-w-lg"
              >
                {engine.partialTranscript || engine.submittedText || "Listening..."}
              </motion.p>

              {engine.pipelineInFlight && (
                <motion.div
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  className="mt-4 flex items-center gap-3"
                >
                  <div className="w-16 h-0.5 rounded-full bg-[var(--bg-elevated)] overflow-hidden">
                    <motion.div
                      animate={{ x: ["-100%", "100%"] }}
                      transition={{ repeat: Infinity, duration: 1.5, ease: "easeInOut" }}
                      className="w-full h-full bg-[var(--accent-amber)]"
                    />
                  </div>
                  <span className="text-sm font-medium text-[var(--accent-amber)]">
                    {humanStatusLabel}
                  </span>
                </motion.div>
              )}
            </motion.div>
          )}

          {/* ── STATE 4: INSIGHT ────────────────────────────────── */}
          {uiState === "insight" && engine.lastResult && (
            <motion.div
              key="insight"
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.5, ease: [0.23, 1, 0.32, 1] }}
              className="w-full max-w-3xl pt-8 md:pt-12"
            >
              {/* Question Echo */}
              <div className="flex items-start gap-3 mb-6">
                <div className="w-7 h-7 rounded-full bg-gradient-to-br from-[var(--accent-blue)] to-indigo-600 flex-shrink-0 mt-0.5" />
                <p className="text-base md:text-lg text-white font-medium leading-snug">
                  {engine.lastResult.submittedText}
                </p>
              </div>

              {engine.ttsState === "failed" && (
                <div className="mb-4">
                  <FailureNotice
                    severity="warning"
                    message="Voice playback failed. The text answer below is still available."
                  />
                </div>
              )}

              {/* Insight Narrative - Visual Focal Point */}
              <InsightNarrative
                text={engine.lastResult.resultData.tts_text}
                isMuted={engine.isMuted}
                isPaused={engine.isPaused}
                onToggleMute={engine.isMuted ? engine.unmuteTTS : engine.muteTTS}
                onTogglePause={engine.isPaused ? engine.resumeTTS : engine.pauseTTS}
              />

              {/* Data & Trust Glass Panel */}
              <DataGlassPanel
                result={engine.lastResult}
                feedbackRating={engine.feedbackRating}
                onFeedback={engine.submitFeedback}
                onDrillDown={engine.submitQuery}
                onDrilldownOpen={setDrilldownTurnId}
                onPin={handlePinWidget}
                getToken={auth.getToken}
              />

              {/* Inline anomaly nudge */}
              {engine.lastResult?.resultData?.anomaly && (
                <InlineAnomalyNudge
                  anomaly={engine.lastResult.resultData.anomaly}
                  onAskBreakdown={engine.submitQuery}
                />
              )}

              {/* Follow-up suggestions */}
              <FollowUpSuggestions
                result={engine.lastResult}
                onSelect={engine.submitQuery}
                disabled={engine.pipelineInFlight}
              />

              {/* Expandable thread history */}
              <div className="mt-8">
                <ThreadHistory
                  turns={engine.turnHistory}
                  activeTurnId={engine.lastResult.turnId}
                />
              </div>

              {/* Conversation context graph */}
              <div className="mt-6 w-full">
                <h4 className="text-xs font-semibold text-[var(--text-muted)] uppercase tracking-wider mb-2">
                  Analysis recap
                </h4>
                <ExecutiveMemoryGraph
                  sessionId={engine.session.sessionId}
                  authToken={token}
                />
              </div>

              {/* New conversation control */}
              <div className="mt-8 mb-4 flex justify-center">
                <button
                  type="button"
                  onClick={engine.resetConversation}
                  aria-label="New conversation"
                  className="flex items-center gap-2 px-4 py-2 rounded-full text-xs font-medium text-[var(--text-muted)] hover:text-white border border-white/10 hover:bg-[var(--bg-surface)] transition-all touch-target"
                >
                  <RotateCcw className="w-3.5 h-3.5" />
                  <span>New conversation</span>
                </button>
              </div>
            </motion.div>
          )}

        </AnimatePresence>
      </div>

      {/* Fixed bottom query dock */}
      <div className="fixed bottom-0 left-0 right-0 p-4 md:p-6 bg-gradient-to-t from-[#090B10] via-[#090B10]/95 to-transparent pointer-events-none z-20">
        <div className="pointer-events-auto max-w-2xl mx-auto space-y-2">
          <AnimatePresence>
            {(engine.notice.severity === "error" || engine.notice.severity === "warning") &&
              uiState !== "ready" && (
              <FailureNotice
                key="dock-notice"
                severity={engine.notice.severity}
                message={engine.notice.message}
                action={
                  engine.turnState === "recoverable_error"
                    ? { label: "Retry", onClick: engine.submitCurrentQuery }
                    : undefined
                }
              />
            )}
          </AnimatePresence>

          <QueryDock
            value={engine.submittedText}
            disabled={!engine.isReady || engine.pipelineInFlight}
            isReady={engine.isReady}
            recordingState={engine.recordingState}
            notice={engine.notice}
            onChange={engine.setSubmittedText}
            onSubmit={engine.submitCurrentQuery}
            onFakeVoice={engine.startFakeVoice}
            onToggleRecording={engine.toggleRecording}
            onResetConversation={engine.resetConversation}
          />
        </div>
      </div>

      {/* Clarification overlay */}
      <AnimatePresence>
        {engine.clarification.pending && (
          <ClarificationOverlay
            clarification={engine.clarification}
            onResolve={engine.submitClarification}
          />
        )}
      </AnimatePresence>

      {/* Briefing Drawer Overlay */}
      <AnimatePresence>
        {briefingDrawerOpen && (
          <div
            data-testid="briefing-drawer"
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-md p-4"
            role="dialog"
            aria-modal="true"
            aria-label="Today's executive briefing"
            onClick={() => setBriefingDrawerOpen(false)}
          >
            <div className="w-full max-w-xl relative max-h-[85vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
              <button
                type="button"
                onClick={() => setBriefingDrawerOpen(false)}
                className="absolute top-4 right-4 z-10 p-1.5 rounded-full bg-white/10 hover:bg-white/20 text-white transition-colors touch-target"
                aria-label="Close briefing drawer"
              >
                <X className="w-4 h-4" />
              </button>
              <MorningBriefingCard
                token={token}
                getToken={auth.getToken}
                briefing={briefingData}
                onBriefingLoaded={setBriefingData}
                onAuthExpired={handleAuthExpired}
                actionsDisabled={!engine.isReady}
                variant="drawer"
                onClose={() => setBriefingDrawerOpen(false)}
                onSelectInsight={(q) => {
                  setBriefingDrawerOpen(false);
                  engine.setSubmittedText(q);
                  engine.submitQuery(q);
                }}
                onAskFollowUp={() => {
                  setBriefingDrawerOpen(false);
                  engine.toggleRecording();
                }}
              />
            </div>
          </div>
        )}
      </AnimatePresence>

      {/* Drilldown modal */}
      <RowDrilldownModal
        isOpen={!!drilldownTurnId}
        onClose={() => setDrilldownTurnId(null)}
        turnId={drilldownTurnId}
        authToken={token}
      />

      {/* Optional Debug Version Footer */}
      {showDebugUi && (
        <div className="fixed bottom-2 right-4 text-[10px] font-mono text-[var(--text-muted)] z-10 pointer-events-none opacity-60">
          Build: {gitSha.slice(0, 7)}
        </div>
      )}
    </main>
  );
}
