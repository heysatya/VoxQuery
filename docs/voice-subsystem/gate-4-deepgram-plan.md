# Gate 4 Deepgram Streaming Plan

## Objective

Implement real browser-to-backend-to-Deepgram streaming while preserving the existing fake
voice mode and Clerk-authenticated `/ws/audio` contract.

Gate 4 is not complete until:

- Browser microphone permission is handled explicitly.
- Browser audio is converted to 16-bit 16kHz mono PCM.
- `/ws/audio` relays binary audio frames to Deepgram.
- Interim transcripts update live.
- Final transcripts include confidence.
- Client disconnect closes the upstream Deepgram connection.
- Text fallback remains available if audio fails.

## Non-Negotiable Boundaries

- Do not put the Deepgram API key in the browser.
- Do not paste the Deepgram API key into chat.
- Do not remove fake voice mode; it remains the default test/fallback path.
- Do not send audio bytes to any LLM API.
- Do not start real Deepgram integration without a local backend env key.
- Keep WebSockets; do not introduce LiveKit.

## Slice 1 - Browser Permission And Audio Capture Shell

Scope:

- Add microphone permission state: `unknown | prompt | granted | denied`.
- Add real recording controls without removing `Fake voice`.
- Preserve editable transcript behavior.
- Handle denied permission with a clear UI notice and keep text input usable.

Tests:

- Permission denied leaves `recordingState=idle` and text input enabled.
- Permission granted enters `connecting`.
- Fake voice behavior remains unchanged.

Stop conditions:

- Browser permission APIs behave inconsistently in test/dev and cannot be represented safely.
- UI changes degrade fake mode or text fallback.

## Slice 2 - AudioWorklet And PCM Conversion Risk Burn-Down

Scope:

- Add an AudioWorklet or equivalent capture path behind a small browser-side adapter.
- Convert microphone audio to linear PCM, 16-bit, 16kHz, mono.
- Emit approximately 100ms binary chunks to the existing `/ws/audio` connection.

Tests:

- Unit-test resampling/PCM conversion with deterministic sample buffers.
- Verify binary frame size and type.
- Verify stop sends `{ "type": "stop_recording" }`.

Stop conditions:

- AudioWorklet loading is blocked by Next/static asset constraints.
- Resampling quality or browser compatibility requires a larger design decision.

## Slice 3 - Backend STT Adapter Interface

Scope:

- Introduce a backend STT provider abstraction.
- Keep fake STT as the default test provider.
- Add Deepgram provider skeleton behind `STT_PROVIDER=deepgram`.
- Validate startup requires `DEEPGRAM_API_KEY` only when the Deepgram provider is selected.

Tests:

- Fake provider keeps current `/ws/audio` tests passing.
- `STT_PROVIDER=deepgram` without key fails startup safely.
- Test mode does not require external Deepgram credentials.

Stop conditions:

- Provider abstraction leaks Deepgram-specific details into route handlers.
- Startup validation risks breaking fake/test mode.

## Slice 4 - Deepgram Relay And Lifecycle

Scope:

- Connect backend `/ws/audio` to Deepgram Nova streaming.
- Relay browser binary frames upstream.
- Relay interim/final transcripts downstream using existing contract events.
- Close Deepgram on browser disconnect, stop message, Deepgram close, relay error, and idle timeout.

Tests:

- Mock Deepgram WebSocket happy path: interim then final transcript.
- Client disconnect closes upstream.
- Deepgram close sends a safe browser error and closes client.
- Idle timeout closes both sides.
- No token or Deepgram key appears in logs.

Stop conditions:

- No Deepgram API key configured locally.
- Deepgram response schema differs materially from expected Nova streaming events.
- Lifecycle tests show an orphaned upstream connection path.

## Slice 5 - Real Deepgram Smoke

Required setup:

- Add `DEEPGRAM_API_KEY` to backend local env only.
- Set `STT_PROVIDER=deepgram`.
- Confirm Deepgram no-log/data-retention setting separately before pilot use.

Smoke sequence:

1. Start backend and frontend.
2. Sign in with Clerk.
3. Start real recording.
4. Speak a short query.
5. Confirm interim transcript appears.
6. Stop recording.
7. Confirm final transcript and confidence appear.
8. Submit reviewed transcript.
9. Confirm text fallback still works after audio failure/retry.
10. Confirm logs contain no Clerk token or Deepgram key.

Post-smoke verification:

- `SESSION_STORE=memory uv run pytest`
- `npm test -- --run`
- `npm run build`
- `npm audit --audit-level moderate`

## First Implementation Pass Recommendation

Start with Slice 1 and Slice 3 together only if their file sets remain small and separable:

- Frontend: permission state, recording control shape, fake mode preserved.
- Backend: STT provider interface and fake provider extraction.

Do not implement real Deepgram network calls in the first pass.
