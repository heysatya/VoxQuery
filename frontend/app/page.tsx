"use client";

import { SignInButton, UserButton, useAuth } from "@clerk/nextjs";
import React from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ApiRequestError,
  audioSocketUrl,
  createSession,
  fetchResult,
  pipelineSocketUrl,
  postClarification,
  postFeedback,
  postTelemetry,
  submitQuery
} from "../lib/api";
import type {
  AudioEvent,
  ClarificationState,
  LastResult,
  MicPermission,
  PipelineEvent,
  RecordingState,
  SessionState
} from "../lib/types";

const tenantId =
  process.env.NEXT_PUBLIC_VOXQUERY_TENANT_ID ??
  process.env.NEXT_PUBLIC_FAKE_TENANT_ID ??
  "00000000-0000-0000-0000-000000000101";

const authMode = process.env.NEXT_PUBLIC_AUTH_MODE ?? "fake";

type AuthRelay = {
  mode: "fake" | "clerk";
  ready: boolean;
  signedIn: boolean;
  getToken: () => Promise<string | null>;
};

export default function HomePage() {
  if (authMode === "clerk") {
    return <ClerkHomePage />;
  }
  return <VoxQueryApp auth={fakeAuthRelay} />;
}

function ClerkHomePage() {
  const { isLoaded, isSignedIn, getToken } = useAuth();
  const auth = useMemo<AuthRelay>(
    () => ({
      mode: "clerk",
      ready: isLoaded,
      signedIn: Boolean(isSignedIn),
      getToken
    }),
    [getToken, isLoaded, isSignedIn]
  );

  if (!isLoaded) {
    return <main className="page-shell">Loading authentication...</main>;
  }

  if (!isSignedIn) {
    return (
      <main className="page-shell auth-shell">
        <section>
          <h1>VoxQuery</h1>
          <p>Sign in to start a secure voice analytics session.</p>
          <SignInButton mode="modal">
            <button className="primary-button">Sign in</button>
          </SignInButton>
        </section>
      </main>
    );
  }

  return (
    <>
      <div className="account-bar">
        <UserButton />
      </div>
      <VoxQueryApp auth={auth} />
    </>
  );
}

const fakeAuthRelay: AuthRelay = {
  mode: "fake",
  ready: true,
  signedIn: true,
  getToken: async () => "fake"
};

