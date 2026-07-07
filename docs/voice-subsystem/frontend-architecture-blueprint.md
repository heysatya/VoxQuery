# VoxQuery Frontend Architecture Blueprint

## Purpose

This blueprint defines the target frontend architecture for the VoxQuery voice-first UI redesign.

The current MVP frontend concentrates auth handling, session lifecycle, WebSocket logic, Web Audio logic, TTS playback, pipeline state, clarification state, feedback handling, text input, fake voice, and result rendering inside `frontend/app/page.tsx`.

The refactor must split that monolith into:

1. A headless engine hook that owns behavior and backend interaction.
2. Pure presentation components that render state and emit user intent.
3. A lightweight page shell that handles auth gating and animated layout composition.

The redesign must feel like a ground-up voice-first interface, but it must not discard working MVP capabilities.

## Current Repo Reality

The existing frontend already includes important behavior that must survive:

- Fake/local auth mode.
- Clerk auth mode.
- Session creation and session reuse through `voxquery_session_id`.
- Pipeline WebSocket.
- Audio WebSocket.
- TTS WebSocket.
- AudioWorklet PCM microphone streaming.
- Fake voice test path.
- Editable text fallback.
- Clarification requests and timeout warnings.
- Result fetching and result rendering.
- Feedback submission.
- Mic permission telemetry.
- Regression tests in `frontend/app/page.test.tsx`.

The redesign is not allowed to treat these as disposable MVP details. They are part of the product contract unless explicitly replaced by equivalent behavior.

## Target Directory Structure

```text
frontend/
├── app/
│   ├── page.tsx
│   ├── hooks/
│   │   └── useVoxQuerySession.ts
│   └── components/
│       ├── hero/
│       │   └── VoiceVisualizer.tsx
│       ├── data/
│       │   └── DataGlassPanel.tsx
│       ├── clarification/
│       │   └── ClarificationOverlay.tsx
│       ├── query/
│       │   └── QueryDock.tsx
│       └── ui/
│           └── local shadcn/ui-style primitives
├── lib/
│   ├── api.ts
│   ├── types.ts
│   └── utils.ts
```

`page.tsx` must become a composition shell. It may handle auth gating and layout state, but it must not contain backend calls, WebSocket setup, Web Audio setup, session lifecycle code, or backend payload construction.

## UI Foundation

The frontend must use:

- TailwindCSS for styling.
- Framer Motion for animation and spatial layout transitions.
- shadcn/ui-style local primitives for common controls.
- Lucide icons where icons improve clarity.

If missing, add:

- Tailwind config.
- PostCSS config.
- Tailwind directives in the global stylesheet.
- `components.json` if using the shadcn CLI.
- A `cn` utility, typically backed by `clsx` and `tailwind-merge`.
- Minimal local primitives under `frontend/app/components/ui`.

Do not install a runtime package named `shadcn`.

## Headless Engine Hook

Create:

```text
frontend/app/hooks/useVoxQuerySession.ts
```

The hook owns all stateful behavior and all backend interaction.

It must export:

```ts
import type {
  ClarificationState,
  LastResult,
  MicPermission,
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

export function useVoxQuerySession(auth: VoxQueryAuthRelay): VoxQueryEngine;
```

## Required Engine Behavior

The hook must preserve these behaviors:

- Create a session through the existing session API.
- Resume a stored session from `window.sessionStorage.getItem("voxquery_session_id")`.
- Store only `voxquery_session_id`, not `conversation_id`.
- Open the pipeline WebSocket when auth and session are ready.
- On pipeline close code `4002`, clear the stored session and create a new one.
- Probe microphone permission when supported.
- Send existing mic permission telemetry on grant or denial.
- Use the existing AudioWorklet path for PCM streaming.
- Send binary PCM frames over the audio WebSocket.
- Send `{ type: "stop_recording" }` when recording stops.
- Keep the audio WebSocket open long enough to receive the final transcript.
- Set both `partialTranscript` and `submittedText` from the final transcript.
- Preserve fake voice through the existing audio WebSocket path.
- Submit text queries through the existing query API.
- Handle pipeline progress events.
- Handle clarification request events.
- Handle clarification timeout warning events.
- Handle result-ready events by fetching the result through the existing result API.
- Start TTS playback after result load using the existing TTS WebSocket.
- Close TTS playback resources when muted.
- Submit clarification choices through the existing clarification API.
- Submit feedback through the existing feedback API using `rating: -1`.
- Prevent duplicate feedback submission from the UI.

## Audio Visualizer Contract

The hook must expose a live `AnalyserNode` during real microphone recording.

The analyser must not break PCM streaming.

A valid audio graph is:

```text
MediaStreamAudioSourceNode
├── AnalyserNode
└── AudioWorkletNode
    └── zero-gain GainNode
        └── audioContext.destination
```

Cleanup must:

- Stop media tracks.
- Disconnect the AudioWorklet.
- Close or suspend the AudioContext as appropriate.
- Close the audio WebSocket when appropriate.
- Clear `audioAnalyserNode`.

## Presentation Components

Presentation components must receive props and callbacks only.

They must not import `frontend/lib/api.ts`.
They must not create sessions.
They must not open WebSockets.
They must not create AudioContexts.
They must not construct backend payloads.

### VoiceVisualizer

Purpose: primary hero voice orb.

Props:

