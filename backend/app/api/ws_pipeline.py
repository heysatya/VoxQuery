import asyncio
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from websockets.exceptions import ConnectionClosed

from app.config import Settings, get_settings
from app.middleware.auth import authenticate_websocket_message

router = APIRouter()
logger = logging.getLogger("voxquery.ws_pipeline")


@router.websocket("/ws/pipeline")
async def pipeline_socket(
    websocket: WebSocket,
    session_id: UUID,
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

    queue = websocket.app.state.events.connect(session_id)
    try:
        while True:
            event = await queue.get()
            await websocket.send_json(event)
    except (WebSocketDisconnect, ConnectionClosed, asyncio.CancelledError, RuntimeError):
        logger.info("Pipeline WebSocket connection closed cleanly (session: %s)", session_id)
    finally:
        websocket.app.state.events.disconnect(session_id, queue)

