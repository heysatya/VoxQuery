from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app


client = TestClient(app)
TENANT_ID = "00000000-0000-0000-0000-000000000101"


def create_session():
    response = client.post("/api/session", json={"tenant_id": TENANT_ID})
    assert response.status_code == 201
    return response.json()


def test_text_query_clarification_then_result_and_feedback():
    session = create_session()
    with client.websocket_connect(f"/ws/pipeline?session_id={session['session_id']}&token=fake") as ws:
        query = client.post(
            "/api/query",
            json={
                "session_id": session["session_id"],
                "submitted_text": "Show revenue by region",
                "input_modality": "text",
            },
        )
        clarification_event = receive_until(ws, "clarification_request")
    assert query.status_code == 202
    body = query.json()
    assert body["status"] == "processing"
    assert clarification_event["turn_id"] == body["turn_id"]

    with client.websocket_connect(f"/ws/pipeline?session_id={session['session_id']}&token=fake") as ws:
        clarification = client.post(
            "/api/clarification",
            json={
                "session_id": session["session_id"],
                "turn_id": body["turn_id"],
                "selection": "Net revenue",
                "resolution_type": "option_selected",
            },
        )
        result_event = receive_until(ws, "result_ready")
    assert clarification.status_code == 200
    assert result_event["turn_id"] == body["turn_id"]

    result = client.get(f"/api/result/{body['turn_id']}")
    assert result.status_code == 200
    payload = result.json()
    assert payload["chart_type"] == "bar"
    assert "order_items" in payload["generated_sql"]

    feedback = client.post(
        "/api/feedback",
        json={
            "session_id": session["session_id"],
            "turn_id": body["turn_id"],
            "rating": -1,
        },
    )
    assert feedback.status_code == 200
    duplicate_feedback = client.post(
        "/api/feedback",
        json={
            "session_id": session["session_id"],
            "turn_id": body["turn_id"],
            "rating": -1,
        },
    )
    assert duplicate_feedback.status_code == 409
    assert duplicate_feedback.json()["error"]["code"] == "feedback_duplicate"


def test_clear_non_ambiguous_query_returns_before_result_ready():
    session = create_session()
    with client.websocket_connect(f"/ws/pipeline?session_id={session['session_id']}&token=fake") as ws:
        query = client.post(
            "/api/query",
            json={
                "session_id": session["session_id"],
                "submitted_text": "Show net revenue by customer segment",
                "input_modality": "text",
            },
        )
        body = query.json()
        immediate_result = client.get(f"/api/result/{body['turn_id']}")
        assert immediate_result.status_code == 202
        result_event = receive_until(ws, "result_ready")
    assert query.status_code == 202
    assert body["status"] == "processing"
    assert result_event["turn_id"] == body["turn_id"]
    result = client.get(f"/api/result/{body['turn_id']}")
    assert result.status_code == 200
    payload = result.json()
    assert payload["result"]["columns"] == ["customer_segment", "total_net_revenue"]
    assert "order_items" in payload["generated_sql"]
    assert "customers.customer_segment" in payload["generated_sql"]
    assert payload["chart_rationale"].endswith("customer_segment.")


def test_clarification_escape_does_not_complete_turn():
    session = create_session()
    with client.websocket_connect(f"/ws/pipeline?session_id={session['session_id']}&token=fake") as ws:
        query = client.post(
            "/api/query",
            json={
                "session_id": session["session_id"],
                "submitted_text": "Show revenue by state",
                "input_modality": "text",
            },
        )
        clarification_event = receive_until(ws, "clarification_request")
    assert query.status_code == 202
    body = query.json()
    assert body["status"] == "processing"
    assert clarification_event["turn_id"] == body["turn_id"]

    escaped = client.post(
        "/api/clarification",
        json={
            "session_id": session["session_id"],
            "turn_id": body["turn_id"],
            "selection": None,
            "resolution_type": "escaped",
        },
    )
    assert escaped.status_code == 200

    result = client.get(f"/api/result/{body['turn_id']}")
    assert result.status_code == 404


def test_clarification_timeout_proceeds_with_original_query():
    session = create_session()
    with client.websocket_connect(f"/ws/pipeline?session_id={session['session_id']}&token=fake") as ws:
        query = client.post(
            "/api/query",
            json={
                "session_id": session["session_id"],
                "submitted_text": "Show revenue by region",
                "input_modality": "text",
            },
        )
        clarification_event = receive_until(ws, "clarification_request")
    body = query.json()
    assert clarification_event["turn_id"] == body["turn_id"]
    stored = app.state.sessions.get(UUID(TENANT_ID), UUID(session["session_id"]))
    assert stored is not None
    assert stored.clarification_state is not None
    stored.clarification_state.issued_at = datetime.now(UTC) - timedelta(seconds=31)

    with client.websocket_connect(f"/ws/pipeline?session_id={session['session_id']}&token=fake") as ws:
        event = receive_until(ws, "result_ready")
        assert event["turn_id"] == body["turn_id"]

    result = client.get(f"/api/result/{body['turn_id']}")
    assert result.status_code == 200
    assert "order_items" in result.json()["generated_sql"]


def test_ecommerce_dimensions_generate_expected_fake_sql():
    session = create_session()
    with client.websocket_connect(f"/ws/pipeline?session_id={session['session_id']}&token=fake") as ws:
        query = client.post(
            "/api/query",
            json={
                "session_id": session["session_id"],
                "submitted_text": "Show net revenue by state",
                "input_modality": "text",
            },
        )
        body = query.json()
        result_event = receive_until(ws, "result_ready")
    assert body["status"] == "processing"
    assert result_event["turn_id"] == body["turn_id"]
    result = client.get(f"/api/result/{body['turn_id']}")
    payload = result.json()
    assert payload["result"]["columns"] == ["geolocation_state", "total_net_revenue"]
    assert "geolocation.geolocation_state" in payload["generated_sql"]
    assert "customers.customer_zip_code_prefix = geolocation.zip_code_prefix" in payload["generated_sql"]


def test_session_tenant_must_match_auth_claims():
    response = client.post(
        "/api/session",
        json={"tenant_id": str(UUID("00000000-0000-0000-0000-000000000999"))},
    )
    assert response.status_code == 401


def test_query_endpoint_rejects_voice_modality():
    session = create_session()
    response = client.post(
        "/api/query",
        json={
            "session_id": session["session_id"],
            "submitted_text": "Show revenue by region",
            "input_modality": "voice",
        },
    )
    assert response.status_code == 400


def test_health_reports_local_stub_dependencies():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["redis"] == "local_stub"
    assert response.json()["postgres"] in ("not_configured", "ok", "degraded")


def test_dev_timeout_route_is_unavailable_outside_local_env():
    session = create_session()
    query = client.post(
        "/api/query",
        json={
            "session_id": session["session_id"],
            "submitted_text": "Show revenue by region",
            "input_modality": "text",
        },
    )
    settings = get_settings()
    original = settings.app_env
    settings.app_env = "production"
    try:
        response = client.post(
            "/api/dev/clarification-timeout",
            json={
                "session_id": session["session_id"],
                "turn_id": query.json()["turn_id"],
                "selection": None,
                "resolution_type": "timeout",
            },
        )
    finally:
        settings.app_env = original
    assert response.status_code == 404


def receive_until(ws, event_type: str):
    for _ in range(8):
        event = ws.receive_json()
        if event["type"] == event_type:
            return event
    raise AssertionError(f"Did not receive {event_type}")
