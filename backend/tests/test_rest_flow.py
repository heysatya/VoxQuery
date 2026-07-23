from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from unittest.mock import patch


client = TestClient(app)
TENANT_ID = "00000000-0000-0000-0000-000000000101"


def create_session():
    response = client.post("/api/session", json={"tenant_id": TENANT_ID})
    assert response.status_code == 201
    return response.json()


def test_delete_session_success():
    session = create_session()
    session_id = session["session_id"]
    
    # Try deleting it
    response = client.delete(f"/api/session/{session_id}")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    
    # Verify it is actually deleted by trying to query
    query = client.post(
        "/api/query",
        json={
            "session_id": session_id,
            "submitted_text": "Show revenue by region",
            "input_modality": "text",
        },
    )
    assert query.status_code == 404
    assert query.json()["error"]["code"] == "session_not_found"

def test_delete_session_not_found():
    response = client.delete("/api/session/00000000-0000-0000-0000-000000000999")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "session_not_found"




@patch("app.observability.langfuse.LangfuseTracer.score_feedback")
def test_text_query_clarification_then_result_and_feedback(mock_score_feedback):
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
    
    # Verify telemetry linkage: tracer.score_feedback must be called with the correct turn_id
    mock_score_feedback.assert_called_once()
    assert mock_score_feedback.call_args[0][0] == UUID(body["turn_id"])
    assert mock_score_feedback.call_args[0][1] == -1
    assert mock_score_feedback.call_args[0][4] is True # clarification_triggered
    assert mock_score_feedback.call_args[0][5] == "Net revenue" # option_selected

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
    assert result_event["proactive_questions"]
    result = client.get(f"/api/result/{body['turn_id']}")
    assert result.status_code == 200
    payload = result.json()
    assert payload["proactive_questions"] == result_event["proactive_questions"]
    assert payload["result"]["columns"] == ["customer_segment", "total_net_revenue"]
    assert payload["result"]["semantic_columns"][0]["role"] == "dimension"
    assert payload["result"]["semantic_columns"][1]["role"] == "metric"
    assert payload["valid_visualizations"] == ["table", "bar"]
    assert payload["trust"]["confidence_tier"] == payload["confidence_tier"]
    assert payload["trust"]["confidence_reasons"]
    assert payload["trust"]["row_count"] == payload["result"]["row_count"]
    assert payload["trust"]["execution_time_ms"] >= 0
    assert "order_items" in payload["trust"]["data_sources"]
    assert payload["trust"]["sql_hash"]
    assert payload["trust"]["data_freshness_note"] == "Live warehouse query"
    assert "order_items" in payload["generated_sql"]
    assert "customers.customer_segment" in payload["generated_sql"]
    assert payload["chart_rationale"].endswith("customer_segment.")


async def test_positive_feedback_records_ok_quality_flag():
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
        receive_until(ws, "result_ready")

    feedback = client.post(
        "/api/feedback",
        json={
            "session_id": session["session_id"],
            "turn_id": body["turn_id"],
            "rating": 1,
        },
    )

    assert feedback.status_code == 200
    stored = await app.state.sessions.get(TENANT_ID, UUID(session["session_id"]))
    assert stored is not None
    assert stored.history[-1].quality_flag == "ok"


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

def test_clarification_timeout_is_silently_ignored():
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
    
    body = query.json()
    
    # Manually expire the clarification state in the session store
    store = app.state.sessions
    s = store._sessions.get((TENANT_ID, UUID(session["session_id"])))
    if s and s.clarification_state:
        s.clarification_state.issued_at = datetime.now(UTC) - timedelta(minutes=11)

    expired = client.post(
        "/api/clarification",
        json={
            "session_id": session["session_id"],
            "turn_id": body["turn_id"],
            "selection": "Net revenue",
            "resolution_type": "timeout",
        },
    )
    assert expired.status_code == 200

    result = client.get(f"/api/result/{body['turn_id']}")
    assert result.status_code == 404


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


def test_query_endpoint_accepts_valid_text_contract():
    session = create_session()
    response = client.post(
        "/api/query",
        json={
            "session_id": session["session_id"],
            "parent_turn_id": None,
            "submitted_text": "Show net revenue by customer segment",
            "input_modality": "text",
            "raw_transcript": None,
            "stt_confidence": None,
            "transcript_edited": False,
        },
    )
    assert response.status_code == 202


def test_text_query_rejects_voice_metadata():
    session = create_session()
    base = {
        "session_id": session["session_id"],
        "submitted_text": "Show net revenue by customer segment",
        "input_modality": "text",
        "raw_transcript": None,
        "stt_confidence": None,
        "transcript_edited": False,
    }

    with_raw = {**base, "raw_transcript": "Show revenue"}
    response = client.post("/api/query", json=with_raw)
    assert response.status_code == 400

    with_confidence = {**base, "stt_confidence": 0.97}
    response = client.post("/api/query", json=with_confidence)
    assert response.status_code == 400

    with_edited_flag = {**base, "transcript_edited": True}
    response = client.post("/api/query", json=with_edited_flag)
    assert response.status_code == 400


