from uuid import uuid4, UUID

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.config import get_settings


@pytest.fixture
def override_tts_fake():
    settings = get_settings()
    original = settings.tts_provider
    settings.tts_provider = "fake"
    yield settings
    settings.tts_provider = original


@pytest.fixture
def auth_token() -> str:
    # Use fake auth provider fallback token
    return "fake"


def test_ws_tts_requires_auth():
    client = TestClient(app)
    session_id = uuid4()
    turn_id = uuid4()
    with pytest.raises(Exception):
        with client.websocket_connect(f"/ws/tts?session_id={session_id}&turn_id={turn_id}") as websocket:
            websocket.receive_bytes()


def test_ws_tts_session_not_found(auth_token):
    client = TestClient(app)
    session_id = uuid4()
    turn_id = uuid4()
    
    with pytest.raises(Exception):
        with client.websocket_connect(
            f"/ws/tts?session_id={session_id}&turn_id={turn_id}&token={auth_token}"
        ) as websocket:
            websocket.receive_bytes()
    # Depending on starlette version, it raises a ConnectionClosed or similar error when 4002 is sent
    # We just ensure it doesn't stay open


def test_ws_tts_turn_not_found(auth_token):
    client = TestClient(app)
    
    # Create a session
    response = client.post(
        "/api/session",
        json={"tenant_id": "00000000-0000-0000-0000-000000000101"},
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert response.status_code == 201
    session_id = response.json()["session_id"]
    turn_id = uuid4()  # Does not exist
    
    with pytest.raises(Exception):
        with client.websocket_connect(
            f"/ws/tts?session_id={session_id}&turn_id={turn_id}&token={auth_token}"
        ) as websocket:
            websocket.receive_bytes()


def test_ws_tts_success(auth_token, override_tts_fake):
    client = TestClient(app)
    
    # Create a session
    response = client.post(
        "/api/session",
        json={"tenant_id": "00000000-0000-0000-0000-000000000101"},
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert response.status_code == 201
    session_id = response.json()["session_id"]
    
    # Manually inject a turn into the session for testing
    from app.main import app as main_app
    fake_user_id = "00000000-0000-0000-0000-000000000001"
    fake_tenant_id = "00000000-0000-0000-0000-000000000101"
    from app.models.contracts import InputModality, TurnRecord
    
    turn_id = uuid4()
    dummy_turn = TurnRecord(
        turn_id=turn_id,
        session_id=session_id,
        conversation_id=uuid4(),
        user_id=fake_user_id,
        tenant_id=fake_tenant_id,
        user_input="hello",
        input_modality=InputModality.voice,
        tts_text="Hello, here is your data.",
    )
    # Insert into the pipeline's in-memory turn store
    main_app.state.pipeline.turns[turn_id] = dummy_turn
    
    # Now connect
    with client.websocket_connect(
        f"/ws/tts?session_id={session_id}&turn_id={turn_id}&token={auth_token}"
    ) as websocket:
        chunk1 = websocket.receive_bytes()
        assert len(chunk1) > 0
        chunk2 = websocket.receive_bytes()
        assert len(chunk2) > 0