function VoxQueryApp({ auth }: { auth: AuthRelay }) {
  const [session, setSession] = useState<SessionState>({ sessionId: null, conversationId: null });
  const [micPermission, setMicPermission] = useState<MicPermission>("unknown");
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
  const [notice, setNotice] = useState(
    auth.mode === "clerk"
      ? "Clerk auth mode active. Requests use the signed-in session token."
      : "Local fake mode active. No external credentials are required."
  );
  const modeLabel = auth.mode === "clerk" ? "clerk auth mode" : "local fake mode";

  const audioSocketRef = useRef<WebSocket | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const audioWorkletRef = useRef<AudioWorkletNode | null>(null);

  const apiReady = useMemo(
    () => auth.ready && auth.signedIn && Boolean(session.sessionId),
    [auth.ready, auth.signedIn, session.sessionId]
  );

  const ensureSession = useCallback(async () => {
    if (!auth.ready || !auth.signedIn) {
      return;
    }
    const existingSessionId =
      typeof window !== "undefined" ? window.sessionStorage.getItem("voxquery_session_id") : null;
    if (existingSessionId) {
      if (session.sessionId !== existingSessionId) {
        setSession({ sessionId: existingSessionId, conversationId: null });
      }
      return;
    }
    const created = await createSession(tenantId, await auth.getToken());
    window.sessionStorage.setItem("voxquery_session_id", created.session_id);
    setSession({ sessionId: created.session_id, conversationId: created.conversation_id });
  }, [auth, session.sessionId]);

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
      const created = await createSession(tenantId, await auth.getToken());
      window.sessionStorage.setItem("voxquery_session_id", created.session_id);
      setSession({ sessionId: created.session_id, conversationId: created.conversation_id });
      setNotice("New conversation started.");
    } catch (error) {
      setNotice(errorMessage(error, "Could not create a new local conversation."));
    }
  }, [auth]);

  useEffect(() => {
    ensureSession().catch(() => setNotice("Could not create a local session. Is the backend running?"));
  }, [ensureSession]);

  // Probe microphone permission status on mount (read-only; does not prompt the user).
  // The Permissions API is absent in some environments (jsdom, old browsers, HTTP contexts)
  // so all access is guarded. Failures are silent — the user can still use text input.
  useEffect(() => {
    if (typeof navigator === "undefined" || !navigator.permissions) {
      return;
    }
    navigator.permissions
      .query({ name: "microphone" as PermissionName })
      .then((status) => {
        setMicPermission(status.state as MicPermission);
        status.onchange = () => {
          setMicPermission(status.state as MicPermission);
        };
      })
      .catch(() => {
        // Permissions API may throw in some environments; leave state as 'unknown'.
      });
  }, []);

  useEffect(() => {
    if (!session.sessionId || !auth.ready || !auth.signedIn) {
      return;
    }
    let socket: WebSocket | null = null;
    let cancelled = false;
    auth
      .getToken()
      .then((token) => {
        if (cancelled || !session.sessionId) {
          return;
        }
        socket = new WebSocket(pipelineSocketUrl(session.sessionId, token));
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
          createSession(tenantId, token)
            .then((created) => {
              window.sessionStorage.setItem("voxquery_session_id", created.session_id);
              setSession({ sessionId: created.session_id, conversationId: created.conversation_id });
          setNotice("Stored session expired. New conversation started.");
            })
            .catch(() => setNotice("Stored session expired, and a new local session could not be created."));
        };
      })
      .catch(() => setNotice("Could not get an auth token for the pipeline stream."));
    return () => {
      cancelled = true;
      socket?.close();
    };
  }, [auth, session.sessionId]);

  async function handleStartRecording() {
    // Guard: browser API unavailable (HTTP context, old browser, jsdom).
    if (
      typeof navigator === "undefined" ||
      !navigator.mediaDevices ||
      typeof navigator.mediaDevices.getUserMedia !== "function"
    ) {
      setNotice("Microphone is unavailable in this context. Use text input or Fake voice.");
      return;
    }
    // Guard: permission already known to be denied.
    if (micPermission === "denied") {
      setNotice("Microphone access denied. Allow access in browser settings or use text input.");
      return;
    }
    // Guard: ensure session exists before prompting for mic.
    if (!session.sessionId) {
      setNotice("Session is not ready. Cannot start recording.");
      return;
    }

    try {
      // This call may prompt the user. On grant, permission is 'granted'.
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      setMicPermission("granted");
      
      const token = await auth.getToken();
      
      // Emit stt.mic.permission via telemetry endpoint
      await postTelemetry({ event: "stt.mic.permission", outcome: "granted", session_id: session.sessionId }, token).catch(console.error);
      
      setRecordingState("connecting");
      setNotice("Microphone access granted. Connecting...");
      
      const socket = new WebSocket(audioSocketUrl(session.sessionId, token));
      audioSocketRef.current = socket;
      mediaStreamRef.current = stream;
      
      socket.onopen = async () => {
        try {
          const audioContext = new (window.AudioContext || (window as any).webkitAudioContext)();
          audioContextRef.current = audioContext;
          
          await audioContext.audioWorklet.addModule('/audio-processor.js');
          
          const source = audioContext.createMediaStreamSource(stream);
          const worklet = new AudioWorkletNode(audioContext, 'pcm-audio-processor');
          audioWorkletRef.current = worklet;
          
          worklet.port.onmessage = (e) => {
            if (socket.readyState === WebSocket.OPEN) {
              socket.send(e.data);
            }
          };
          
          source.connect(worklet);
          
          const zeroGain = audioContext.createGain();
          zeroGain.gain.value = 0;
          worklet.connect(zeroGain);
          zeroGain.connect(audioContext.destination); // Required for worklet to run in some browsers
          
          setRecordingState("recording");
          setNotice("Recording...");
        } catch (error) {
          setRecordingState("idle");
          setNotice("Failed to initialize audio processing.");
          recorderCleanup();
        }
      };
      
      socket.onmessage = (message) => {
        const event = parseSocketEvent<AudioEvent>(message.data);
        if (!event) return;
        
        if (event.type === "interim_transcript") {
          setPartialTranscript(event.text);
        } else if (event.type === "final_transcript") {
          setPartialTranscript(event.text);
          setSubmittedText(event.text);
          setRecordingState("idle");
          setNotice("Transcript received. Review or edit before submitting.");
          // We can safely close here, final is received.
          recorderCleanup();
        } else if (event.type === "error") {
          setRecordingState("idle");
          setNotice(event.message);
          recorderCleanup();
        }
      };
      
      socket.onerror = () => {
        setRecordingState("idle");
        setNotice("Audio WebSocket unavailable or error occurred.");
        recorderCleanup();
      };
      
      socket.onclose = () => {
        setRecordingState((prev) => (prev === "recording" || prev === "processing" ? "idle" : prev));
        if (audioSocketRef.current === socket) {
          audioSocketRef.current = null;
        }
        recorderCleanup();
      };
      
    } catch (err) {
      const domErr = err as { name?: string };
      if (domErr?.name === "NotAllowedError" || domErr?.name === "PermissionDeniedError") {
        setMicPermission("denied");
        const token = await auth.getToken();
        if (session.sessionId) {
          await postTelemetry({ event: "stt.mic.permission", outcome: "denied", session_id: session.sessionId }, token).catch(console.error);
        }
        setNotice("Microphone access denied. Allow access in browser settings or use text input.");
        setRecordingState("idle");
      } else {
        setNotice("Could not access microphone. Try again or use text input.");
        setRecordingState("idle");
      }
    }
  }
  
  function recorderCleanup() {
    if (audioWorkletRef.current) {
      audioWorkletRef.current.disconnect();
      audioWorkletRef.current = null;
    }
    if (mediaStreamRef.current) {
      mediaStreamRef.current.getTracks().forEach(track => track.stop());
      mediaStreamRef.current = null;
    }
    if (audioContextRef.current) {
      if (audioContextRef.current.state !== "closed") {
        audioContextRef.current.close().catch(console.error);
      }
      audioContextRef.current = null;
    }
    if (audioSocketRef.current) {
      const socket = audioSocketRef.current;
      audioSocketRef.current = null;
      // Remove onclose handler to prevent infinite recursion
      socket.onclose = null;
      if (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING) {
        socket.close();
      }
    }
  }

  function handleStopRecording() {
    // 1. Stop mic tracks
    if (mediaStreamRef.current) {
      mediaStreamRef.current.getTracks().forEach(track => track.stop());
    }
    // 2. Suspend/Close audio context
    if (audioContextRef.current && audioContextRef.current.state !== "closed") {
      audioContextRef.current.suspend().catch(console.error);
    }
    // 3. Send stop_recording JSON, but keep WS open for final transcript
    if (audioSocketRef.current && audioSocketRef.current.readyState === WebSocket.OPEN) {
      audioSocketRef.current.send(JSON.stringify({ type: "stop_recording" }));
    }
    
    setRecordingState("processing");
    setNotice("Recording stopped. Processing transcript...");
  }

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
    const socket = new WebSocket(audioSocketUrl(session.sessionId, await auth.getToken()));
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
      const accepted = await submitQuery(
        {
          session_id: session.sessionId,
          submitted_text: submittedText,
          input_modality: "text",
          raw_transcript: null,
          stt_confidence: null
        },
        await auth.getToken()
      );
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
        await postClarification(
          {
            session_id: session.sessionId,
            turn_id: currentTurnId,
            selection: null,
            resolution_type: "escaped"
          },
          await auth.getToken()
        );
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
      await postClarification(
        {
          session_id: session.sessionId,
          turn_id: currentTurnId,
          selection,
          resolution_type: "option_selected"
        },
        await auth.getToken()
      );
      setClarification({ pending: false, question: null, options: [], secondsRemaining: 30 });
      setNotice("Clarification submitted. Waiting for pipeline result.");
    } catch (error) {
      setPipelineInFlight(false);
      setNotice(errorMessage(error, "Could not resolve clarification. Try submitting again."));
    }
  }

  async function loadResult(turnId: string) {
    setPipelineStage("rendering");
    const result = await fetchResult(turnId, await auth.getToken());
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
      await postFeedback(
        { session_id: session.sessionId, turn_id: lastResult.turnId, rating: -1 },
        await auth.getToken()
      );
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
          <span>{modeLabel}</span>
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
            {recordingState === "recording" ? (
              <button type="button" onClick={handleStopRecording} disabled={pipelineInFlight}>
                Stop recording
              </button>
            ) : (
              <button
                type="button"
                onClick={handleStartRecording}
                disabled={
                  pipelineInFlight ||
                  recordingState === "connecting" ||
                  recordingState === "processing"
                }
              >
                Start recording
              </button>
            )}
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
