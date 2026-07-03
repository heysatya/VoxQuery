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
    provider = build_stt_provider(settings)

    try:
        async for event in provider.stream(_frame_generator(websocket)):
            await websocket.send_json(event.model_dump(mode="json"))
        # Stream exhausted (stop_recording received and final transcript emitted)
        await websocket.close(code=1000)
    except WebSocketDisconnect:
        # Browser disconnected mid-stream; upstream cleanup is the provider's
        # responsibility in Slice 4. FakeSttProvider has no upstream to clean.
        return
    except NotImplementedError:
        # Deepgram provider skeleton activated without implementation (Slice 4 gap).
        logger.error("STT provider not implemented; check STT_PROVIDER setting.")
        await websocket.send_json(
            {"type": "error", "code": "relay_error", "message": "STT provider not available."}
        )
        await websocket.close(code=1011)
