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
  ClarificationState,
  LastResult,
  MicPermission,
  SessionState
} from "../../lib/types";
import {
  mapVoiceToRecordingState,
  notice as createNotice,
  parseAudioEvent,
  parsePipelineEvent,
  transitionVoiceState,
  turnPhaseFromPipelineStage,
  type NoticeSeverity,
  type TtsLifecycleState,
  type TurnLifecycleState,
  type UserNotice,
  type VoiceCaptureState
} from "../state/interactionState";

export type VoxQueryAuthMode = "fake" | "clerk";

export type VoxQueryAuthRelay = {
  mode: VoxQueryAuthMode;
  ready: boolean;
  signedIn: boolean;
  getToken: () => Promise<string | null>;
};

type VoiceDraft = {
  rawTranscript: string;
  sttConfidence: number;
};

/** Exposed so the review panel can display the original raw transcript. */
export type { VoiceDraft };

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
  turnHistory: LastResult[];
  clarification: ClarificationState;
  notice: UserNotice;

  micPermission: MicPermission;
  voiceState: VoiceCaptureState;
  turnState: TurnLifecycleState;
  ttsState: TtsLifecycleState;
  recordingState: ReturnType<typeof mapVoiceToRecordingState>;
  audioAnalyserNode: AnalyserNode | null;
  isMuted: boolean;
  voiceDraft: VoiceDraft | null;

  feedbackSubmitted: boolean;
  feedbackRating: -1 | 1 | null;

  setSubmittedText: (value: string) => void;
  startRecording: () => Promise<void>;
  stopRecording: () => void;
  toggleRecording: () => Promise<void>;
  startFakeVoice: () => Promise<void>;
  submitCurrentQuery: () => Promise<void>;
  submitQuery: (text: string) => Promise<void>;
  submitClarification: (selection: string | null) => Promise<void>;
  submitFeedback: (rating?: -1 | 1) => Promise<void>;
  resetConversation: () => Promise<void>;
  muteTTS: () => void;
  unmuteTTS: () => void;
};

const tenantId =
  process.env.NEXT_PUBLIC_VOXQUERY_TENANT_ID ??
  process.env.NEXT_PUBLIC_FAKE_TENANT_ID ??
  "00000000-0000-0000-0000-000000000101";

function errorMessage(error: unknown, fallback: string) {
  if (error instanceof Error) return error.message;
  return fallback;
}

function normalizeTranscript(value: string) {
  return value.trim().toLowerCase().split(/\s+/).join(" ");
}

type WindowWithWebkitAudio = Window &
  typeof globalThis & {
    webkitAudioContext?: typeof AudioContext;
  };

function createBrowserAudioContext(options?: AudioContextOptions) {
  const audioWindow = window as WindowWithWebkitAudio;
  const AudioContextConstructor = window.AudioContext ?? audioWindow.webkitAudioContext;
  if (!AudioContextConstructor) {
    throw new Error("AudioContext is unavailable.");
  }
  return new AudioContextConstructor(options);
}

