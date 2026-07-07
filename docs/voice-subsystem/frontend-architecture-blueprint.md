# VoxQuery Frontend Architecture Blueprint

## Purpose

This blueprint defines the target frontend architecture for the VoxQuery voice-first UI redesign.

The current MVP frontend concentrates auth handling, session lifecycle, WebSocket logic, Web Audio logic, TTS playback, pipeline state, clarification state, feedback handling, text input, fake voice, and result rendering inside `frontend/app/page.tsx`.

The refactor must split that monolith into:

1. A headless engine hook that owns behavior and backend interaction.
2. Pure presentation components that render state and emit user intent.
3. A lightweight page shell that handles auth gating and animated layout composition.

The redesign must feel like a ground-up voice-first interface following the **"Ambient Intelligence"** philosophy. It must look premium, discarding technical dashboards, sidebars, and explicit pipeline trackers in favor of a clean, narrative-driven 3-state flow (Ready → Thinking → Insight). It must not discard working MVP capabilities.

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

## The Three States of VoxQuery

The UI is driven by three distinct visual states with graceful animated transitions between them.

1. **State 1: "Ready" — The Listening Concierge**
   - The Orb is large, centered, and breathing with a subtle gradient.
   - A warm, human prompt: "What would you like to know?"
   - 3 pre-seeded starter questions as pill buttons.
   - Minimal text input floating at the bottom as a fallback.
   - Tiny status bar at the bottom: connection status, voice toggle, reset.

2. **State 2: "Thinking" — The Processing State**
   - The Orb shifts to a purposeful, directional animation and an amber color.
   - The user's question (transcript) is displayed prominently.
   - A human-readable status line replaces the technical pipeline tracker (e.g., "Analyzing your data...").

3. **State 3: "Insight" — The Answer**
   - Question Echo with a miniaturized orb anchored at the top.
   - **InsightNarrative**: The most important element. Large, beautiful typography for the storytelling text, with a TTS indicator.
   - **DataGlassPanel**: Clean Recharts visualization in a frosted glass card below the narrative.
   - Trust Layer inside the chart card: Confidence tier, chart rationale, collapsed "View SQL" toggle, CSV download.
   - **FollowUpSuggestions**: 2-3 proactive next questions as pill buttons.
   - Persistent text input at the bottom.

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
│       ├── insight/
│       │   ├── InsightNarrative.tsx
│       │   └── FollowUpSuggestions.tsx
│       └── ui/
│           └── local shadcn/ui-style primitives
├── lib/
│   ├── api.ts
│   ├── types.ts
│   └── utils.ts
```

`page.tsx` must become a composition shell. It may handle auth gating and layout state, but it must not contain backend calls, WebSocket setup, Web Audio setup, session lifecycle code, or backend payload construction.

## UI Foundation & Visual Design Language

The frontend must use:

- TailwindCSS for styling.
- Framer Motion for animation and spatial layout transitions.
- React Markdown for narrative text formatting.
- shadcn/ui-style local primitives for common controls.
- Lucide icons where icons improve clarity.

**Design Aesthetics ("Private members' club" dark mode):**
- **Backgrounds:** Near-black base (`#0C0D11`) with elevated surfaces (`#161822`, `#1E2030`).
- **Typography:** `Inter` for standard text and data, `JetBrains Mono` for SQL. High contrast for primary text, softer for secondary.
- **Glassmorphism:** Frosted glass effect for cards and panels.
- **Accents:** Blue for idle/listening, Amber for thinking, Green for success, Rose for recording/errors.
- **Micro-Animations:** Slow breathing for idle orb, directional animations for thinking, staggered fade-ins for charts and follow-ups.

## Headless Engine Hook

Create `frontend/app/hooks/useVoxQuerySession.ts`.
The hook owns all stateful behavior and all backend interaction. It exposes state variables (`recordingState`, `pipelineStage`, `lastResult`, etc.) and actions (`startRecording`, `submitQuery`, `muteTTS`, etc.).

## Required Engine Behavior

The hook must preserve these behaviors:
- Create a session through the existing session API.
- Resume a stored session from `window.sessionStorage.getItem("voxquery_session_id")`.
- Store only `voxquery_session_id`, not `conversation_id`.
- Open the pipeline WebSocket when auth and session are ready.
- Probe microphone permission when supported and send telemetry.
- Use the existing AudioWorklet path for PCM streaming.
- Send binary PCM frames over the audio WebSocket.
- Handle pipeline progress, clarification, and result-ready events.
- Fetch the result through the existing result API.
- Start TTS playback after result load using the existing TTS WebSocket.
- Submit text queries, clarifications, and feedback (rating: -1) through existing APIs.

## Presentation Components

Presentation components must receive props and callbacks only. They must not own backend lifecycles.

### VoiceVisualizer
- Renders the primary hero voice orb.
- Displays idle, connecting, recording, and processing states.
- Uses `AnalyserNode` for live visualization.
- Resizes dynamically based on the application state (large in Ready/Thinking, small in Insight).

### InsightNarrative (NEW)
- Renders the storytelling text returned by the backend.
- Formats text using `react-markdown` with appropriate typography.
- Displays TTS playing state.

### DataGlassPanel
- Renders the data visualization (Chart or Table).
- Includes Trust Layer: Confidence tier, chart rationale.
- Includes Collapsed SQL View and CSV Download.
- Incorporates feedback controls.

### FollowUpSuggestions (NEW)
- Renders proactive follow-up questions as pill buttons.
- On click, fires a new query.

### ClarificationOverlay
- Interruptive clarification state rendered as a dark glass card.
- Renders conversational question, options, countdown, and escape action.

### QueryDock
- Secondary reliability controls.
- Provides editable text fallback, fake voice (for testing), and conversation reset.
- Minimal and visually secondary to the main interface.

## Page Composition

`frontend/app/page.tsx` must preserve the auth split (Fake vs Clerk).
The voice-first shell uses Framer Motion for transitioning between the 3 core states.
The layout must include mobile fallbacks and not rely solely on desktop panels. Sidebars, technical pipeline trackers, and morning briefings from the original MVP are strictly removed.

## Backend Compatibility

Do not change the behavior of:
- `/api/session`, `/api/query`, `/api/clarification`, `/api/result/{turnId}`, `/api/feedback`, `/api/telemetry`
- `/ws/pipeline`, `/ws/audio`, `/ws/tts`

Do not change existing request or response shapes.

## Test Requirements

The refactor must update or add tests covering equivalent behavior in `frontend/app/page.test.tsx`.
Required coverage includes session persistence, WebSocket behaviors, text fallback, mic permissions, stop recording sequence, clarification flows, and rendering of new components (DataGlassPanel, FollowUpSuggestions, InsightNarrative).

Required verification commands:
```bash
npm test
npm run build
```

## Acceptance Criteria

The refactor is complete only when:
- `page.tsx` is no longer a monolithic behavior container.
- `useVoxQuerySession` owns backend, session, WebSocket, audio, TTS, telemetry, clarification, and feedback behavior.
- Presentation components are pure and backend-agnostic.
- The UI is genuinely voice-first (Ambient Intelligence).
- Fake auth and Clerk auth both still work.
- Existing backend contracts are unchanged.
- Tests and build pass.