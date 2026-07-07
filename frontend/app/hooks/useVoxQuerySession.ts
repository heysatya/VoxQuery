import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  audioSocketUrl,
  createSession,
  deleteSession,
  fetchResult,
  pipelineSocketUrl,
  postClarification,
  postFeedback,
  postTelemetry,
  submitQuery as submitQueryApi,
  ttsSocketUrl
} from "../../lib/api";
import type {
  AudioEvent,
  ClarificationState,
  LastResult,
  MicPermission,
  PipelineEvent,
  RecordingState,
  SessionState
} from "../../lib/types";

export type VoxQueryAuthMode = "fake" | "clerk";

export type VoxQueryAuthRelay = {
  mode: VoxQueryAuthMode;
  ready: boolean;
  signedIn: boolean;
  getToken: () => Promise<string | null>;
};

export type VoxQueryEngine = {
  authMode: VoxQueryAuthMode;
  modeLabel: string;
  isReady: boolean;
  session: SessionState;

  submittedText: string;
  partialTranscript: string;
  pipelineInFlight: boolean;
  pipelineStage: string | null;
  lastResult: LastResult | null;
  clarification: ClarificationState;
  notice: string;

  micPermission: MicPermission;
  recordingState: RecordingState;
  audioAnalyserNode: AnalyserNode | null;
  isMuted: boolean;

  feedbackSubmitted: boolean;

  setSubmittedText: (value: string) => void;
  startRecording: () => Promise<void>;
  stopRecording: () => void;
  toggleRecording: () => Promise<void>;
  startFakeVoice: () => Promise<void>;
  submitCurrentQuery: () => Promise<void>;
  submitQuery: (text: string) => Promise<void>;
  submitClarification: (selection: string | null) => Promise<void>;
  submitFeedback: (rating?: -1) => Promise<void>;
  resetConversation: () => Promise<void>;
  muteTTS: () => void;
  unmuteTTS: () => void;
};

const tenantId =
  process.env.NEXT_PUBLIC_VOXQUERY_TENANT_ID ??
  process.env.NEXT_PUBLIC_FAKE_TENANT_ID ??
  "00000000-0000-0000-0000-000000000101";

function parseSocketEvent<T>(data: string): T | null {
  try {
    return JSON.parse(data) as T;
  } catch {
    return null;
  }
}

function errorMessage(error: unknown, fallback: string) {
  if (error instanceof Error) return error.message;
  return fallback;
}