def test_voice_query_contract_preserves_provenance():
    session = create_session()
    response = client.post(
        "/api/query",
        json={
            "session_id": session["session_id"],
            "parent_turn_id": None,
            "submitted_text": "Show net revenue by customer segment",
            "input_modality": "voice",
            "raw_transcript": "Show net revenue by customer segment",
            "stt_confidence": 0.97,
            "transcript_edited": False,
        },
    )
    assert response.status_code == 202
    turn_id = UUID(response.json()["turn_id"])
    turn = app.state.pipeline.turns[turn_id]
    assert turn.input_modality == "voice"
    assert turn.raw_transcript == "Show net revenue by customer segment"
    assert turn.deepgram_confidence_raw == 0.97
    assert turn.transcript_edited is False


def test_voice_query_contract_accepts_truthful_edit_flag():
    session = create_session()
    response = client.post(
        "/api/query",
        json={
            "session_id": session["session_id"],
            "parent_turn_id": None,
            "submitted_text": "Show net revenue by customer segment for enterprise",
            "input_modality": "voice",
            "raw_transcript": "Show net revenue by customer segment",
            "stt_confidence": 0.91,
            "transcript_edited": True,
        },
    )
    assert response.status_code == 202


def test_voice_query_rejects_missing_or_false_provenance():
    session = create_session()
    base = {
        "session_id": session["session_id"],
        "parent_turn_id": None,
        "submitted_text": "Show net revenue by customer segment",
        "input_modality": "voice",
        "raw_transcript": "Show net revenue by customer segment",
        "stt_confidence": 0.97,
        "transcript_edited": False,
    }

    response = client.post("/api/query", json={**base, "raw_transcript": None})
    assert response.status_code == 400

    response = client.post("/api/query", json={**base, "stt_confidence": None})
    assert response.status_code == 400

    response = client.post("/api/query", json={**base, "submitted_text": "Show net revenue", "transcript_edited": False})
    assert response.status_code == 400


def test_followup_query_uses_first_class_parent_turn_id():
    session = create_session()
    with client.websocket_connect(f"/ws/pipeline?session_id={session['session_id']}&token=fake") as ws:
        first = client.post(
            "/api/query",
            json={
                "session_id": session["session_id"],
                "parent_turn_id": None,
                "submitted_text": "Show net revenue in Germany.",
                "input_modality": "text",
                "raw_transcript": None,
                "stt_confidence": None,
                "transcript_edited": False,
            },
        )
        first_body = first.json()
        receive_until(ws, "result_ready")

    response = client.post(
        "/api/query",
        json={
            "session_id": session["session_id"],
            "parent_turn_id": first_body["turn_id"],
            "submitted_text": "Just enterprise customers.",
            "input_modality": "text",
            "raw_transcript": None,
            "stt_confidence": None,
            "transcript_edited": False,
        },
    )
    assert response.status_code == 202
    followup_turn = app.state.pipeline.turns[UUID(response.json()["turn_id"])]
    assert str(followup_turn.parent_turn_id) == first_body["turn_id"]
    assert followup_turn.user_input == "Just enterprise customers."
    assert "→" not in followup_turn.user_input


def test_followup_rejects_cross_session_parent_turn():
    first_session = create_session()
    with client.websocket_connect(f"/ws/pipeline?session_id={first_session['session_id']}&token=fake") as ws:
        first = client.post(
            "/api/query",
            json={
                "session_id": first_session["session_id"],
                "submitted_text": "Show net revenue by customer segment",
                "input_modality": "text",
            },
        )
        first_body = first.json()
        receive_until(ws, "result_ready")

    second_session = create_session()
    response = client.post(
        "/api/query",
        json={
            "session_id": second_session["session_id"],
            "parent_turn_id": first_body["turn_id"],
            "submitted_text": "Just enterprise customers.",
            "input_modality": "text",
        },
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "turn_forbidden"


def test_followup_rejects_incomplete_parent_turn():
    session = create_session()
    with client.websocket_connect(f"/ws/pipeline?session_id={session['session_id']}&token=fake") as ws:
        first = client.post(
            "/api/query",
            json={
                "session_id": session["session_id"],
                "submitted_text": "Show revenue by region",
                "input_modality": "text",
            },
        )
        first_body = first.json()
        receive_until(ws, "clarification_request")

    # Clear the active in-flight marker so this assertion reaches parent eligibility,
    # not the single-flight guard for the already pending clarification.
    app.state.pipeline._in_flight.discard(UUID(session["session_id"]))
    response = client.post(
        "/api/query",
        json={
            "session_id": session["session_id"],
            "parent_turn_id": first_body["turn_id"],
            "submitted_text": "Just enterprise customers.",
            "input_modality": "text",
        },
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "turn_processing"


def test_health_reports_local_stub_dependencies():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["redis"] == "local_stub"
    assert response.json()["postgres"] in ("not_configured", "ok", "degraded")



def receive_until(ws, event_type: str):
    for _ in range(8):
        event = ws.receive_json()
        if event["type"] == "pipeline_error" and event_type != "pipeline_error":
            raise AssertionError(f"Received error instead of {event_type}: {event}")
        if event["type"] == event_type:
            return event
    raise AssertionError(f"Did not receive {event_type}")
