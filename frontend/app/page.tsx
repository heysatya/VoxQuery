"use client";

import { OrganizationList, OrganizationSwitcher, SignInButton, UserButton, useAuth, useOrganization } from "@clerk/nextjs";
import React, { useMemo, useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { RotateCcw, CheckCircle2 } from "lucide-react";
import { useVoxQuerySession, type VoxQueryAuthRelay } from "./hooks/useVoxQuerySession";
import { VoiceVisualizer } from "./components/hero/VoiceVisualizer";
import { MorningBriefingCard } from "./components/briefing/MorningBriefingCard";
import { ExecutiveMemoryGraph } from "./components/memory/ExecutiveMemoryGraph";
import { DataGlassPanel } from "./components/data/DataGlassPanel";
import { ExecutiveWorkspace } from "./components/workspace/ExecutiveWorkspace";
import { RowDrilldownModal } from "./components/data/RowDrilldownModal";
import { InsightNarrative } from "./components/insight/InsightNarrative";
import { FollowUpSuggestions } from "./components/insight/FollowUpSuggestions";
import { ClarificationOverlay } from "./components/clarification/ClarificationOverlay";
import { QueryDock } from "./components/query/QueryDock";
import { TranscriptReviewPanel } from "./components/transcript/TranscriptReviewPanel";
import { ThreadHistory } from "./components/thread/ThreadHistory";
import { InlineAnomalyNudge } from "./components/insight/InlineAnomalyNudge";
import { FailureNotice } from "./components/notice/FailureNotice";
import { PriorSessionMemoryCard } from "./components/memory/PriorSessionMemoryCard";
import { VoxQueryLogo } from "./components/brand/VoxQueryLogo";
import { getStatusLabel } from "./state/interactionState";
import { fetchWorkspaceWidgets, pinWorkspaceWidget, deleteWorkspaceWidget, fetchVersion, fetchBriefing, fetchPriorSessionSummary } from "../lib/api";
import type { LastResult } from "../lib/types";

const authMode = process.env.NEXT_PUBLIC_AUTH_MODE ?? "fake";

/* ── Auth wrappers ────────────────────────────────────────────── */

export default function HomePage() {
  if (authMode === "clerk") return <ClerkHomePage />;
  return <VoxQueryApp auth={fakeAuthRelay} />;
}

function ClerkHomePage() {
  const { isLoaded: isAuthLoaded, isSignedIn, orgId, getToken } = useAuth();
  const { isLoaded: isOrgLoaded, organization } = useOrganization();

  const isLoaded = isAuthLoaded && isOrgLoaded;
  const hasActiveOrg = Boolean(orgId || organization);

  const auth = useMemo<VoxQueryAuthRelay>(
    () => ({
      mode: "clerk",
      ready: isLoaded && hasActiveOrg,
      signedIn: Boolean(isSignedIn) && hasActiveOrg,
      getToken
    }),
    [getToken, isLoaded, isSignedIn, hasActiveOrg]
  );

  if (!isLoaded) {
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
          <SignInButton mode="modal">
            <button className="w-full py-3 px-4 bg-[var(--accent-blue)] hover:bg-[var(--accent-blue)]/80 text-white font-semibold rounded-xl transition-colors touch-target">
              Sign in
            </button>
          </SignInButton>
        </section>
      </main>
    );
  }

  if (!hasActiveOrg) {
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
            <OrganizationList hidePersonal={true} afterSelectOrganizationUrl="/" afterCreateOrganizationUrl="/" />
          </div>
        </section>
      </main>
    );
  }

  return (
    <>
      <div className="fixed top-4 right-4 z-50 flex items-center gap-3">
        <div className="glass-card px-3 py-1 rounded-full flex items-center">
          <OrganizationSwitcher hidePersonal={true} afterSelectOrganizationUrl="/" afterLeaveOrganizationUrl="/" />
        </div>
        <div className="glass-card p-1 rounded-full"><UserButton /></div>
      </div>
      <VoxQueryApp auth={auth} />
    </>
  );
}

const fakeAuthRelay: VoxQueryAuthRelay = {
  mode: "fake",
  ready: true,
  signedIn: true,
  getToken: async () => "fake"
};

/* ── Starter questions ───────────────────────────────────────── */

const STARTER_QUESTIONS = [
  "How did revenue perform last quarter?",
  "What are the top-selling products?",
  "Show me pipeline by region",
];

/* ── Main App ────────────────────────────────────────────────── */

