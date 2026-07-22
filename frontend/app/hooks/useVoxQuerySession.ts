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
import { PcmChunkReassembler } from "../../lib/audio/pcmReassembler";

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
  isPaused: boolean;
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
  pauseTTS: () => void;
  resumeTTS: () => void;
};

const tenantId =
  process.env.NEXT_PUBLIC_VOXQUERY_TENANT_ID ??
  process.env.NEXT_PUBLIC_FAKE_TENANT_ID ??
  "";

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
  const audioStopAfterFlushRef = useRef(false);
  const pendingAudioFramesRef = useRef<ArrayBuffer[]>([]);
  const currentTurnIdRef = useRef<string | null>(null);
  const currentTurnRequestRef = useRef<{ submittedText: string; parentTurnId: string | null } | null>(null);
  const [audioAnalyserNode, setAudioAnalyserNode] = useState<AnalyserNode | null>(null);

  const ttsAudioContextRef = useRef<AudioContext | null>(null);
  const ttsSocketRef = useRef<WebSocket | null>(null);
  const activeTtsSourcesRef = useRef<Set<AudioBufferSourceNode>>(new Set());
  const nextPlayTimeRef = useRef<number>(0);
  const ttsGainNodeRef = useRef<GainNode | null>(null);
  const ttsReassemblerRef = useRef<PcmChunkReassembler>(new PcmChunkReassembler());
  const [isMuted, setIsMuted] = useState(false);
  const [isPaused, setIsPaused] = useState(false);
  const [ttsState, setTtsState] = useState<TtsLifecycleState>("idle");

  /** Ramp duration for mute/unmute/stop fades, matched to avoid audible clicks
   * from an instantaneous gain or amplitude discontinuity. */
  const GAIN_RAMP_SECONDS = 0.03;

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
      } catch (error) {
        if (!cancelled) {
          setNotice(errorMessage(error, "Could not create a local session. Is the backend running?"), "error");
        }
      }
    }
    void startSession();
    return () => {
      cancelled = true;
    };
  }, [ensureSession, setNotice]);

  // The recording AudioContext is deliberately kept alive (suspended, not
  // closed) across individual recordings for reuse — see recorderCleanup.
  // Only fully release it when the hook itself unmounts.
  useEffect(() => {
    return () => {
      closeRecordingAudioContext();
    };
  }, []);

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
        socket = new WebSocket(pipelineSocketUrl(session.sessionId));
        socket.onopen = () => {
          socket?.send(JSON.stringify({ event: "auth", token: token ?? "fake" }));
        };
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
        socket.onerror = () => setNotice("Could not connect to the real-time event stream. Please check your network connection.", "error");
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
    audioStopAfterFlushRef.current = false;
    pendingAudioFramesRef.current = [];
    if (audioWorkletRef.current) {
      if (audioWorkletRef.current && audioWorkletRef.current.disconnect) { try { audioWorkletRef.current.disconnect(); } catch (e) { } }
      audioWorkletRef.current = null;
    }
    setAudioAnalyserNode(null);
    if (mediaStreamRef.current) {
      mediaStreamRef.current.getTracks().forEach((track) => track.stop());
      mediaStreamRef.current = null;
    }
    // Suspend rather than close: the context (and its already-loaded worklet
    // module) is reused on the next recording instead of being torn down and
    // reconstructed from scratch, which previously added avoidable latency
    // and overhead to every single mic click.
    if (audioContextRef.current && audioContextRef.current.state === "running") {
      audioContextRef.current.suspend().catch(console.error);
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

  /** Fully tears down the recording AudioContext — only used on unmount, not
   * between individual recordings (see recorderCleanup, which suspends and
   * reuses it instead). */
  function closeRecordingAudioContext() {
    if (audioContextRef.current && audioContextRef.current.state !== "closed") {
      audioContextRef.current.close().catch(console.error);
    }
    audioContextRef.current = null;
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
      setPartialTranscript("");
      stopTTS("idle");
      setVoiceState((state) => transitionVoiceState(state, "request_permission"));

      // Open the backend audio WebSocket immediately, in parallel with the mic
      // permission prompt and token fetch, rather than waiting for both to
      // resolve first. The backend begins connecting to Deepgram as soon as it
      // accepts+authenticates this socket, so this removes a full WS-handshake
      // round-trip (browser<->backend) from the critical path before the user
      // can start being transcribed, without pre-opening anything before the
      // click (which would risk the backend's idle-timeout on a connection
      // opened too far ahead of actual speech).
      const tokenPromise = auth.getToken();
      const socket = new WebSocket(audioSocketUrl(session.sessionId));
      audioSocketRef.current = socket;
      pendingAudioFramesRef.current = [];

      const flushQueuedAudio = () => {
        if (socket.readyState !== WebSocket.OPEN) return;
        for (const frame of pendingAudioFramesRef.current) {
          socket.send(frame);
        }
        pendingAudioFramesRef.current = [];
      };

      const markRecording = () => {
        setVoiceState((state) => transitionVoiceState(state, "connected"));
        setNotice("Recording...");
      };

      socket.onopen = () => {
        tokenPromise
          .then((token) => {
            socket.send(JSON.stringify({ event: "auth", token: token ?? "fake" }));
            flushQueuedAudio();
            if (audioWorkletRef.current) {
              markRecording();
            }
          })
          .catch(console.error);
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

      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          autoGainControl: true,
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true
        }
      });
      mediaStreamRef.current = stream;
      setMicPermission("granted");

      const token = await tokenPromise;
      postTelemetry({ event: "stt.mic.permission", outcome: "granted", session_id: session.sessionId }, token).catch(console.error);

      setVoiceState((state) => transitionVoiceState(state, "permission_granted"));
      setNotice("Microphone access granted. Connecting...");

      try {
        // Reuse a single AudioContext across recordings instead of creating and
        // tearing one down on every click — avoids the setup/teardown latency
        // and overhead of repeated AudioContext construction.
        let audioContext = audioContextRef.current;
        if (!audioContext || audioContext.state === "closed") {
          // Request 16kHz directly: on browsers that honor it, the browser's
          // native (anti-aliased) resampler does this work instead of the
          // worklet's manual linear-interpolation downsample loop — the
          // worklet already guards this correctly (downsample() short-circuits
          // when inputRate === outputRate, and reads the real negotiated rate
          // live via AudioWorkletGlobalScope.sampleRate), so browsers that
          // don't honor the request (some older Safari/WebKit builds) safely
          // fall back to the existing manual downsample instead of silently
          // sending audio at the wrong implied rate.
          audioContext = createBrowserAudioContext({ sampleRate: 16000 });
          audioContextRef.current = audioContext;
          await audioContext.audioWorklet.addModule("/audio-processor.js");
        } else if (audioContext.state === "suspended") {
          await audioContext.resume();
        }

        const source = audioContext.createMediaStreamSource(stream);
        const analyser = audioContext.createAnalyser();
        analyser.fftSize = 256;
        setAudioAnalyserNode(analyser);

        const worklet = new AudioWorkletNode(audioContext, "pcm-audio-processor");
        audioWorkletRef.current = worklet;

        worklet.port.onmessage = (e) => {
          if (e.data && typeof e.data === "object" && "type" in e.data && e.data.type === "flushed") {
            if (audioStopAfterFlushRef.current && socket.readyState === WebSocket.OPEN) {
              audioStopAfterFlushRef.current = false;
              flushQueuedAudio();
              socket.send(JSON.stringify({ type: "stop_recording" }));
            }
            return;
          }

          if (!(e.data instanceof ArrayBuffer)) {
            return;
          }

          if (socket.readyState === WebSocket.OPEN) {
            socket.send(e.data);
            return;
          }

          if (socket.readyState === WebSocket.CONNECTING && pendingAudioFramesRef.current.length < 250) {
            pendingAudioFramesRef.current.push(e.data);
          }
        };

        source.connect(analyser);
        analyser.connect(worklet);

        const zeroGain = audioContext.createGain();
        zeroGain.gain.value = 0;
        worklet.connect(zeroGain);
        zeroGain.connect(audioContext.destination);

        flushQueuedAudio();
        markRecording();
      } catch (error) {
        console.error("Audio processor initialization error:", error);
        setVoiceState("capture_error");
        setNotice("Failed to initialize audio processing.", "error");
        recorderCleanup();
      }
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
        recorderCleanup();
        setVoiceState("capture_error");
        setNotice("Could not access microphone. Try again or use text input.", "error");
      }
    }
  }

  function stopRecording() {
    if (mediaStreamRef.current) {
      mediaStreamRef.current.getTracks().forEach((track) => track.stop());
    }
    if (audioSocketRef.current && audioSocketRef.current.readyState === WebSocket.OPEN) {
      if (audioWorkletRef.current) {
        audioStopAfterFlushRef.current = true;
        audioWorkletRef.current.port.postMessage({ type: "flush" });
        window.setTimeout(() => {
          if (audioStopAfterFlushRef.current && audioSocketRef.current?.readyState === WebSocket.OPEN) {
            audioStopAfterFlushRef.current = false;
            audioSocketRef.current.send(JSON.stringify({ type: "stop_recording" }));
          }
        }, 80);
      } else {
        audioSocketRef.current.send(JSON.stringify({ type: "stop_recording" }));
      }
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
    const token = await auth.getToken();
    const socket = new WebSocket(audioSocketUrl(session.sessionId));
    socket.onopen = () => {
      socket.send(JSON.stringify({ event: "auth", token: token ?? "fake" }));
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
      setNotice("Could not connect to the fake voice service. Please check your network connection.", "error");
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
      setNotice(errorMessage(error, "Failed to submit query. Please check your network connection and try again."), "error");
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
      const ctx = createBrowserAudioContext({ sampleRate: 16000 });
      ttsAudioContextRef.current = ctx;
      const gain = ctx.createGain();
      gain.gain.value = isMuted ? 0 : 1;
      gain.connect(ctx.destination);
      ttsGainNodeRef.current = gain;
    }
    if (ttsAudioContextRef.current.state === "suspended" && !isPaused) {
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
    ttsReassemblerRef.current.reset();
    setIsPaused(false);
    setTtsState("loading");

    try {
      const audioCtx = ensureTTSContext();
      const gainNode = ttsGainNodeRef.current;
      nextPlayTimeRef.current = audioCtx.currentTime + 0.1;

      const socket = new WebSocket(ttsSocketUrl(session.sessionId, turnId));
      socket.binaryType = "arraybuffer";
      ttsSocketRef.current = socket;
      socket.onopen = () => {
        socket.send(JSON.stringify({ event: "auth", token: token ?? "fake" }));
      };

      socket.onmessage = (event) => {
        if (event.data && typeof event.data === "string") return;
        if (ttsAudioContextRef.current?.state === "closed") return;

        if (!(event.data instanceof ArrayBuffer)) {
          return;
        }

        // Reassemble across chunk boundaries instead of truncating a trailing
        // odd byte, which previously corrupted samples split across two
        // WebSocket messages and produced audible clicks/static.
        const int16Array = ttsReassemblerRef.current.push(event.data as ArrayBuffer);
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
          source.connect(gainNode ?? audioCtx.destination);

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

  function stopTTS(nextState: TtsLifecycleState = "ended", shouldMute = false) {
    const audioCtx = ttsAudioContextRef.current;
    const gainNode = ttsGainNodeRef.current;

    if (shouldMute) {
      setIsMuted(true);
    }
    setIsPaused(false);

    if (ttsSocketRef.current) {
      ttsSocketRef.current.close();
      ttsSocketRef.current = null;
    }

    if (audioCtx && gainNode && activeTtsSourcesRef.current.size > 0) {
      // Fade out over GAIN_RAMP_SECONDS before cutting playback, instead of an
      // instantaneous stop, which truncates the waveform at an arbitrary,
      // non-zero amplitude and produces an audible click.
      const now = audioCtx.currentTime;
      gainNode.gain.cancelScheduledValues(now);
      gainNode.gain.setValueAtTime(gainNode.gain.value, now);
      gainNode.gain.linearRampToValueAtTime(0, now + GAIN_RAMP_SECONDS);

      const sourcesToStop = Array.from(activeTtsSourcesRef.current);
      window.setTimeout(() => {
        sourcesToStop.forEach((source) => {
          try {
            source.stop();
          } catch (e) {
            // ignore if already stopped
          }
        });
        activeTtsSourcesRef.current.clear();
        // Restore gain for the next playback, honoring current mute state.
        if (ttsGainNodeRef.current && ttsAudioContextRef.current) {
          const restoreCtx = ttsAudioContextRef.current;
          ttsGainNodeRef.current.gain.setValueAtTime(isMuted ? 0 : 1, restoreCtx.currentTime);
        }
      }, GAIN_RAMP_SECONDS * 1000 + 10);
    } else {
      activeTtsSourcesRef.current.forEach((source) => {
        try {
          source.stop();
        } catch (e) {
          // ignore if already stopped
        }
      });
      activeTtsSourcesRef.current.clear();
    }

    ttsReassemblerRef.current.reset();
    nextPlayTimeRef.current = 0;
    setTtsState(nextState);
  }

  /** True mute: ramps playback volume to 0 without stopping generation or
   * losing playback position. Audio keeps arriving and queuing in the
   * background — unmuteTTS() ramps volume back up seamlessly. */
  function muteTTS() {
    setIsMuted(true);
    const audioCtx = ttsAudioContextRef.current;
    const gainNode = ttsGainNodeRef.current;
    if (audioCtx && gainNode) {
      const now = audioCtx.currentTime;
      gainNode.gain.cancelScheduledValues(now);
      gainNode.gain.setValueAtTime(gainNode.gain.value, now);
      gainNode.gain.linearRampToValueAtTime(0, now + GAIN_RAMP_SECONDS);
    }
  }

  /** Ramps playback volume back up. If nothing is currently playing, this
   * just clears the muted flag so the next turn starts audible. */
  function unmuteTTS() {
    setIsMuted(false);
    const audioCtx = ttsAudioContextRef.current;
    const gainNode = ttsGainNodeRef.current;
    if (audioCtx && gainNode) {
      const now = audioCtx.currentTime;
      gainNode.gain.cancelScheduledValues(now);
      gainNode.gain.setValueAtTime(gainNode.gain.value, now);
      gainNode.gain.linearRampToValueAtTime(1, now + GAIN_RAMP_SECONDS);
    }
  }

  /** Genuine pause: suspends the AudioContext clock itself, so all scheduled
   * buffer sources freeze in place rather than being destroyed. resumeTTS()
   * continues from exactly where playback left off. */
  function pauseTTS() {
    const audioCtx = ttsAudioContextRef.current;
    if (!audioCtx || audioCtx.state !== "running") return;
    audioCtx.suspend().catch(console.error);
    setIsPaused(true);
    setTtsState("paused");
  }

  function resumeTTS() {
    const audioCtx = ttsAudioContextRef.current;
    if (!audioCtx || audioCtx.state !== "suspended") return;
    audioCtx.resume().catch(console.error);
    setIsPaused(false);
    setTtsState((state) => (state === "paused" ? "playing" : state));
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
    isPaused,
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
    unmuteTTS,
    pauseTTS,
    resumeTTS
  };
}

