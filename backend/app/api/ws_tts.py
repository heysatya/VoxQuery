"""
WebSocket TTS relay endpoint (PRD 4.7).

Responsibility: Authenticate the connection, look up the turn_id to get the TTS text,
invoke the TTS provider, and stream raw PCM audio bytes to the browser.
"""

import asyncio
import logging
import time
from uuid import UUID

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from websockets.exceptions import ConnectionClosed

from app.api.rest import _get_turn_for_user
from app.config import Settings, get_settings
from app.core.tts import build_tts_provider, TTSUnavailableError
from app.middleware.auth import authenticate_websocket_message

router = APIRouter()
logger = logging.getLogger("voxquery.ws_tts")


@router.websocket("/ws/tts")
async def tts_socket(
    websocket: WebSocket,
    session_id: UUID,
    turn_id: UUID,
    settings: Settings = Depends(get_settings),
) -> None:
    await websocket.accept()
    claims = await authenticate_websocket_message(websocket, settings)
    if claims is None:
        return

    session = await websocket.app.state.sessions.get_for_claims(claims, session_id)
    if session is None:
        await websocket.close(code=4002)
        return

    db_pool = getattr(websocket.app.state, "db_pool", None)
    try:
        turn = await _get_turn_for_user(turn_id, claims, websocket.app.state.pipeline, db_pool)
    except Exception:
        await websocket.close(code=4004)  # Not found
        return

    text_to_speak = turn.tts_text
    if not text_to_speak:
        await websocket.close(code=1000)
        return

    # Removed duplicate accept

    # Removed duplicate get_settings
    telemetry = websocket.app.state.telemetry.bind(
        session_id=str(session_id),
        tenant_id=str(claims.tenant_id),
        user_id=str(claims.user_id),
        turn_id=str(turn_id),
    )

    telemetry.emit("tts.ws.lifecycle", tier=2, action="opened")
    provider_name = "deepgram" if settings.tts_provider == "deepgram" else "fake"
    provider = build_tts_provider(settings, logger=logger)

    close_code = 1000
    chunk_count = 0
    byte_count = 0
    started_at = time.monotonic()
    try:
        async for chunk in provider.stream_audio(text_to_speak):
            chunk_count += 1
            byte_count += len(chunk)
            await websocket.send_bytes(chunk)
        telemetry.emit(
            "tts.audio.complete",
            tier=2,
            provider=provider_name,
            chunk_count=chunk_count,
            byte_count=byte_count,
            latency_ms=int((time.monotonic() - started_at) * 1000),
        )
        await websocket.close(code=close_code)
    except (WebSocketDisconnect, ConnectionClosed, asyncio.CancelledError):
        close_code = 1006
        logger.info("TTS WebSocket connection closed cleanly (session: %s)", session_id)
        return
    except TTSUnavailableError:
        telemetry.emit("tts.error", tier=2, error_type="deepgram_connection")
        close_code = 1011
        try:
            await websocket.send_json(
                {
                    "type": "error",
                    "code": "tts_unavailable",
                    "message": "Voice playback is temporarily unavailable.",
                }
            )
            await websocket.close(code=close_code)
        except Exception:
            pass
    except Exception as exc:
        logger.exception("TTS streaming error: %s", str(exc))
        telemetry.emit("tts.error", tier=2, error_type="relay")
        close_code = 1011
        try:
            await websocket.send_json(
                {
                    "type": "error",
                    "code": "tts_relay_error",
                    "message": "Voice playback failed.",
                }
            )
            await websocket.close(code=close_code)
        except Exception:
            pass
    finally:
        telemetry.emit("tts.ws.lifecycle", tier=2, action="closed", close_code=close_code)
