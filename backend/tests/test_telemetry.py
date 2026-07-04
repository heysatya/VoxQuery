"""
Tests for StructuredLogger and emit() (services/telemetry.py).

Written before the implementation (TDD red phase).

Design contract:
  - emit() writes a single JSON line to stdout per call.
  - Every emitted line contains: event (str), tier (int), ts (ISO8601 str).
  - emit() never raises under any failure condition (telemetry must not crash the app).
  - StructuredLogger carries bound context fields, merged into every emit call.
  - Payload kwargs override bound context on field name conflict.
  - bind() returns a new logger without mutating the parent.
  - No secrets (API keys, tokens) are logged — enforced at call sites, not here.
"""

from __future__ import annotations

import json

import pytest

from app.services.telemetry import StructuredLogger, emit


# ---------------------------------------------------------------------------
# Module-level emit() — JSON output correctness
# ---------------------------------------------------------------------------


def test_emit_writes_a_single_json_line_to_stdout(capsys):
    emit("stt.test.event", tier=2, value=1.0)
    out = capsys.readouterr().out.strip()
    assert out, "emit() produced no output"
    line = json.loads(out)
    assert line["event"] == "stt.test.event"
    assert line["tier"] == 2
    assert line["value"] == pytest.approx(1.0)


def test_emit_always_includes_required_envelope_fields(capsys):
    emit("trust.test", tier=1)
    out = capsys.readouterr().out.strip()
    line = json.loads(out)
    assert "event" in line, "missing 'event'"
    assert "tier" in line, "missing 'tier'"
    assert "ts" in line, "missing 'ts' (ISO8601 timestamp)"


def test_emit_timestamp_is_iso8601_string(capsys):
    from datetime import datetime
    emit("stt.test", tier=2)
    out = capsys.readouterr().out.strip()
    ts = json.loads(out)["ts"]
    # Must parse without error — datetime.fromisoformat() is strict
    dt = datetime.fromisoformat(ts)
    assert dt.tzinfo is not None, "timestamp must be timezone-aware (UTC)"


def test_emit_payload_kwargs_appear_in_output(capsys):
    emit("stt.ws.lifecycle", tier=2, action="opened", session_id="sess-1")
    out = capsys.readouterr().out.strip()
    line = json.loads(out)
    assert line["action"] == "opened"
    assert line["session_id"] == "sess-1"


def test_emit_tier_defaults_to_2(capsys):
    emit("stt.test.default_tier")
    out = capsys.readouterr().out.strip()
    line = json.loads(out)
    assert line["tier"] == 2


# ---------------------------------------------------------------------------
# Fault tolerance — emit() must never raise
# ---------------------------------------------------------------------------


def test_emit_does_not_raise_on_non_serializable_payload(capsys):
    class Unserializable:
        pass

    # Must complete without raising; output must still be valid JSON.
    emit("stt.test", tier=2, bad=Unserializable())
    out = capsys.readouterr().out.strip()
    assert out, "emit() produced no output for non-serializable payload"
    json.loads(out)  # must still be valid JSON


def test_emit_does_not_raise_when_print_itself_fails(monkeypatch):
    def broken_print(*args, **kwargs):
        raise OSError("stdout broken")

    # print is a builtin — must be patched at the builtins level.
    monkeypatch.setattr("builtins.print", broken_print)
    emit("stt.test", tier=2, value=42)  # must not raise


# ---------------------------------------------------------------------------
# StructuredLogger — context binding
# ---------------------------------------------------------------------------


def test_structured_logger_bind_propagates_context_to_emit(capsys):
    logger = StructuredLogger(session_id="abc123", tenant_id="t-1")
    logger.emit("stt.ws.lifecycle", action="opened")
    out = capsys.readouterr().out.strip()
    line = json.loads(out)
    assert line["session_id"] == "abc123"
    assert line["tenant_id"] == "t-1"
    assert line["action"] == "opened"


def test_structured_logger_payload_overrides_bound_context_on_conflict(capsys):
    logger = StructuredLogger(session_id="original")
    logger.emit("stt.test", session_id="override")
    out = capsys.readouterr().out.strip()
    line = json.loads(out)
    assert line["session_id"] == "override"


def test_structured_logger_bind_returns_new_instance(capsys):
    parent = StructuredLogger(session_id="parent-sess")
    child = parent.bind(tenant_id="child-tenant")
    parent.emit("test.parent")
    child.emit("test.child")
    lines = [json.loads(l) for l in capsys.readouterr().out.strip().splitlines()]
    parent_line = next(l for l in lines if l["event"] == "test.parent")
    child_line = next(l for l in lines if l["event"] == "test.child")
    # Parent must not have child's extra context.
    assert "tenant_id" not in parent_line
    assert child_line["tenant_id"] == "child-tenant"
    assert child_line["session_id"] == "parent-sess"


def test_structured_logger_bind_does_not_mutate_parent():
    parent = StructuredLogger(session_id="p")
    _ = parent.bind(tenant_id="extra")
    # Parent's internal context must be unchanged.
    assert "tenant_id" not in parent._context


def test_structured_logger_emit_tier_default_is_2(capsys):
    logger = StructuredLogger()
    logger.emit("ai.test")
    out = capsys.readouterr().out.strip()
    line = json.loads(out)
    assert line["tier"] == 2


def test_empty_structured_logger_emits_valid_json(capsys):
    logger = StructuredLogger()
    logger.emit("stt.test", tier=3)
    out = capsys.readouterr().out.strip()
    line = json.loads(out)
    assert line["event"] == "stt.test"
    assert line["tier"] == 3
