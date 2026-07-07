"""
WebSocket TTS relay endpoint (PRD 4.7).

Responsibility: Authenticate the connection, look up the turn_id to get the TTS text,
invoke the TTS provider, and stream raw PCM audio bytes to the browser.
"""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from app.config import get_settings
from app.core.tts import build_tts_provider, TTSUnavailableError
from app.middleware.auth import authenticate_websocket
from app.models.contracts import AuthClaims

router = APIRouter()
logger = logging.getLogger("voxquery.ws_tts")


@router.websocket("/ws/tts")
async def tts_socket(
    websocket: WebSocket,
    session_id: UUID,
    turn_id: UUID,
    claims: AuthClaims | None = Depends(authenticate_websocket),
) -> None:
    if claims is None:
        return

    from app.main import app

    session = app.state.sessions.get_for_claims(claims, session_id)
    if session is None:
        await websocket.close(code=4002)
        return

    try:
        turn = app.state.pipeline.get_turn_for_user(turn_id, claims)
    except Exception:
        await websocket.close(code=4004) # Not found
        return

    text_to_speak = turn.tts_text
    if not text_to_speak:
        await websocket.close(code=1000)
        return

    await websocket.accept()

    settings = get_settings()
    telemetry = app.state.telemetry.bind(
        session_id=str(session_id),
        tenant_id=str(claims.tenant_id),
        user_id=str(claims.user_id),
        turn_id=str(turn_id),
    )
    
    telemetry.emit("tts.ws.lifecycle", tier=2, action="opened")
    provider = build_tts_provider(settings, logger=logger)

    close_code = 1000
    try:
        async for chunk in provider.stream_audio(text_to_speak):
            await websocket.send_bytes(chunk)
        await websocket.close(code=close_code)
    except WebSocketDisconnect:
        close_code = 1006
        return
    except TTSUnavailableError:
        telemetry.emit("tts.error", tier=2, error_type="deepgram_connection")
        close_code = 1011
        try:
            await websocket.close(code=close_code)
        except Exception:
            pass
    except Exception as exc:
        logger.error(f"TTS streaming error: {exc}")
        telemetry.emit("tts.error", tier=2, error_type="relay")
        close_code = 1011
        try:
            await websocket.close(code=close_code)
        except Exception:
            pass
    finally:
        telemetry.emit("tts.ws.lifecycle", tier=2, action="closed", close_code=close_code)
