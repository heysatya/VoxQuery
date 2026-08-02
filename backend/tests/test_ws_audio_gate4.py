import json
from uuid import uuid4
from fastapi.testclient import TestClient

from app.main import app
from app.config import get_settings
from app.core.stt import DeepgramUnavailableError
from app.models.contracts import InterimTranscriptEvent

client = TestClient(app)
TENANT_ID = "00000000-0000-0000-0000-000000000101"


def test_telemetry_spoofed_session_returns_api_error_envelope():
    response = client.post(
        "/api/telemetry",
        json={"session_id": str(uuid4()), "event": "stt.mic.permission", "outcome": "granted"},
    )
    assert response.status_code == 403
    data = response.json()
    assert "error" in data
    assert data["error"]["code"] == "session_not_found"
    assert "message" in data["error"]


def test_ws_audio_fake_provider_happy_path(capsys, monkeypatch):
    # force STT_PROVIDER=fake
    settings = get_settings()
    monkeypatch.setattr(settings, "stt_provider", "fake")

    session = client.post("/api/session", json={"tenant_id": TENANT_ID}).json()
    session_id = session["session_id"]

    with client.websocket_connect(f"/ws/audio?session_id={session_id}&token=fake") as ws:
        ws.send_bytes(b"chunk1")
        interim = ws.receive_json()
        assert interim["type"] == "interim_transcript"

        ws.send_text(json.dumps({"type": "stop_recording"}))
        final = ws.receive_json()
        assert final["type"] == "final_transcript"

    out = capsys.readouterr().out
    logs = [json.loads(line) for line in out.strip().splitlines() if line.strip()]

    # Assert one stt.ws.lifecycle opened event
    opened_logs = [
        log
        for log in logs
        if log.get("event") == "stt.ws.lifecycle" and log.get("action") == "opened"
    ]
    assert len(opened_logs) == 1
    assert opened_logs[0]["session_id"] == session_id
    assert opened_logs[0]["tenant_id"] == TENANT_ID

    # Assert one stt.transcript.final event
    final_logs = [log for log in logs if log.get("event") == "stt.transcript.final"]
    assert len(final_logs) == 1
    assert final_logs[0]["provider"] == "fake"
    assert final_logs[0]["confidence"] == 0.97
    assert "latency_ms" in final_logs[0]
    assert final_logs[0]["session_id"] == session_id
    assert final_logs[0]["tenant_id"] == TENANT_ID

    # Assert one stt.ws.lifecycle closed event with close_code 1000
    closed_logs = [
        log
        for log in logs
        if log.get("event") == "stt.ws.lifecycle" and log.get("action") == "closed"
    ]
    assert len(closed_logs) == 1
    assert closed_logs[0]["close_code"] == 1000
    assert closed_logs[0]["session_id"] == session_id
    assert closed_logs[0]["tenant_id"] == TENANT_ID

    # Assert no stt.error
    error_logs = [log for log in logs if log.get("event") == "stt.error"]
    assert len(error_logs) == 0


def test_ws_audio_provider_unavailable_path(capsys, monkeypatch):
    session = client.post("/api/session", json={"tenant_id": TENANT_ID}).json()
    session_id = session["session_id"]

    class UnavailableProvider:
        async def stream(self, audio_frames):
            raise DeepgramUnavailableError("Deepgram temporarily unavailable")
            yield InterimTranscriptEvent(text="dummy")  # For typing

    import app.api.ws_audio

    monkeypatch.setattr(
        app.api.ws_audio, "build_stt_provider", lambda s, logger: UnavailableProvider()
    )

    with client.websocket_connect(f"/ws/audio?session_id={session_id}&token=fake") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert msg["code"] == "deepgram_unavailable"
        assert "message" in msg

        # TestClient currently does not surface close_code properly on raises sometimes,
        # but we can rely on receive_json throwing or we just assert the message is received.
        # Check telemetry for stt.error

    out = capsys.readouterr().out
    logs = [json.loads(line) for line in out.strip().splitlines() if line.strip()]

    error_logs = [log for log in logs if log.get("event") == "stt.error"]
    assert len(error_logs) == 1
    assert error_logs[0]["error_type"] == "deepgram_connection"

    closed_logs = [
        log
        for log in logs
        if log.get("event") == "stt.ws.lifecycle" and log.get("action") == "closed"
    ]
    assert len(closed_logs) == 1
    assert closed_logs[0]["close_code"] == 1011


def test_ws_audio_generic_relay_exception_path(capsys, monkeypatch):
    session = client.post("/api/session", json={"tenant_id": TENANT_ID}).json()
    session_id = session["session_id"]

    class GenericErrorProvider:
        async def stream(self, audio_frames):
            raise RuntimeError("Something bad happened internally")
            yield InterimTranscriptEvent(text="dummy")

    import app.api.ws_audio

    monkeypatch.setattr(
        app.api.ws_audio, "build_stt_provider", lambda s, logger: GenericErrorProvider()
    )

    with client.websocket_connect(f"/ws/audio?session_id={session_id}&token=fake") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert msg["code"] == "relay_error"

    out = capsys.readouterr().out
    logs = [json.loads(line) for line in out.strip().splitlines() if line.strip()]

    error_logs = [log for log in logs if log.get("event") == "stt.error"]
    assert len(error_logs) == 1
    assert error_logs[0]["error_type"] == "relay"

    closed_logs = [
        log
        for log in logs
        if log.get("event") == "stt.ws.lifecycle" and log.get("action") == "closed"
    ]
    assert len(closed_logs) == 1
    assert closed_logs[0]["close_code"] == 1011
