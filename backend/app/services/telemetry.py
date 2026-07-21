"""
Structured telemetry logger for VoxQuery (replaces services/observability.py no-op).

Design principles:
  - emit() writes one JSON line to stdout per call. Queryable with jq in dev,
    indexable in Railway/Datadog/CloudWatch in production with no config change.
  - Never raises. Telemetry must not crash the application under any condition.
  - No abstraction hierarchy, no database, no sink injection at this stage.
    A PostgresTelemetrySink will be added at pilot readiness when real data exists.
  - Callers are responsible for never passing secrets (API keys, tokens) in payload.
    The logger serialises whatever it receives — it has no secret-detection logic.

Usage:
    # Module-level (simple, no context):
    from app.services.telemetry import emit
    emit("stt.ws.lifecycle", action="opened", session_id="...")

    # Context-carrying (route handlers):
    log = app.state.telemetry.bind(session_id=str(sid), tenant_id=str(tid))
    log.emit("stt.transcript.final", confidence=0.94, latency_ms=2100)
    child_log = log.bind(turn_id=str(turn_id))  # add more context without mutating parent

Gate 4 events defined in docs/voice-subsystem/execution-gate4.md.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from typing import Any


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


import re

_SECRET_PATTERN = re.compile(r'(sk-[a-zA-Z0-9]+|sk_test_[a-zA-Z0-9]+|Bearer\s+[a-zA-Z0-9\-\._~+/]+=*|Basic\s+[a-zA-Z0-9\+/]+=*)')

def _scrub_value(val: Any) -> Any:
    if isinstance(val, str) and _SECRET_PATTERN.search(val):
        return "***SCRUBBED***"
    return val

def _safe_dumps(payload: dict[str, Any]) -> str:
    """
    Serialise payload to a JSON string.

    For any value that json.dumps cannot handle, fall back to repr() so the
    event is always emitted as valid JSON rather than silently dropped.
    """
    scrubbed = {k: _scrub_value(v) for k, v in payload.items()}
    try:
        return json.dumps(scrubbed, default=str)
    except Exception:
        # Second-level fallback: repr every value individually.
        safe: dict[str, Any] = {}
        for k, v in scrubbed.items():
            try:
                json.dumps(v, default=str)
                safe[k] = v
            except Exception:
                safe[k] = repr(v)
        try:
            return json.dumps(safe)
        except Exception:
            return json.dumps({"event": payload.get("event", "unknown"), "error": "serialization_failed"})


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def emit(event: str, tier: int = 2, **payload: Any) -> None:
    """
    Emit a structured telemetry event as a JSON line to stdout.

    Args:
        event: Dotted event name. Convention: "<subsystem>.<noun>.<verb_or_state>"
               e.g. "stt.transcript.final", "trust.auth.failure", "stt.ws.lifecycle"
        tier:  Metric tier.
               1 = trust     (invariants; any breach is a production incident)
               2 = ai_quality (AI pipeline performance; reviewed weekly)
               3 = business  (user-value indicators; reviewed per pilot sprint)
        **payload: Arbitrary key-value context. Must not contain secrets.

    This function never raises. If the underlying print() call fails (e.g. broken
    stdout in a test harness), the exception is silently swallowed.
    """
    try:
        line = _safe_dumps({
            "event": event,
            "tier": tier,
            "ts": _utcnow_iso(),
            **payload,
        })
        print(line, file=sys.stdout, flush=True)
    except Exception:
        # Absolute last-resort guard. Do not re-raise — telemetry must never
        # propagate exceptions into the application call stack.
        pass


class StructuredLogger:
    """
    Context-carrying wrapper around emit().

    Attach one instance to app.state.telemetry in main.py (unbound root logger).
    Route handlers call .bind(...) to create a request-scoped child logger that
    automatically includes session_id, tenant_id, etc. on every call.

    bind() returns a new StructuredLogger — the parent is never mutated.

    Example:
        # In main.py:
        app.state.telemetry = StructuredLogger()

        # In a route handler:
        log = app.state.telemetry.bind(session_id=str(sid), tenant_id=str(tid))
        log.emit("stt.ws.lifecycle", action="opened")
        log.emit("stt.transcript.final", confidence=0.94, latency_ms=2100)
    """

    def __init__(self, **context: Any) -> None:
        # Immutable after construction — bind() always creates a new instance.
        self._context: dict[str, Any] = dict(context)

    def emit(self, event: str, tier: int = 2, **payload: Any) -> None:
        """
        Emit an event, merging bound context with payload.
        Payload kwargs win on field name conflict with bound context.
        """
        emit(event, tier, **{**self._context, **payload})

    def bind(self, **extra: Any) -> "StructuredLogger":
        """
        Return a new StructuredLogger with additional context fields merged in.
        The parent logger is not modified.
        """
        return StructuredLogger(**{**self._context, **extra})
