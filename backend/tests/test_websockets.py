from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app


client = TestClient(app)
TENANT_ID = "00000000-0000-0000-0000-000000000101"


def test_fake_audio_socket_returns_final_transcript():
    session = client.post("/api/session", json={"tenant_id": TENANT_ID}).json()
    with client.websocket_connect(f"/ws/audio?session_id={session['session_id']}&token=fake") as ws:
        ws.send_bytes(b"fake-audio")
        interim = ws.receive_json()
        assert interim["type"] == "interim_transcript"
        ws.send_text('{"type":"stop_recording"}')
        final = ws.receive_json()
        assert final["type"] == "final_transcript"
        assert final["text"] == "Show revenue by region"


def test_pipeline_socket_receives_result_ready_for_clear_query():
    session = client.post("/api/session", json={"tenant_id": TENANT_ID}).json()
    with client.websocket_connect(
        f"/ws/pipeline?session_id={session['session_id']}&token=fake"
    ) as ws:
        query = client.post(
            "/api/query",
            json={
                "session_id": session["session_id"],
                "submitted_text": "Show net revenue by customer segment",
                "input_modality": "text",
            },
        )
        assert query.status_code == 202
        assert query.json()["status"] == "processing"
        progress = ws.receive_json()
        assert progress["type"] == "pipeline_progress"
        result = receive_until(ws, "result_ready")
        assert result["turn_id"] == query.json()["turn_id"]
        assert result["chart_type"] == "bar"


def test_pipeline_socket_receives_clarification_and_result_after_selection():
    session = client.post("/api/session", json={"tenant_id": TENANT_ID}).json()
    with client.websocket_connect(
        f"/ws/pipeline?session_id={session['session_id']}&token=fake"
    ) as ws:
        query = client.post(
            "/api/query",
            json={
                "session_id": session["session_id"],
                "submitted_text": "Show revenue by region",
                "input_modality": "text",
            },
        )
        clarification = receive_until(ws, "clarification_request")
        assert clarification["question"] == "Which revenue metric did you mean?"
        assert "Net revenue" in clarification["options"]

        response = client.post(
            "/api/clarification",
            json={
                "session_id": session["session_id"],
                "turn_id": query.json()["turn_id"],
                "selection": "Net revenue",
                "resolution_type": "option_selected",
            },
        )
        assert response.status_code == 200
        result = receive_until(ws, "result_ready")
        assert result["turn_id"] == query.json()["turn_id"]


def test_pipeline_socket_clarifies_vague_top_item_query():
    session = client.post("/api/session", json={"tenant_id": TENANT_ID}).json()
    with client.websocket_connect(
        f"/ws/pipeline?session_id={session['session_id']}&token=fake"
    ) as ws:
        query = client.post(
            "/api/query",
            json={
                "session_id": session["session_id"],
                "submitted_text": "What is the top item?",
                "input_modality": "text",
            },
        )
        clarification = receive_until(ws, "clarification_request")

        assert query.status_code == 202
        assert clarification["turn_id"] == query.json()["turn_id"]
        assert clarification["type"] == "clarification_request"


def receive_until(ws, event_type: str):
    for _ in range(8):
        event = ws.receive_json()
        if event["type"] == event_type:
            return event
    raise AssertionError(f"Did not receive {event_type}")