export function useVoxQuerySession(auth: VoxQueryAuthRelay): VoxQueryEngine {
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
  const [audioAnalyserNode, setAudioAnalyserNode] = useState<AnalyserNode | null>(null);

  const ttsAudioContextRef = useRef<AudioContext | null>(null);
  const ttsSocketRef = useRef<WebSocket | null>(null);
  const nextPlayTimeRef = useRef<number>(0);
  const [isMuted, setIsMuted] = useState(false);

  const isReady = useMemo(
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

  const resetConversation = useCallback(async () => {
    setPipelineInFlight(false);
    setPipelineStage(null);
    setCurrentTurnId(null);
    setPartialTranscript("");
    setSubmittedText("");
    setRecordingState("idle");
    setFeedbackSubmitted(false);
    setClarification({ pending: false, question: null, options: [], secondsRemaining: 30 });
    setLastResult(null);
    stopTTS();
    recorderCleanup();
    if (session.sessionId) {
      try {
        await deleteSession(session.sessionId, await auth.getToken());
      } catch (error) {
        console.warn("Could not explicitly delete session on backend", error);
      }
    }
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
  }, [auth, session.sessionId]);

  useEffect(() => {
    ensureSession().catch(() => setNotice("Could not create a local session. Is the backend running?"));
  }, [ensureSession]);

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

  function recorderCleanup() {
    if (audioWorkletRef.current) {
      audioWorkletRef.current.disconnect();
      audioWorkletRef.current = null;
    }
    setAudioAnalyserNode(null);
    if (mediaStreamRef.current) {
      mediaStreamRef.current.getTracks().forEach((track) => track.stop());
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
      socket.onclose = null;
      if (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING) {
        socket.close();
      }
    }
  }

  async function startRecording() {
    if (
      typeof navigator === "undefined" ||
      !navigator.mediaDevices ||
      typeof navigator.mediaDevices.getUserMedia !== "function"
    ) {
      setNotice("Microphone is unavailable in this context. Use text input or Fake voice.");
      return;
    }
    if (micPermission === "denied") {
      setNotice("Microphone access denied. Allow access in browser settings or use text input.");
      return;
    }
    if (!session.sessionId) {
      setNotice("Session is not ready. Cannot start recording.");
      return;
    }

    try {
      ensureTTSContext();
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      setMicPermission("granted");

      const token = await auth.getToken();
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

          await audioContext.audioWorklet.addModule("/audio-processor.js");

          const source = audioContext.createMediaStreamSource(stream);
          const analyser = audioContext.createAnalyser();
          analyser.fftSize = 256;
          setAudioAnalyserNode(analyser);

          const worklet = new AudioWorkletNode(audioContext, "pcm-audio-processor");
          audioWorkletRef.current = worklet;

          worklet.port.onmessage = (e) => {
            if (socket.readyState === WebSocket.OPEN) {
              socket.send(e.data);
            }
          };

          source.connect(analyser);
          analyser.connect(worklet);

          const zeroGain = audioContext.createGain();
          zeroGain.gain.value = 0;
          worklet.connect(zeroGain);
          zeroGain.connect(audioContext.destination);

          setRecordingState("recording");
          setNotice("Recording...");
        } catch (error) {
          console.error("Audio processor initialization error:", error);
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

  function stopRecording() {
    if (mediaStreamRef.current) {
      mediaStreamRef.current.getTracks().forEach((track) => track.stop());
    }
    if (audioContextRef.current && audioContextRef.current.state !== "closed") {
      audioContextRef.current.suspend().catch(console.error);
    }
    if (audioSocketRef.current && audioSocketRef.current.readyState === WebSocket.OPEN) {
      audioSocketRef.current.send(JSON.stringify({ type: "stop_recording" }));
    }
    setRecordingState("processing");
    setNotice("Recording stopped. Processing transcript...");
  }

  async function toggleRecording() {
    if (recordingState === "recording") {
      stopRecording();
    } else if (recordingState === "idle" && !pipelineInFlight) {
      await startRecording();
    }
  }

  async function startFakeVoice() {
    if (!session.sessionId) {
      setNotice("Session is still starting. Try fake voice again in a moment.");
      return;
    }
    if (typeof WebSocket === "undefined") {
      setNotice("WebSocket support is unavailable in this browser.");
      return;
    }
    ensureTTSContext();
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

  async function submitQuery(text: string) {
    if (pipelineInFlight) {
      setNotice("A query is already running. Please wait for it to complete.");
      return;
    }
    if (!session.sessionId || !text.trim()) {
      setNotice("Please enter a question before submitting.");
      return;
    }

    const isFollowUp = !!lastResult;
    const fullText = (isFollowUp && submittedText) ? `${submittedText} → ${text}` : text;
    setSubmittedText(fullText);

    setPipelineInFlight(true);
    setPipelineStage("sql_generation");
    setLastResult(null);
    setFeedbackSubmitted(false);
    setClarification({ pending: false, question: null, options: [], secondsRemaining: 30 });
    try {
      ensureTTSContext();
      const accepted = await submitQueryApi(
        {
          session_id: session.sessionId,
          submitted_text: fullText,
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

  async function submitCurrentQuery() {
    await submitQuery(submittedText);
  }

  async function submitClarification(selection: string | null) {
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

    const token = await auth.getToken();
    playTTS(turnId, token);
  }

  function ensureTTSContext() {
    if (!ttsAudioContextRef.current || ttsAudioContextRef.current.state === "closed") {
      ttsAudioContextRef.current = new (window.AudioContext || (window as any).webkitAudioContext)({ sampleRate: 16000 });
    }
    if (ttsAudioContextRef.current.state === "suspended") {
      ttsAudioContextRef.current.resume().catch(console.error);
    }
    return ttsAudioContextRef.current;
  }

  function playTTS(turnId: string, token: string | null) {
    if (!session.sessionId) return;

    if (ttsSocketRef.current) {
      ttsSocketRef.current.close();
      ttsSocketRef.current = null;
    }
    setIsMuted(false);

    try {
      const audioCtx = ensureTTSContext();
      nextPlayTimeRef.current = audioCtx.currentTime + 0.1;

      const socket = new WebSocket(ttsSocketUrl(session.sessionId, turnId, token));
      socket.binaryType = "arraybuffer";
      ttsSocketRef.current = socket;

      socket.onmessage = (event) => {
        if (ttsAudioContextRef.current?.state === "closed") return;

        const buffer = event.data as ArrayBuffer;
        const int16Array = new Int16Array(buffer);
        const float32Array = new Float32Array(int16Array.length);
        for (let i = 0; i < int16Array.length; i++) {
          float32Array[i] = int16Array[i] / 32768.0;
        }

        const audioBuffer = audioCtx.createBuffer(1, float32Array.length, 16000);
        audioBuffer.getChannelData(0).set(float32Array);

        const source = audioCtx.createBufferSource();
        source.buffer = audioBuffer;
        source.connect(audioCtx.destination);

        const startTime = Math.max(nextPlayTimeRef.current, audioCtx.currentTime);
        source.start(startTime);
        nextPlayTimeRef.current = startTime + audioBuffer.duration;
      };
    } catch (e) {
      console.error("TTS playback failed to initialize", e);
    }
  }

  function stopTTS() {
    setIsMuted(true);
    if (ttsSocketRef.current) {
      ttsSocketRef.current.close();
      ttsSocketRef.current = null;
    }
    if (ttsAudioContextRef.current && ttsAudioContextRef.current.state !== "closed") {
      ttsAudioContextRef.current.close().catch(console.error);
      ttsAudioContextRef.current = null;
    }
  }

  function muteTTS() {
    stopTTS();
  }

  function unmuteTTS() {
    setIsMuted(false);
  }

  async function submitFeedback(rating?: -1) {
    if (!session.sessionId || !lastResult) {
      return;
    }
    if (feedbackSubmitted) {
      setNotice("Feedback already recorded for this query.");
      return;
    }
    try {
      await postFeedback(
        { session_id: session.sessionId, turn_id: lastResult.turnId, rating: rating ?? -1 },
        await auth.getToken()
      );
      setFeedbackSubmitted(true);
      setNotice("Feedback recorded for threshold tuning.");
    } catch (error) {
      setNotice(errorMessage(error, "Could not record feedback."));
    }
  }

  return {
    authMode: auth.mode,
    modeLabel,
    isReady,
    session,
    submittedText,
    partialTranscript,
    pipelineInFlight,
    pipelineStage,
    lastResult,
    clarification,
    notice,
    micPermission,
    recordingState,
    audioAnalyserNode,
    isMuted,
    feedbackSubmitted,
    setSubmittedText,
    startRecording,
    stopRecording,
    toggleRecording,
    startFakeVoice,
    submitCurrentQuery,
    submitQuery,
    submitClarification,
    submitFeedback,
    resetConversation,
    muteTTS,
    unmuteTTS
  };
}
