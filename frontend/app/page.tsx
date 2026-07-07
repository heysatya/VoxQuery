"use client";

import { SignInButton, UserButton, useAuth } from "@clerk/nextjs";
import React, { useMemo } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { RotateCcw } from "lucide-react";
import { useVoxQuerySession, type VoxQueryAuthRelay } from "./hooks/useVoxQuerySession";
import { VoiceVisualizer } from "./components/hero/VoiceVisualizer";
import { DataGlassPanel } from "./components/data/DataGlassPanel";
import { InsightNarrative } from "./components/insight/InsightNarrative";
import { FollowUpSuggestions } from "./components/insight/FollowUpSuggestions";
import { ClarificationOverlay } from "./components/clarification/ClarificationOverlay";
import { QueryDock } from "./components/query/QueryDock";

const authMode = process.env.NEXT_PUBLIC_AUTH_MODE ?? "fake";

/* ── Auth wrappers (unchanged contracts) ─────────────────────── */

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

/* ── Human-readable status mapping ───────────────────────────── */

function getHumanStatus(pipelineStage: string | null): string {
  if (!pipelineStage) return "Analyzing your data...";
  const map: Record<string, string> = {
    stt: "Processing your voice...",
    rag_retrieval: "Understanding your question...",
    sql_generation: "Crafting the query...",
    sql_validation: "Verifying accuracy...",
    sql_execution: "Running against your data...",
    chart_selection: "Building your chart...",
    tts_generation: "Preparing the summary...",
  };
  return map[pipelineStage] || "Analyzing your data...";
}

/* ── Starter questions ───────────────────────────────────────── */

const STARTER_QUESTIONS = [
  "How did revenue perform last quarter?",
  "What are the top-selling products?",
  "Show me pipeline by region",
];

/* ── Main App ────────────────────────────────────────────────── */

function VoxQueryApp({ auth }: { auth: VoxQueryAuthRelay }) {
  const engine = useVoxQuerySession(auth);

  const isActive = engine.recordingState !== "idle" || engine.pipelineInFlight;
  const hasResult = !!engine.lastResult;

  // Three UI states: ready → active → insight
  const uiState: "ready" | "active" | "insight" =
    isActive ? "active" : hasResult ? "insight" : "ready";

  return (
    <main className="min-h-screen flex flex-col relative">
      {/* Scrollable content */}
      <div className="flex-1 flex flex-col items-center px-4 md:px-8 pb-40 overflow-y-auto scrollbar-hide">

        <AnimatePresence mode="wait">

          {/* ── STATE 1: READY ──────────────────────────────── */}
          {uiState === "ready" && (
            <motion.div
              key="ready"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0, y: -20 }}
              transition={{ duration: 0.4 }}
              className="flex-1 flex flex-col items-center justify-center min-h-[80vh] max-w-2xl w-full"
            >
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
                    className="px-4 py-2.5 rounded-full border border-[var(--border)] bg-[var(--bg-surface)] text-sm text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:border-[var(--accent-blue)]/30 hover:bg-[var(--bg-elevated)] transition-all disabled:opacity-50"
                  >
                    {q}
                  </button>
                ))}
              </div>
            </motion.div>
          )}

          {/* ── STATE 2: ACTIVE (recording / processing) ──── */}
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

              {/* Human-readable status */}
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
                    {getHumanStatus(engine.pipelineStage)}
                  </span>
                </motion.div>
              )}
            </motion.div>
          )}

          {/* ── STATE 3: INSIGHT ────────────────────────────── */}
          {uiState === "insight" && engine.lastResult && (
            <motion.div
              key="insight"
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.5, ease: [0.23, 1, 0.32, 1] }}
              className="w-full max-w-3xl pt-10 md:pt-16"
            >
              {/* Question echo */}
              <div className="flex items-center gap-3 mb-8">
                <div className="w-8 h-8 rounded-full bg-gradient-to-br from-[var(--accent-blue)] to-indigo-600 flex-shrink-0" />
                <p className="text-lg text-[var(--text-secondary)] font-light">
                  {engine.submittedText}
                </p>
              </div>

              {/* Narrative — the hero */}
              <InsightNarrative
                text={engine.lastResult.resultData.tts_text}
                isMuted={engine.isMuted}
                onToggleMute={engine.isMuted ? engine.unmuteTTS : engine.muteTTS}
              />

              {/* Chart card */}
              <DataGlassPanel
                result={engine.lastResult}
                feedbackSubmitted={engine.feedbackSubmitted}
                isMuted={engine.isMuted}
                onFeedback={() => engine.submitFeedback(-1)}
                onMute={engine.muteTTS}
                onUnmute={engine.unmuteTTS}
              />

              {/* Follow-up suggestions */}
              <FollowUpSuggestions
                result={engine.lastResult}
                onSelect={engine.submitQuery}
                disabled={engine.pipelineInFlight}
              />

              {/* New conversation button */}
              <div className="mt-10 flex justify-center">
                <button
                  type="button"
                  onClick={engine.resetConversation}
                  className="flex items-center gap-2 px-4 py-2 rounded-full text-sm text-[var(--text-muted)] hover:text-[var(--text-secondary)] border border-[var(--border)] hover:border-[var(--border)] hover:bg-[var(--bg-surface)] transition-all"
                >
                  <RotateCcw className="w-3.5 h-3.5" />
                  <span>New conversation</span>
                </button>
              </div>
            </motion.div>
          )}

        </AnimatePresence>
      </div>

      {/* ── Fixed bottom dock ──────────────────────────────── */}
      <div className="fixed bottom-0 left-0 right-0 p-4 md:p-6 bg-gradient-to-t from-[var(--bg-base)] via-[var(--bg-base)]/95 to-transparent pointer-events-none z-20">
        <div className="pointer-events-auto">
          <QueryDock
            value={engine.submittedText}
            disabled={!engine.isReady || engine.pipelineInFlight}
            isReady={engine.isReady}
            recordingState={engine.recordingState}
            notice={engine.notice}
            modeLabel={engine.modeLabel}
            onChange={engine.setSubmittedText}
            onSubmit={engine.submitCurrentQuery}
            onFakeVoice={engine.startFakeVoice}
            onResetConversation={engine.resetConversation}
          />
        </div>
      </div>

      {/* ── Clarification overlay ──────────────────────────── */}
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