function VoxQueryApp({ auth }: { auth: VoxQueryAuthRelay }) {
  const engine = useVoxQuerySession(auth);
  const [drilldownTurnId, setDrilldownTurnId] = useState<string | null>(null);
  const [pinnedWidgets, setPinnedWidgets] = useState<any[]>([]);
  const [token, setToken] = useState<string | null>(null);
  const [briefingDrawerOpen, setBriefingDrawerOpen] = useState(false);
  const [gitSha, setGitSha] = useState<string>("unknown");
  const [anomalyCount, setAnomalyCount] = useState<number | null>(null);
  const [priorQuestions, setPriorQuestions] = useState<string[]>([]);

  useEffect(() => {
    let active = true;
    auth.getToken().then((t) => {
      if (active) {
        setToken(t);
        fetchVersion(t).then((v) => {
          if (active && v?.git_sha) setGitSha(v.git_sha);
        }).catch(() => {});
        if (t) {
          fetchBriefing(t).then((b) => {
            if (active && b?.anomalies) {
              setAnomalyCount(b.anomalies.length);
            }
          }).catch(() => {});
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
    auth.getToken().then((token) => {
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

  const handlePinWidget = async (result: LastResult) => {
    const title = result.submittedText
      || result.resultData?.tts_text?.split(".")[0]
      || "Pinned metric";
    try {
      const token = await auth.getToken();
      const newWidget = await pinWorkspaceWidget(
        {
          turn_id: result.turnId,
          title,
        },
        token
      );
      setPinnedWidgets((prev) => {
        if (prev.some((w) => w.id === newWidget.id || w.id === result.turnId)) return prev;
        return [...prev, newWidget];
      });
    } catch (err) {
      console.error("Failed to pin widget", err);
    }
  };

  const handleRemoveWidget = async (id: string) => {
    try {
      const token = await auth.getToken();
      await deleteWorkspaceWidget(id, token);
      setPinnedWidgets((prev) => prev.filter((w) => w.id !== id && w.widget_id !== id));
    } catch (err) {
      console.error("Failed to remove widget", err);
    }
  };

  const isReviewing = engine.voiceState === "reviewing";
  const isActive = engine.recordingState !== "idle" || engine.pipelineInFlight;
  const hasResult = !!engine.lastResult;
  const isError = engine.turnState === "recoverable_error" || engine.turnState === "fatal_error";

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
      {/* Restrained Top Header Bar */}
      <header className="w-full px-6 py-3.5 flex items-center justify-between z-40 relative border-b border-white/5 bg-[#090B10]/80 backdrop-blur-xl">
        <div className="flex items-center gap-3">
          <VoxQueryLogo variant="header" />
        </div>

        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => setBriefingDrawerOpen(true)}
            className="px-3.5 py-1.5 rounded-full glass-card text-white text-xs font-semibold hover:border-[var(--accent-blue)]/50 transition-all flex items-center gap-2 touch-target"
            aria-label="Open today's briefing drawer"
          >
            <span>
              {anomalyCount === null
                ? "☀️ Today's briefing"
                : anomalyCount === 0
                ? "☀️ Today's briefing — Clear"
                : anomalyCount === 1
                ? "☀️ Today's briefing — 1 flag"
                : `☀️ Today's briefing — ${anomalyCount} flags`}
            </span>
          </button>
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
              className="flex-1 flex flex-col items-center justify-center min-h-[75vh] max-w-2xl w-full pt-8"
            >
              <VoxQueryLogo variant="hero" className="mb-8" />

              {/* Voice Visualizer Orb - Primary Interaction */}
              <div className="my-4 flex flex-col items-center">
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

              <h2 className="mt-8 text-2xl md:text-3xl font-extrabold text-white text-center tracking-tight">
                What would you like to know?
              </h2>
              <p className="mt-2 text-xs md:text-sm text-[var(--text-secondary)] font-medium text-center">
                Tap the orb to speak, or try one of these:
              </p>

              {/* Starter questions */}
              <div className="mt-5 flex flex-wrap justify-center gap-2.5 max-w-lg">
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

              {/* Quiet workspace connection status indicator */}
              <div className="mt-8 flex items-center justify-center gap-2 text-xs text-[var(--text-muted)] font-medium">
                <CheckCircle2 className="w-3.5 h-3.5 text-[var(--accent-green)]" />
                <span>Connected to your workspace</span>
              </div>

              <div className="mt-10 w-full">
                <PriorSessionMemoryCard
                  questions={priorQuestions}
                  onSelectQuestion={(q) => {
                    engine.setSubmittedText(q);
                    engine.submitQuery(q);
                  }}
                />
              </div>

              {/* Saved metrics workspace */}
              <div className="mt-6 w-full">
                <ExecutiveWorkspace
                  pinnedWidgets={pinnedWidgets}
                  onRemoveWidget={handleRemoveWidget}
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
                onReRecord={() => {
                  engine.setSubmittedText("");
                  void engine.startRecording();
                }}
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
                isMuted={engine.isMuted}
                onFeedback={engine.submitFeedback}
                onMute={engine.muteTTS}
                onUnmute={engine.unmuteTTS}
                onDrillDown={engine.submitQuery}
                onDrilldownOpen={setDrilldownTurnId}
                onPin={handlePinWidget}
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
                  Conversation context
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
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-md p-4">
            <div className="w-full max-w-xl">
              <MorningBriefingCard
                token={token}
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

      {/* Quiet Version Footer */}
      <div className="fixed bottom-2 right-4 text-[10px] font-mono text-[var(--text-muted)] z-10 pointer-events-none opacity-60">
        Build: {gitSha.slice(0, 7)}
      </div>
    </main>
  );
}
