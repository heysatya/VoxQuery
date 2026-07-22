"use client";

import { SignInButton, UserButton, useAuth } from "@clerk/nextjs";
import React, { useMemo } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { RotateCcw } from "lucide-react";
import { useVoxQuerySession, type VoxQueryAuthRelay } from "./hooks/useVoxQuerySession";
import { VoiceVisualizer } from "./components/hero/VoiceVisualizer";
import { MorningBriefingCard } from "./components/briefing/MorningBriefingCard";
import { ExecutiveMemoryGraph } from "./components/memory/ExecutiveMemoryGraph";
import { DataGlassPanel } from "./components/data/DataGlassPanel";
import { InsightNarrative } from "./components/insight/InsightNarrative";
import { FollowUpSuggestions } from "./components/insight/FollowUpSuggestions";
import { ClarificationOverlay } from "./components/clarification/ClarificationOverlay";
import { QueryDock } from "./components/query/QueryDock";
import { TranscriptReviewPanel } from "./components/transcript/TranscriptReviewPanel";
import { ThreadHistory } from "./components/thread/ThreadHistory";
import { FailureNotice } from "./components/notice/FailureNotice";
import { getStatusLabel } from "./state/interactionState";

const authMode = process.env.NEXT_PUBLIC_AUTH_MODE ?? "fake";

/* -- Auth wrappers (unchanged contracts) ----------------------- */

export default function HomePage() {
  if (authMode === "clerk") return <ClerkHomePage />;
  return <VoxQueryApp auth={fakeAuthRelay} />;
}

