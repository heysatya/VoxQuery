"use client";

import React from "react";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ApiRequestError,
  audioSocketUrl,
  createSession,
  fetchResult,
  pipelineSocketUrl,
  postClarification,
  postFeedback,
  submitQuery
} from "../lib/api";
import type {
  AudioEvent,
  ClarificationState,
  LastResult,
  PipelineEvent,
  RecordingState,
  SessionState
} from "../lib/types";

const tenantId =
  process.env.NEXT_PUBLIC_FAKE_TENANT_ID ?? "00000000-0000-0000-0000-000000000101";

export default function HomePage() {
  const [session, setSession] = useState<SessionState>({ sessionId: null, conversationId: null });
  const [recordingState, setRecordingState] = useState<RecordingState>("idle");
  const [partialTranscript, setPartialTranscript] = useState("");
  const [submittedText, setSubmittedText] = useState("");
  const [pipelineInFlight, setPipelineInFlight] = useState(false);
  const [currentTurnId, setCurrentTurnId] = useState<string | null>(null);
  const [pipelineStage, setPipelineStage] = useState<string | null>(null);
  const [feedbackSubmitted, setFeedbackSubmitted] = useState(false);
  const [clarification, setClarification] = useState<ClarificationState>({
    pending: false,
    question: null,
    options: [],
    secondsRemaining: 30
  });
  const [lastResult, setLastResult] = useState<LastResult | null>(null);
  const [notice, setNotice] = useState("Local fake mode active. No external credentials are required.");

  const apiReady = useMemo(() => Boolean(session.sessionId), [session.sessionId]);

  const ensureSession = useCallback(async () => {
    const existingSessionId =
      typeof window !== "undefined" ? window.sessionStorage.getItem("voxquery_session_id") : null;
    if (existingSessionId) {
      if (session.sessionId !== existingSessionId) {
        setSession({ sessionId: existingSessionId, conversationId: null });
      }
      return;
    }
    const created = await createSession(tenantId);
    window.sessionStorage.setItem("voxquery_session_id", created.session_id);
    setSession({ sessionId: created.session_id, conversationId: created.conversation_id });
  }, [session.sessionId]);

  const startNewConversation = useCallback(async () => {
    setPipelineInFlight(false);
    setPipelineStage(null);
    setCurrentTurnId(null);
    setPartialTranscript("");
    setSubmittedText("");
    setRecordingState("idle");
    setFeedbackSubmitted(false);
    setClarification({ pending: false, question: null, options: [], secondsRemaining: 30 });
    setLastResult(null);
    if (typeof window !== "undefined") {
      window.sessionStorage.removeItem("voxquery_session_id");
    }
    setSession({ sessionId: null, conversationId: null });
    try {
      const created = await createSession(tenantId);
      window.sessionStorage.setItem("voxquery_session_id", created.session_id);
      setSession({ sessionId: created.session_id, conversationId: created.conversation_id });
      setNotice("New local conversation started.");
    } catch (error) {
      setNotice(errorMessage(error, "Could not create a new local conversation."));
    }
  }, []);

  useEffect(() => {
    ensureSession().catch(() => setNotice("Could not create a local session. Is the backend running?"));
  }, [ensureSession]);

  useEffect(() => {
    if (!session.sessionId) {
      return;
    }
    const socket = new WebSocket(pipelineSocketUrl(session.sessionId));
    socket.onmessage = (message) => {
      const event = parseSocketEvent<PipelineEvent>(message.data);
      if (!event) {
        return;
      }
      if (event.type === "pipeline_progress") {
        setPipelineStage(event.stage);
        return;
      }
      if (event.type === "clarification_request") {
        setCurrentTurnId(event.turn_id);
        setClarification({
          pending: true,
          question: event.question,
          options: event.options,
          secondsRemaining: event.timeout_seconds
        });
        setPipelineInFlight(false);
        setPipelineStage("clarification_pending");
        setNotice("Clarification required before executing the query.");
        return;
      }
      if (event.type === "clarification_timeout_warning") {
        setClarification((current) => ({
          ...current,
          secondsRemaining: event.seconds_remaining
        }));
        setNotice("Clarification will time out soon. Choose an option or rephrase.");
        return;
      }
      if (event.type === "result_ready") {
        setCurrentTurnId(event.turn_id);
        setPipelineInFlight(false);
        void loadResult(event.turn_id).catch((error) =>
          setNotice(errorMessage(error, "Result is ready, but could not be loaded."))
        );
        return;
      }
      if (event.type === "pipeline_error") {
        setPipelineInFlight(false);
        setPipelineStage(null);
        setNotice(event.message);
      }
    };
    socket.onerror = () => setNotice("Pipeline event stream unavailable. Check that the backend is running.");
    socket.onclose = (event) => {
      if (event.code !== 4002) {
        return;
      }
      window.sessionStorage.removeItem("voxquery_session_id");
      setSession({ sessionId: null, conversationId: null });
      createSession(tenantId)
        .then((created) => {
          window.sessionStorage.setItem("voxquery_session_id", created.session_id);
          setSession({ sessionId: created.session_id, conversationId: created.conversation_id });
          setNotice("Stored session expired. New local conversation started.");
        })
        .catch(() => setNotice("Stored session expired, and a new local session could not be created."));
    };
    return () => socket.close();
  }, [session.sessionId]);

  async function handleFakeVoice() {
    if (!session.sessionId) {
      setNotice("Session is still starting. Try fake voice again in a moment.");
      return;
    }
    if (typeof WebSocket === "undefined") {
      setNotice("WebSocket support is unavailable in this browser.");
      return;
    }
    setRecordingState("connecting");
    setNotice("Connecting to local fake STT WebSocket.");
    const socket = new WebSocket(audioSocketUrl(session.sessionId));
    socket.onopen = () => {
      setRecordingState("recording");
      socket.send(new Uint8Array([1, 2, 3]));
      setRecordingState("processing");
      socket.send(JSON.stringify({ type: "stop_recording" }));
    };
    socket.onmessage = (message) => {
      const event = parseSocketEvent<AudioEvent>(message.data);
      if (!event) {
        return;
      }
      if (event.type === "interim_transcript") {
        setPartialTranscript(event.text);
        return;
      }
      if (event.type === "final_transcript") {
        setPartialTranscript(event.text);
        setSubmittedText(event.text);
        setRecordingState("idle");
        setNotice("Fake voice transcript received. Review or edit before submitting.");
        socket.close();
        return;
      }
      if (event.type === "error") {
        setRecordingState("idle");
        setNotice(event.message);
      }
    };
    socket.onerror = () => {
      setRecordingState("idle");
      setNotice("Fake voice WebSocket unavailable. Check that the backend is running.");
    };
    socket.onclose = () => setRecordingState("idle");
  }

  async function handleSubmit() {
    if (pipelineInFlight) {
      setNotice("A query is already running. Please wait for it to complete.");
      return;
    }
    if (!session.sessionId || !submittedText.trim()) {
      setNotice("Please enter a question before submitting.");
      return;
    }
    setPipelineInFlight(true);
    setPipelineStage("sql_generation");
    setLastResult(null);
    setFeedbackSubmitted(false);
    setClarification({ pending: false, question: null, options: [], secondsRemaining: 30 });
    try {
      const accepted = await submitQuery({
        session_id: session.sessionId,
        submitted_text: submittedText,
        input_modality: "text",
        raw_transcript: null,
        stt_confidence: null
      });
      setCurrentTurnId(accepted.turn_id);
      setFeedbackSubmitted(false);
      setNotice("Query submitted. Waiting for pipeline events.");
    } catch (error) {
      setPipelineInFlight(false);
      setNotice(errorMessage(error, "Query failed. Check that the backend is running."));
    }
  }

  async function handleClarification(selection: string | null) {
    if (!session.sessionId || !currentTurnId) {
      return;
    }
    if (selection === null) {
      try {
        await postClarification({
          session_id: session.sessionId,
          turn_id: currentTurnId,
          selection: null,
          resolution_type: "escaped"
        });
        setClarification({ pending: false, question: null, options: [], secondsRemaining: 30 });
        setPipelineStage(null);
        setCurrentTurnId(null);
        setNotice("Clarification escaped. Edit your question and submit again.");
      } catch (error) {
        setNotice(errorMessage(error, "Could not escape clarification. Try submitting again."));
      }
      return;
    }

    setPipelineInFlight(true);
    setPipelineStage("snowflake_executing");
    try {
      await postClarification({
        session_id: session.sessionId,
        turn_id: currentTurnId,
        selection,
        resolution_type: "option_selected"
      });
      setClarification({ pending: false, question: null, options: [], secondsRemaining: 30 });
      setNotice("Clarification submitted. Waiting for pipeline result.");
    } catch (error) {
      setPipelineInFlight(false);
      setNotice(errorMessage(error, "Could not resolve clarification. Try submitting again."));
    }
  }

  async function loadResult(turnId: string) {
    setPipelineStage("rendering");
    const result = await fetchResult(turnId);
    setLastResult({
      turnId,
      confidenceTier: result.confidence_tier,
      chartType: result.chart_type,
      chartRationale: result.chart_rationale,
      resultData: result,
      proactiveQuestions: [
        "Show that by quarter",
        "Compare this with last month",
        "Break it down by customer segment"
      ]
    });
    setPipelineInFlight(false);
    setPipelineStage(null);
    setNotice("Result ready.");
  }

  async function handleFeedback() {
    if (!session.sessionId || !lastResult) {
      return;
    }
    if (feedbackSubmitted) {
      setNotice("Feedback already recorded for this query.");
      return;
    }
    try {
      await postFeedback({ session_id: session.sessionId, turn_id: lastResult.turnId, rating: -1 });
      setFeedbackSubmitted(true);
      setNotice("Feedback recorded for threshold tuning.");
    } catch (error) {
      setNotice(errorMessage(error, "Could not record feedback."));
    }
  }

  return (
    <main className="page-shell">
      <section className="workbench">
        <header className="topbar">
          <div>
            <h1>VoxQuery</h1>
            <p>Voice subsystem local MVP</p>
          </div>
          <button type="button" onClick={startNewConversation}>
            New conversation
          </button>
        </header>

        <div className="status-row">
          <span>Session {apiReady ? "active" : "starting"}</span>
          <span>{recordingState}</span>
          <span>{pipelineStage ?? "idle"}</span>
          <span>local fake mode</span>
        </div>

        <section className="input-panel">
          <label htmlFor="query">Ask a data question</label>
          <textarea
            id="query"
            value={submittedText}
            disabled={pipelineInFlight}
            onChange={(event) => setSubmittedText(event.target.value)}
            placeholder="Show net revenue by customer segment"
          />
          {partialTranscript ? <p className="partial">Raw transcript: {partialTranscript}</p> : null}
          <div className="actions">
            <button type="button" onClick={handleFakeVoice} disabled={pipelineInFlight}>
              Fake voice
            </button>
            <button type="button" onClick={handleSubmit} disabled={!apiReady || pipelineInFlight}>
              Submit
            </button>
          </div>
        </section>

        {clarification.pending ? (
          <section className="clarification">
            <h2>{clarification.question}</h2>
            <p className="partial">{clarification.secondsRemaining}s remaining</p>
            <div className="option-grid">
              {clarification.options.map((option) => (
                <button key={option} type="button" onClick={() => handleClarification(option)}>
                  {option}
                </button>
              ))}
            </div>
            <button type="button" className="link-button" onClick={() => handleClarification(null)}>
              None of these - let me rephrase
            </button>
          </section>
        ) : null}

        {lastResult ? (
          <section className="result-panel">
            <div className="result-header">
              <h2>Result</h2>
              <span className="confidence">{lastResult.confidenceTier}</span>
            </div>
            <p>{lastResult.chartRationale}</p>
            <table>
              <thead>
                <tr>
                  {lastResult.resultData.result.columns.map((column) => (
                    <th key={column}>{column}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {lastResult.resultData.result.rows.map((row, rowIndex) => (
                  <tr key={rowIndex}>
                    {row.map((cell, cellIndex) => (
                      <td key={cellIndex}>{cell}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
            <details>
              <summary>View SQL</summary>
              <pre>{lastResult.resultData.generated_sql}</pre>
            </details>
            <div className="actions">
              <button type="button" onClick={handleFeedback}>
                {feedbackSubmitted ? "Feedback recorded" : "Thumbs down"}
              </button>
            </div>
          </section>
        ) : null}

        <p className="notice">{notice}</p>
      </section>
    </main>
  );
}

function errorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiRequestError) {
    return error.message;
  }
  return fallback;
}

function parseSocketEvent<T>(data: unknown): T | null {
  if (typeof data !== "string") {
    return null;
  }
  try {
    return JSON.parse(data) as T;
  } catch {
    return null;
  }
}
