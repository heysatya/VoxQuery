import asyncio
from queue import Empty
from uuid import UUID

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from app.middleware.auth import authenticate_websocket
from app.models.contracts import AuthClaims

router = APIRouter()


@router.websocket("/ws/pipeline")
async def pipeline_socket(
    websocket: WebSocket,
    session_id: UUID,
    claims: AuthClaims | None = Depends(authenticate_websocket),
) -> None:
    if claims is None:
        return
    from app.main import app

    session = app.state.sessions.get_for_claims(claims, session_id)
    if session is None:
        await websocket.close(code=4002)
        return

    await websocket.accept()
    queue = app.state.events.connect(session_id)
    try:
        while True:
            try:
                event = queue.get_nowait()
            except Empty:
                await asyncio.sleep(0.01)
                continue
            await websocket.send_json(event)
    except WebSocketDisconnect:
        app.state.events.disconnect(session_id, queue)
    except RuntimeError:
        app.state.events.disconnect(session_id, queue)
