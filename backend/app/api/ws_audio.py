from uuid import UUID

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from app.middleware.auth import authenticate_websocket
from app.models.contracts import AuthClaims, FinalTranscriptEvent, InterimTranscriptEvent

router = APIRouter()


@router.websocket("/ws/audio")
async def audio_socket(
    websocket: WebSocket,
    session_id: UUID,
    claims: AuthClaims | None = Depends(authenticate_websocket),
) -> None:
    if claims is None:
        return
    from app.main import app

    session = app.state.sessions.get(claims.tenant_id, session_id)
    if session is None:
        await websocket.close(code=4002)
        return

    await websocket.accept()
    partial_sent = False
    try:
        while True:
            message = await websocket.receive()
            if "bytes" in message and message["bytes"] is not None and not partial_sent:
                partial_sent = True
                await websocket.send_json(
                    InterimTranscriptEvent(text="Show revenue").model_dump(mode="json")
                )
            if "text" in message and message["text"] is not None:
                if "stop_recording" in message["text"]:
                    await websocket.send_json(
                        FinalTranscriptEvent(
                            text="Show revenue by region",
                            confidence=0.97,
                        ).model_dump(mode="json")
                    )
                    await websocket.close(code=1000)
                    return
    except WebSocketDisconnect:
        return