```ts
type VoiceVisualizerProps = {
  state: RecordingState;
  analyser: AnalyserNode | null;
  disabled: boolean;
  pipelineStage: string | null;
  partialTranscript: string;
  onPrimaryAction: () => void | Promise<void>;
  onStop: () => void;
};
```

Requirements:

- Render as the visual and interaction center of the app.
- Display idle, connecting, recording, and processing states.
- Use the provided analyser for live visualization when available.
- In recording state, the primary action should stop recording.
- Otherwise, the primary action should start recording.
- Never own backend or browser audio lifecycle.

### DataGlassPanel

Purpose: result display and result-level actions.

Props:

```ts
type DataGlassPanelProps = {
  result: LastResult;
  feedbackSubmitted: boolean;
  isMuted: boolean;
  onFeedback: () => void | Promise<void>;
  onMute: () => void;
  onUnmute: () => void;
};
```

Requirements:

- Render confidence tier.
- Render chart rationale.
- Render result rows and columns reliably.
- Render generated SQL behind a disclosure.
- Render feedback control.
- Render compact TTS mute/unmute control.
- If no chart library exists, table rendering is sufficient and preferred over inventing new chart behavior.

### ClarificationOverlay

Purpose: interruptive clarification state.

Props:

```ts
type ClarificationOverlayProps = {
  clarification: ClarificationState;
  onResolve: (selection: string | null) => void | Promise<void>;
};
```

Requirements:

- Render question.
- Render options.
- Render countdown.
- Render escape/rephrase action.
- Escape action must call `onResolve(null)`.

### QueryDock

Purpose: secondary reliability controls.

Props:

```ts
type QueryDockProps = {
  value: string;
  disabled: boolean;
  isReady: boolean;
  recordingState: RecordingState;
  notice: string;
  modeLabel: string;
  onChange: (value: string) => void;
  onSubmit: () => void | Promise<void>;
  onFakeVoice: () => void | Promise<void>;
  onResetConversation: () => void | Promise<void>;
};
```

Requirements:

- Provide editable text fallback.
- Provide fake voice.
- Provide reset/new conversation.
- Show current notice.
- Show compact readiness and auth-mode state.
- Stay visually secondary to the orb.

## Page Composition

`frontend/app/page.tsx` must preserve the auth split:

- In fake mode, pass a fake auth relay with token `"fake"`.
- In Clerk mode, use `useAuth`.
- If Clerk is loading, show an auth-loading state.
- If Clerk is signed out, show sign-in UI.
- If auth is ready and signed in, render the voice-first app shell.

The voice-first shell must use Framer Motion for these states:

- Idle: orb centered, QueryDock secondary.
- Recording: orb active, transcript visible near orb.
- Processing: orb remains central with pipeline stage visible.
- Clarification: overlay appears above the main layout.
- Result ready: orb shifts left and DataGlassPanel slides in from the right.
- Reset: result, clarification, transcript, feedback, and pipeline state clear.

The layout must include mobile fallbacks. Do not rely only on `50vw` desktop panels.

## Backend Compatibility

Do not change the behavior of:

- `/api/session`
- `/api/query`
- `/api/clarification`
- `/api/result/{turnId}`
- `/api/feedback`
- `/api/telemetry`
- `/ws/pipeline`
- `/ws/audio`
- `/ws/tts`

Do not change existing request or response shapes.

In particular:

- Feedback remains `rating: -1`.
- Session storage key remains `voxquery_session_id`.
- Stop recording message remains `{ type: "stop_recording" }`.
- Fake token remains `"fake"` in fake mode.

## Test Requirements

The refactor must update or add tests covering equivalent behavior.

Required coverage:

- Session creation stores only `voxquery_session_id`.
- Stored session resumes without creating a replacement session.
- Pipeline WebSocket opens with session and token.
- Pipeline close code `4002` creates a new session.
- Text fallback remains editable.
- Fake voice fills the editable transcript.
- Mic unavailable keeps text input usable.
- Mic denied records telemetry and returns to idle.
- Mic granted records telemetry and starts recording flow.
- AudioWorklet starts when permission is granted.
- Binary PCM frames are sent over the audio WebSocket.
- Stop recording sends `{ type: "stop_recording" }`.
- Final transcript updates both partial transcript and editable submitted text.
- Clarification renders question, options, countdown, and escape action.
- Clarification escape submits `null`.
- Result-ready event fetches and renders result data.
- TTS WebSocket opens after result load.
- Mute closes TTS playback resources.
- Feedback submits once and duplicate feedback is reflected in UI state.
- `audioAnalyserNode` exists during real recording and clears on cleanup.

Required verification commands:

```bash
npm test
npm run build
```

Run `npm run lint` if valid for the installed Next.js version.

## Acceptance Criteria

The refactor is complete only when:

- `page.tsx` is no longer a monolithic behavior container.
- `useVoxQuerySession` owns backend, session, WebSocket, audio, TTS, telemetry, clarification, and feedback behavior.
- Presentation components are pure and backend-agnostic.
- The UI is genuinely voice-first.
- Text and fake voice remain available as secondary fallback controls.
- Fake auth and Clerk auth both still work.
- Existing backend contracts are unchanged.
- Tests and build pass, or any non-passing command is documented with a concrete reason.

## Locked Decisions

- Text fallback and fake voice stay available in a secondary `QueryDock`.
- TTS remains automatic after result load and uses a compact mute/unmute control.
- `shadcn/ui` means local copied primitives, not a runtime `shadcn` package.
- The redesign may add frontend dependencies/configuration, but it may not change backend contracts.