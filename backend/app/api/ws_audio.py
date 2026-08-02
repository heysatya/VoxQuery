"""
WebSocket audio relay endpoint (engineering-spec.md §3 module: api/ws_audio.py).

Responsibility (single): accept authenticated audio WebSocket connections and
delegate all STT logic to the configured SttProvider. The route knows nothing
about Deepgram, PCM encoding, or transcript text — all of that lives in
app/core/stt.py.

Frame protocol (interface-contracts.md §1):
  Browser → Backend:  binary frames (raw PCM audio)
  Browser → Backend:  JSON text {"type": "stop_recording"} to end stream
  Backend → Browser:  JSON InterimTranscriptEvent / FinalTranscriptEvent / error
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator
from uuid import UUID

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from app.config import Settings, get_settings
from app.core.stt import build_stt_provider
from app.middleware.auth import authenticate_websocket_message

router = APIRouter()
logger = logging.getLogger("voxquery.ws_audio")


async def _frame_generator(websocket: WebSocket) -> AsyncGenerator[bytes, None]:
    """
    Yield binary audio frames from the WebSocket until a stop_recording message
    is received or the connection drops.

    Binary frames are yielded as-is to the STT provider.
    Text frames are inspected for {"type": "stop_recording"}; on receipt the
    generator returns (exhausted), which causes the provider to emit its final
    transcript and then stop.

    Any other text frame is silently ignored to future-proof the protocol.
    """
    while True:
        message = await websocket.receive()
        if "bytes" in message and message["bytes"] is not None:
            yield message["bytes"]
        elif "text" in message and message["text"] is not None:
            try:
                parsed = json.loads(message["text"])
                if isinstance(parsed, dict) and parsed.get("type") == "stop_recording":
                    return  # signal: stream is over; provider will emit final transcript
            except (json.JSONDecodeError, AttributeError):
                pass  # malformed text frame — ignore and keep reading


@router.websocket("/ws/audio")
async def audio_socket(
    websocket: WebSocket,
    session_id: UUID,
    settings: Settings = Depends(get_settings),
) -> None:
    """
    Authenticated audio relay WebSocket.

    Auth and session validation happen before accept(); a rejected connection
    never reaches the STT provider.

    After accept(), binary audio frames are streamed to the configured STT
    provider. Events emitted by the provider are forwarded to the browser as
    JSON text frames. On normal completion (final transcript sent) the
    connection is closed with code 1000.

    WebSocket close codes (interface-contracts.md §1):
      1000 — normal close after final transcript
      4001 — auth failed (handled by authenticate_websocket before accept)
      4002 — session not found
    """
    await websocket.accept()
    claims = await authenticate_websocket_message(websocket, settings)
    if claims is None:
        return

    session = await websocket.app.state.sessions.get_for_claims(claims, session_id)
    if session is None:
        await websocket.close(code=4002)
        return

    limit = await websocket.app.state.rate_limiter.check_rate_limit(
        str(claims.user_id), str(claims.tenant_id)
    )
    if not limit.available:
        await websocket.close(code=1013, reason="Request protection is temporarily unavailable")
        return
    if not limit.ok:
        # 4429: custom close code for rate limit exceeded
        await websocket.close(
            code=4429, reason=f"Rate limit exceeded. Retry after {limit.retry_after_seconds}s"
        )
        return

    settings = get_settings()
    telemetry = websocket.app.state.telemetry.bind(
        session_id=str(session_id),
        tenant_id=str(claims.tenant_id),
        user_id=str(claims.user_id),
    )
    import time
    from app.core.stt import DeepgramUnavailableError
    from app.models.contracts import FinalTranscriptEvent

    start_time = time.monotonic()

    telemetry.emit("stt.ws.lifecycle", tier=2, action="opened")
    provider = build_stt_provider(settings, logger=telemetry)
    provider_name = "deepgram" if settings.stt_provider == "deepgram" else "fake"

    close_code = 1000
    stop_time = None

    async def intercept_stop(gen):
        nonlocal stop_time
        async for frame in gen:
            yield frame
        stop_time = time.monotonic()

    try:
        async for event in provider.stream(intercept_stop(_frame_generator(websocket))):
            if isinstance(event, FinalTranscriptEvent):
                if stop_time is None:
                    stop_time = time.monotonic()
                latency_ms = int((time.monotonic() - stop_time) * 1000)
                telemetry.emit(
                    "stt.transcript.final",
                    tier=2,
                    provider=provider_name,
                    confidence=event.confidence,
                    latency_ms=latency_ms,
                )
            await websocket.send_json(event.model_dump(mode="json"))
        # Stream exhausted (stop_recording received and final transcript emitted)
        await websocket.close(code=close_code)
    except WebSocketDisconnect:
        # Browser disconnected mid-stream
        close_code = 1006
        return

    except DeepgramUnavailableError as exc:
        telemetry.emit("stt.error", tier=2, error_type="deepgram_connection", detail=str(exc))
        close_code = 1011
        try:
            await websocket.send_json(
                {
                    "type": "error",
                    "code": "deepgram_unavailable",
                    "message": "Speech-to-text service is temporarily unavailable.",
                }
            )
            await websocket.close(code=close_code)
        except Exception as exc:
            logger.exception("Audio streaming error: %s", str(exc))
    except Exception as exc:
        logger.exception("Audio streaming error: %s", str(exc))
        telemetry.emit("stt.error", tier=2, error_type="relay")
        close_code = 1011
        try:
            await websocket.send_json(
                {
                    "type": "error",
                    "code": "relay_error",
                    "message": "An unexpected error occurred during audio processing.",
                }
            )
            await websocket.close(code=close_code)
        except Exception as exc:
            logger.exception("Audio streaming error: %s", str(exc))
    finally:
        telemetry.emit("stt.ws.lifecycle", tier=2, action="closed", close_code=close_code)
