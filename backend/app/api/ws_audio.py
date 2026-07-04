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

from app.config import get_settings
from app.core.stt import build_stt_provider
from app.middleware.auth import authenticate_websocket
from app.models.contracts import AuthClaims

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
    claims: AuthClaims | None = Depends(authenticate_websocket),
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
    if claims is None:
        return

    from app.main import app  # local import avoids circular reference at module load

    session = app.state.sessions.get_for_claims(claims, session_id)
    if session is None:
        await websocket.close(code=4002)
        return

    await websocket.accept()

    settings = get_settings()
    telemetry = app.state.telemetry.bind(
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
    try:
        async for event in provider.stream(_frame_generator(websocket)):
            if isinstance(event, FinalTranscriptEvent):
                latency_ms = int((time.monotonic() - start_time) * 1000)
                telemetry.emit(
                    "stt.transcript.final", 
                    tier=2, 
                    provider=provider_name, 
                    confidence=event.confidence, 
                    latency_ms=latency_ms
                )
            await websocket.send_json(event.model_dump(mode="json"))
        # Stream exhausted (stop_recording received and final transcript emitted)
        await websocket.close(code=close_code)
    except WebSocketDisconnect:
        # Browser disconnected mid-stream
        close_code = 1006
        return
    except NotImplementedError:
        # Deepgram provider skeleton activated without implementation (Slice 4 gap).
        telemetry.emit("stt.error", tier=2, error_type="relay")
        close_code = 1011
        await websocket.send_json(
            {"type": "error", "code": "relay_error", "message": "STT provider not available."}
        )
        await websocket.close(code=close_code)
    except DeepgramUnavailableError:
        telemetry.emit("stt.error", tier=2, error_type="deepgram_connection")
        close_code = 1011
        try:
            await websocket.send_json(
                {"type": "error", "code": "deepgram_unavailable", "message": "Speech-to-text service is temporarily unavailable."}
            )
            await websocket.close(code=close_code)
        except Exception:
            pass
    except Exception:
        telemetry.emit("stt.error", tier=2, error_type="relay")
        close_code = 1011
        try:
            await websocket.send_json(
                {"type": "error", "code": "relay_error", "message": "An unexpected error occurred during audio processing."}
            )
            await websocket.close(code=close_code)
        except Exception:
            pass
    finally:
        telemetry.emit("stt.ws.lifecycle", tier=2, action="closed", close_code=close_code)