function ClerkHomePage() {
  const { isLoaded, isSignedIn, getToken } = useAuth();
  const auth = useMemo<VoxQueryAuthRelay>(
    () => ({
      mode: "clerk",
      ready: isLoaded,
      signedIn: Boolean(isSignedIn),
      getToken
    }),
    [getToken, isLoaded, isSignedIn]
  );

  if (!isLoaded) {
    return (
      <main className="min-h-screen flex items-center justify-center">
        <div className="text-[var(--text-muted)] animate-pulse">Loading authentication...</div>
      </main>
    );
  }

  if (!isSignedIn) {
    return (
      <main className="min-h-screen flex flex-col items-center justify-center p-4">
        <section className="glass-card p-8 max-w-md w-full text-center space-y-6">
          <h1 className="text-3xl font-bold text-[var(--text-primary)]">VoxQuery</h1>
          <p className="text-[var(--text-secondary)]">Sign in to start a secure voice analytics session.</p>
          <SignInButton mode="modal">
            <button className="w-full py-3 px-4 bg-[var(--accent-blue)] hover:bg-[var(--accent-blue)]/80 text-white font-medium rounded-xl transition-colors">
              Sign in
            </button>
          </SignInButton>
        </section>
      </main>
    );
  }

  return (
    <>
      <div className="fixed top-4 right-4 z-50">
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

  // Phase 3.2: derive visible state from explicit lifecycle dimensions
  const isReviewing = engine.voiceState === "reviewing";
  const isActive = engine.recordingState !== "idle" || engine.pipelineInFlight;
  const hasResult = !!engine.lastResult;
  const isError = engine.turnState === "recoverable_error" || engine.turnState === "fatal_error";

  // Deterministic UI state
  const uiState: "ready" | "reviewing" | "active" | "insight" =
    isReviewing ? "reviewing" :
    isActive ? "active" :
    hasResult ? "insight" : "ready";

  // Phase 3.2: status label derived from explicit state
  const statusLabel = getStatusLabel(engine.voiceState, engine.turnState, engine.ttsState);

  return (
    <main className="min-h-screen flex flex-col relative">
      {/* Scrollable content area */}
      <div className="flex-1 flex flex-col items-center px-4 md:px-8 pb-44 overflow-y-auto scrollbar-hide">

        <AnimatePresence mode="wait">

          {/* ── STATE 1: READY ──────────────────────────────────── */}
          {uiState === "ready" && (
            <motion.div
              key="ready"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0, y: -20 }}
              transition={{ duration: 0.4 }}
              className="flex-1 flex flex-col items-center justify-center min-h-[80vh] max-w-2xl w-full pt-6"
            >
              <MorningBriefingCard
                onSelectInsight={(q) => {
                  engine.setSubmittedText(q);
                  engine.submitQuery(q);
                }}
              />

              <VoiceVisualizer
                state={engine.recordingState}
                analyser={engine.audioAnalyserNode}
                disabled={!engine.isReady || engine.pipelineInFlight}
                pipelineStage={engine.pipelineStage}
                partialTranscript={engine.partialTranscript}
                onPrimaryAction={engine.startRecording}
                onStop={engine.stopRecording}
              />

              <h2 className="mt-10 text-2xl md:text-3xl font-light text-[var(--text-primary)] text-center tracking-tight">
                What would you like to know?
              </h2>
              <p className="mt-3 text-sm text-[var(--text-muted)] text-center">
                Tap the orb to speak, or try one of these:
              </p>

              <div className="mt-6 flex flex-wrap justify-center gap-2">
                {STARTER_QUESTIONS.map((q) => (
                  <button
                    key={q}
                    type="button"
                    onClick={() => {
                      engine.setSubmittedText(q);
                      engine.submitQuery(q);
                    }}
                    disabled={!engine.isReady}
                    className="px-4 py-2.5 rounded-full border border-[var(--border)] bg-[var(--bg-surface)] text-sm text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:border-[var(--accent-blue)]/30 hover:bg-[var(--bg-elevated)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent-blue)] transition-all disabled:opacity-50"
                  >
                    {q}
                  </button>
                ))}
              </div>

              {/* Phase 3.3: show error notice in ready state if a prior query failed */}
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

          {/* ── STATE 2: REVIEWING (transcript review) ──────────── */}
          {uiState === "reviewing" && (
            <motion.div
              key="reviewing"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0, y: -16 }}
              transition={{ duration: 0.3 }}
              className="flex-1 flex flex-col items-center justify-center min-h-[60vh] max-w-2xl w-full pt-10"
            >
              <h2 className="text-xl font-light text-[var(--text-primary)] text-center mb-6">
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

          {/* ── STATE 3: ACTIVE (recording / processing) ────────── */}
          {uiState === "active" && (
            <motion.div
              key="active"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0, y: -20 }}
              transition={{ duration: 0.4 }}
              className="flex-1 flex flex-col items-center justify-center min-h-[80vh] max-w-2xl w-full"
            >
              <VoiceVisualizer
                state={engine.recordingState}
                analyser={engine.audioAnalyserNode}
                disabled={!engine.isReady}
                pipelineStage={engine.pipelineStage}
                partialTranscript={engine.partialTranscript}
                onPrimaryAction={engine.startRecording}
                onStop={engine.stopRecording}
              />

              {/* User's question */}
              <motion.p
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                className="mt-10 text-xl md:text-2xl text-[var(--text-primary)] text-center font-light max-w-lg"
              >
                {engine.partialTranscript || engine.submittedText || "Listening..."}
              </motion.p>

              {/* Phase 3.2: status label derived from explicit state */}
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
                  <span className="text-sm text-[var(--accent-amber)]">
                    {statusLabel}
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
              className="w-full max-w-3xl pt-10 md:pt-16"
            >
              {/* Phase 3.4: expandable thread history */}
              <ThreadHistory
                turns={engine.turnHistory}
                activeTurnId={engine.lastResult.turnId}
              />

              {/* Question echo */}
              <div className="flex items-start gap-3 mb-6">
                <div className="w-7 h-7 rounded-full bg-gradient-to-br from-[var(--accent-blue)] to-indigo-600 flex-shrink-0 mt-0.5" />
                <p className="text-base md:text-lg text-[var(--text-secondary)] font-light leading-snug">
                  {engine.lastResult.submittedText}
                </p>
              </div>

              {/* Phase 3.3: TTS failure notice */}
              {engine.ttsState === "failed" && (
                <div className="mb-4">
                  <FailureNotice
                    severity="warning"
                    message="Voice playback failed. The text answer below is still available."
                  />
                </div>
              )}

              {/* Narrative */}
              <InsightNarrative
                text={engine.lastResult.resultData.tts_text}
                isMuted={engine.isMuted}
                isPaused={engine.isPaused}
                onToggleMute={engine.isMuted ? engine.unmuteTTS : engine.muteTTS}
                onTogglePause={engine.isPaused ? engine.resumeTTS : engine.pauseTTS}
              />

              {/* Chart card */}
              <DataGlassPanel
                result={engine.lastResult}
                feedbackRating={engine.feedbackRating}
                isMuted={engine.isMuted}
                onFeedback={engine.submitFeedback}
                onMute={engine.muteTTS}
                onUnmute={engine.unmuteTTS}
                onDrillDown={engine.submitQuery}
              />

              {/* Follow-up suggestions */}
              <FollowUpSuggestions
                result={engine.lastResult}
                onSelect={engine.submitQuery}
                disabled={engine.pipelineInFlight}
              />

              <div className="mt-8 w-full">
                <ExecutiveMemoryGraph
                  sessionId={engine.session.sessionId}
                  auth={auth}
                />
              </div>

              {/* New conversation button */}
              <div className="mt-10 mb-4 flex justify-center">
                <button
                  type="button"
                  onClick={engine.resetConversation}
                  aria-label="New conversation"
                  className="flex items-center gap-2 px-4 py-2 rounded-full text-sm text-[var(--text-muted)] hover:text-[var(--text-secondary)] border border-[var(--border)] hover:bg-[var(--bg-surface)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent-blue)] transition-all"
                >
                  <RotateCcw className="w-3.5 h-3.5" />
                  <span>New conversation</span>
                </button>
              </div>
            </motion.div>
          )}

        </AnimatePresence>
      </div>

      {/* ── Fixed bottom dock ─────────────────────────────────── */}
      <div className="fixed bottom-0 left-0 right-0 p-4 md:p-6 bg-gradient-to-t from-[var(--bg-base)] via-[var(--bg-base)]/95 to-transparent pointer-events-none z-20">
        <div className="pointer-events-auto max-w-2xl mx-auto space-y-2">
          {/* Phase 3.3: error/warning notices rendered above the dock */}
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
            onResetConversation={engine.resetConversation}
          />
        </div>
      </div>

      {/* ── Clarification overlay ─────────────────────────────── */}
      <AnimatePresence>
        {engine.clarification.pending && (
          <ClarificationOverlay
            clarification={engine.clarification}
            onResolve={engine.submitClarification}
          />
        )}
      </AnimatePresence>
    </main>
  );
}