export function useVoxQuerySession(auth: VoxQueryAuthRelay): VoxQueryEngine {
  const [session, setSession] = useState<SessionState>({ sessionId: null, conversationId: null });
  const [micPermission, setMicPermission] = useState<MicPermission>("unknown");
  const [voiceState, setVoiceState] = useState<VoiceCaptureState>("idle");
  const [partialTranscript, setPartialTranscript] = useState("");
  const [submittedText, setSubmittedText] = useState("");
  const [pipelineInFlight, setPipelineInFlight] = useState(false);
  const [currentTurnId, setCurrentTurnId] = useState<string | null>(null);
  const [pipelineStage, setPipelineStage] = useState<string | null>(null);
  const [turnState, setTurnState] = useState<TurnLifecycleState>("idle");
  const [feedbackSubmitted, setFeedbackSubmitted] = useState(false);
  const [feedbackRating, setFeedbackRating] = useState<-1 | 1 | null>(null);
  const [clarification, setClarification] = useState<ClarificationState>({
    pending: false,
    question: null,
    options: []
  });
  const [lastResult, setLastResult] = useState<LastResult | null>(null);
  const [turnHistory, setTurnHistory] = useState<LastResult[]>([]);
  const [voiceDraft, setVoiceDraft] = useState<VoiceDraft | null>(null);
  const [notice, setNoticeState] = useState<UserNotice>(
    createNotice(
      auth.mode === "clerk"
        ? "Clerk auth mode active. Requests use the signed-in session token."
        : "Local fake mode active. No external credentials are required."
    )
  );
  const modeLabel = auth.mode === "clerk" ? "clerk auth mode" : "local fake mode";
  const recordingState = useMemo(() => mapVoiceToRecordingState(voiceState), [voiceState]);
  const setNotice = useCallback((message: string, severity: NoticeSeverity = "info") => {
    setNoticeState(createNotice(message, severity));
  }, []);

  const audioSocketRef = useRef<WebSocket | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const audioWorkletRef = useRef<AudioWorkletNode | null>(null);
  const currentTurnIdRef = useRef<string | null>(null);
  const currentTurnRequestRef = useRef<{ submittedText: string; parentTurnId: string | null } | null>(null);
  const [audioAnalyserNode, setAudioAnalyserNode] = useState<AnalyserNode | null>(null);

  const ttsAudioContextRef = useRef<AudioContext | null>(null);
  const ttsSocketRef = useRef<WebSocket | null>(null);
  const activeTtsSourcesRef = useRef<Set<AudioBufferSourceNode>>(new Set());
  const nextPlayTimeRef = useRef<number>(0);
  const [isMuted, setIsMuted] = useState(false);
  const [ttsState, setTtsState] = useState<TtsLifecycleState>("idle");

  const isReady = useMemo(
    () => auth.ready && auth.signedIn && Boolean(session.sessionId),
    [auth.ready, auth.signedIn, session.sessionId]
  );

  function setActiveTurnId(turnId: string | null) {
    currentTurnIdRef.current = turnId;
    setCurrentTurnId(turnId);
  }

  function setActiveTurnRequest(submitted: string, parentTurnId: string | null) {
    currentTurnRequestRef.current = { submittedText: submitted, parentTurnId };
  }

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
    setActiveTurnId(null);
    setPartialTranscript("");
    setSubmittedText("");
    setVoiceDraft(null);
    setVoiceState("idle");
    setTurnState("idle");
    setFeedbackSubmitted(false);
    setFeedbackRating(null);
    setClarification({ pending: false, question: null, options: [] });
    setLastResult(null);
    setTurnHistory([]);
    stopTTS("idle");
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
  }, [auth, session.sessionId, setNotice]);

  useEffect(() => {
    let cancelled = false;
    async function startSession() {
      try {
        await ensureSession();
      } catch {
        if (!cancelled) {
          setNotice("Could not create a local session. Is the backend running?");
        }
      }
    }
    void startSession();
    return () => {
      cancelled = true;
    };
  }, [ensureSession, setNotice]);

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

  const getTokenRef = useRef(auth.getToken);
  useEffect(() => {
    getTokenRef.current = auth.getToken;
  }, [auth.getToken]);

  useEffect(() => {
    if (!session.sessionId || !auth.ready || !auth.signedIn) {
      return;
    }
    let socket: WebSocket | null = null;
    let cancelled = false;
    getTokenRef.current()
      .then((token) => {
        if (cancelled || !session.sessionId) {
          return;
        }
        socket = new WebSocket(pipelineSocketUrl(session.sessionId, token));
        socket.onmessage = (message) => {
          const event = parsePipelineEvent(message.data);
          if (!event) {
            return;
          }
          if (event.type === "pipeline_progress") {
            if (currentTurnIdRef.current && event.turn_id !== currentTurnIdRef.current) {
              return;
            }
            setPipelineStage(event.stage);
            setTurnState(turnPhaseFromPipelineStage(event.stage));
            return;
          }
          if (event.type === "clarification_request") {
            if (currentTurnIdRef.current && event.turn_id !== currentTurnIdRef.current) {
              return;
            }
            setActiveTurnId(event.turn_id);
            setClarification({
              pending: true,
              question: event.question,
              options: event.options
            });
            setPipelineInFlight(false);
            setPipelineStage("clarification_pending");
            setTurnState("clarification_required");
            setNotice("Clarification required before executing the query.", "warning");
            return;
          }
          if (event.type === "result_ready") {
            if (event.turn_id !== currentTurnIdRef.current) {
              return;
            }
            setPipelineInFlight(false);
            setTurnState("preparing_answer");
            void loadResult(event.turn_id).catch((error) =>
              setNotice(errorMessage(error, "Result is ready, but could not be loaded."), "error")
            );
            return;
          }
          if (event.type === "pipeline_error") {
            if (event.turn_id !== currentTurnIdRef.current) {
              return;
            }
            setClarification({ pending: false, question: null, options: [] });
            setPipelineInFlight(false);
            setPipelineStage(null);
            setTurnState(event.code === "clarification_timeout" ? "recoverable_error" : "fatal_error");
            setNotice(event.message, "error");
          }
        };
        socket.onerror = () => setNotice("Pipeline event stream unavailable. Check that the backend is running.", "error");
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
  }, [auth.ready, auth.signedIn, session.sessionId, setNotice]);



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
      setVoiceState("capture_error");
      setNotice("Microphone is unavailable in this context. Use text input or Fake voice.", "error");
      return;
    }
    if (micPermission === "denied") {
      setVoiceState("permission_explaining");
      setNotice("Microphone access denied. Allow access in browser settings or use text input.", "error");
      return;
    }
    if (!session.sessionId) {
      setVoiceState("capture_error");
      setNotice("Session is not ready. Cannot start recording.", "error");
      return;
    }

    try {
      setVoiceDraft(null);
      stopTTS("idle");
      ensureTTSContext();
      setVoiceState((state) => transitionVoiceState(state, "request_permission"));
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      setMicPermission("granted");

      const token = await auth.getToken();
      await postTelemetry({ event: "stt.mic.permission", outcome: "granted", session_id: session.sessionId }, token).catch(console.error);

      setVoiceState((state) => transitionVoiceState(state, "permission_granted"));
      setNotice("Microphone access granted. Connecting...");

      const socket = new WebSocket(audioSocketUrl(session.sessionId, token));
      audioSocketRef.current = socket;
      mediaStreamRef.current = stream;

      socket.onopen = async () => {
        try {
          const audioContext = createBrowserAudioContext();
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

          setVoiceState((state) => transitionVoiceState(state, "connected"));
          setNotice("Recording...");
        } catch (error) {
          console.error("Audio processor initialization error:", error);
          setVoiceState("capture_error");
          setNotice("Failed to initialize audio processing.", "error");
          recorderCleanup();
        }
      };

      socket.onmessage = (message) => {
        const event = parseAudioEvent(message.data);
        if (!event) return;

        if (event.type === "interim_transcript") {
          setPartialTranscript(event.text);
        } else if (event.type === "final_transcript") {
          setPartialTranscript(event.text);
          setSubmittedText(event.text);
          setVoiceDraft({ rawTranscript: event.text, sttConfidence: event.confidence });
          setVoiceState((state) => transitionVoiceState(state, "transcript_ready"));
          setNotice("Transcript received. Review or edit before submitting.");
          recorderCleanup();
        } else if (event.type === "error") {
          setVoiceState("capture_error");
          setNotice(event.message, "error");
          recorderCleanup();
        }
      };

      socket.onerror = () => {
        setVoiceState("capture_error");
        setNotice("Audio WebSocket unavailable or error occurred.", "error");
        recorderCleanup();
      };

      socket.onclose = () => {
        setVoiceState((state) =>
          state === "listening" || state === "stopping" || state === "finalizing" ? "idle" : state
        );
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
        setVoiceState("capture_error");
        setNotice("Microphone access denied. Allow access in browser settings or use text input.", "error");
      } else {
        setVoiceState("capture_error");
        setNotice("Could not access microphone. Try again or use text input.", "error");
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
    setVoiceState((state) => transitionVoiceState(state, "stop_requested"));
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
    stopTTS("idle");
    setVoiceDraft(null);
    setVoiceState("connecting");
    setNotice("Connecting to local fake STT WebSocket.");
    const socket = new WebSocket(audioSocketUrl(session.sessionId, await auth.getToken()));
    socket.onopen = () => {
      setVoiceState("listening");
      socket.send(new Uint8Array([1, 2, 3]));
      setVoiceState("finalizing");
      socket.send(JSON.stringify({ type: "stop_recording" }));
    };
    socket.onmessage = (message) => {
      const event = parseAudioEvent(message.data);
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
        setVoiceDraft({ rawTranscript: event.text, sttConfidence: event.confidence });
        setVoiceState("reviewing");
        setNotice("Fake voice transcript received. Review or edit before submitting.");
        socket.close();
        return;
      }
      if (event.type === "error") {
        setVoiceState("capture_error");
        setNotice(event.message, "error");
      }
    };
    socket.onerror = () => {
      setVoiceState("capture_error");
      setNotice("Fake voice WebSocket unavailable. Check that the backend is running.", "error");
    };
    socket.onclose = () => setVoiceState((state) => (state === "finalizing" ? "idle" : state));
  }

  async function submitQuery(text: string) {
    if (pipelineInFlight) {
      setNotice("A query is already running. Please wait for it to complete.", "warning");
      return;
    }
    if (!session.sessionId || !text.trim()) {
      setNotice("Please enter a question before submitting.", "warning");
      return;
    }

    const submitted = text.trim();
    const parentTurnId = lastResult?.turnId ?? null;
    const activeVoiceDraft = voiceDraft;
    const transcriptEdited = activeVoiceDraft
      ? normalizeTranscript(submitted) !== normalizeTranscript(activeVoiceDraft.rawTranscript)
      : false;
    setSubmittedText(submitted);

    setPipelineInFlight(true);
    setPipelineStage("sql_generation");
    setTurnState("submitting");
    setLastResult(null);
    setFeedbackSubmitted(false);
    setFeedbackRating(null);
    setVoiceState("idle");
    setClarification({ pending: false, question: null, options: [] });
    try {
      stopTTS("idle", false);
      ensureTTSContext();
      const accepted = await submitQueryApi(
        {
          session_id: session.sessionId,
          parent_turn_id: parentTurnId,
          submitted_text: submitted,
          input_modality: activeVoiceDraft ? "voice" : "text",
          raw_transcript: activeVoiceDraft?.rawTranscript ?? null,
          stt_confidence: activeVoiceDraft?.sttConfidence ?? null,
          transcript_edited: transcriptEdited
        },
        await auth.getToken()
      );
      setActiveTurnId(accepted.turn_id);
      setActiveTurnRequest(submitted, parentTurnId);
      setVoiceDraft(null);
      setFeedbackSubmitted(false);
      setFeedbackRating(null);
      setTurnState("accepted");
      setNotice("Query submitted. Waiting for pipeline events.");
    } catch (error) {
      setPipelineInFlight(false);
      setTurnState("recoverable_error");
      setNotice(errorMessage(error, "Query failed. Check that the backend is running."), "error");
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
        setClarification({ pending: false, question: null, options: [] });
        setPipelineStage(null);
        setActiveTurnId(null);
        setTurnState("idle");
        setNotice("Clarification escaped. Edit your question and submit again.");
      } catch (error) {
        setTurnState("recoverable_error");
        setNotice(errorMessage(error, "Could not escape clarification. Try submitting again."), "error");
      }
      return;
    }

    setPipelineInFlight(true);
    setPipelineStage("snowflake_executing");
    setTurnState("clarification_submitting");
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
      setClarification({ pending: false, question: null, options: [] });
      setTurnState("executing");
      setNotice("Clarification submitted. Waiting for pipeline result.");
    } catch (error) {
      setPipelineInFlight(false);
      setTurnState("recoverable_error");
      setNotice(errorMessage(error, "Could not resolve clarification. Try submitting again."), "error");
    }
  }

  async function loadResult(turnId: string) {
    setPipelineStage("rendering");
    setTurnState("preparing_answer");
    const result = await fetchResult(turnId, await auth.getToken());
    if (turnId !== currentTurnIdRef.current || result.turn_id !== turnId) {
      return;
    }
    const request = currentTurnRequestRef.current;
    const completedResult: LastResult = {
      turnId,
      submittedText: request?.submittedText ?? submittedText,
      parentTurnId: request?.parentTurnId ?? null,
      confidenceTier: result.confidence_tier,
      chartType: result.chart_type,
      chartRationale: result.chart_rationale,
      resultData: result,
      proactiveQuestions: result.proactive_questions
    };
    setLastResult(completedResult);
    setTurnHistory((history) => [
      ...history.filter((item) => item.turnId !== turnId),
      completedResult
    ].slice(-6));
    setPipelineInFlight(false);
    setPipelineStage(null);
    setTurnState("completed");
    setClarification({ pending: false, question: null, options: [] });
    setNotice("Result ready.");

    const token = await auth.getToken();
    playTTS(turnId, token);
  }

  function ensureTTSContext() {
    if (!ttsAudioContextRef.current || ttsAudioContextRef.current.state === "closed") {
      ttsAudioContextRef.current = createBrowserAudioContext({ sampleRate: 16000 });
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
    setTtsState("loading");

    try {
      const audioCtx = ensureTTSContext();
      nextPlayTimeRef.current = audioCtx.currentTime + 0.1;

      const socket = new WebSocket(ttsSocketUrl(session.sessionId, turnId, token));
      socket.binaryType = "arraybuffer";
      ttsSocketRef.current = socket;

      socket.onmessage = (event) => {
        if (ttsAudioContextRef.current?.state === "closed") return;
        
        if (!(event.data instanceof ArrayBuffer)) {
          return;
        }

        const buffer = event.data as ArrayBuffer;
        const safeBuffer = buffer.byteLength % 2 !== 0 ? buffer.slice(0, buffer.byteLength - 1) : buffer;
        const int16Array = new Int16Array(safeBuffer);
        
        if (int16Array.length === 0) return;

        setTtsState("playing");
        const float32Array = new Float32Array(int16Array.length);
        for (let i = 0; i < int16Array.length; i++) {
          float32Array[i] = int16Array[i] / 32768.0;
        }

        try {
          const audioBuffer = audioCtx.createBuffer(1, float32Array.length, 16000);
          audioBuffer.getChannelData(0).set(float32Array);

          const source = audioCtx.createBufferSource();
          source.buffer = audioBuffer;
          source.connect(audioCtx.destination);
        
          activeTtsSourcesRef.current.add(source);
          source.onended = () => {
            activeTtsSourcesRef.current.delete(source);
          };

          const startTime = Math.max(nextPlayTimeRef.current, audioCtx.currentTime);
          source.start(startTime);
          nextPlayTimeRef.current = startTime + audioBuffer.duration;
        } catch (err) {
          console.error("Audio buffer error:", err);
        }
      };
      socket.onerror = () => {
        setTtsState("failed");
        setNotice("Voice playback failed. The text answer is still available.", "warning");
      };
      socket.onclose = () => {
        if (ttsSocketRef.current === socket) {
          ttsSocketRef.current = null;
        }
        setTtsState((state) => (state === "loading" || state === "playing" ? "ended" : state));
      };
    } catch (e) {
      console.error("TTS playback failed to initialize", e);
      setTtsState("failed");
      setNotice("Voice playback failed to initialize. The text answer is still available.", "warning");
    }
  }

  function stopTTS(nextState: TtsLifecycleState = "ended", shouldMute = true) {
    if (shouldMute) {
      setIsMuted(true);
    }
    if (ttsSocketRef.current) {
      ttsSocketRef.current.close();
      ttsSocketRef.current = null;
    }
    activeTtsSourcesRef.current.forEach((source) => {
      try {
        source.stop();
      } catch (e) {
        // ignore if already stopped
      }
    });
    activeTtsSourcesRef.current.clear();
    nextPlayTimeRef.current = 0;
    setTtsState(nextState);
  }

  function muteTTS() {
    stopTTS();
  }

  function unmuteTTS() {
    setIsMuted(false);
  }

  async function submitFeedback(rating?: -1 | 1) {
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
      setFeedbackRating(rating ?? -1);
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
    turnHistory,
    clarification,
    notice,
    micPermission,
    voiceState,
    turnState,
    ttsState,
    recordingState,
    audioAnalyserNode,
    isMuted,
    voiceDraft,
    feedbackSubmitted,
    feedbackRating,
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
