"""
Tests for the STT provider abstraction (Slice 3 – Gate 4).

Design contract (from engineering-spec.md §3 and gate-4-deepgram-plan.md):
  - STT_PROVIDER=fake  → FakeSttProvider; no external credentials required.
  - STT_PROVIDER=deepgram → DeepgramSttProvider; requires DEEPGRAM_API_KEY.
  - STT_PROVIDER=deepgram without key → validate_startup() raises RuntimeError.
  - Tests never touch the real Deepgram network.
  - FakeSttProvider.stream() emits interim then final transcript in that order.
"""

from __future__ import annotations

import pytest

from app.config import Settings
from app.core.stt import DeepgramSttProvider, FakeSttProvider, build_stt_provider
from app.models.contracts import FinalTranscriptEvent, InterimTranscriptEvent
from unittest.mock import AsyncMock, patch
import asyncio
import json
from app.services.telemetry import StructuredLogger


# ---------------------------------------------------------------------------
# Factory selection
# ---------------------------------------------------------------------------


def test_fake_provider_is_default():
    """STT_PROVIDER defaults to 'fake'; no credentials required."""
    settings = Settings(APP_ENV="test")
    provider = build_stt_provider(settings)
    assert isinstance(provider, FakeSttProvider)


def test_fake_provider_selected_explicitly():
    """STT_PROVIDER=fake works when set explicitly."""
    settings = Settings(APP_ENV="test", STT_PROVIDER="fake")
    provider = build_stt_provider(settings)
    assert isinstance(provider, FakeSttProvider)


def test_deepgram_provider_selected_when_key_present():
    """STT_PROVIDER=deepgram with a key returns a DeepgramSttProvider instance."""
    settings = Settings(
        APP_ENV="test",
        STT_PROVIDER="deepgram",
        DEEPGRAM_API_KEY="sk-test-placeholder",
    )
    provider = build_stt_provider(settings)
    assert isinstance(provider, DeepgramSttProvider)


def test_invalid_stt_provider_raises_at_settings_construction():
    """An unrecognised STT_PROVIDER value is rejected at Settings parse time."""
    with pytest.raises(Exception):  # pydantic ValidationError
        Settings(APP_ENV="test", STT_PROVIDER="whisper")


# ---------------------------------------------------------------------------
# Startup validation
# ---------------------------------------------------------------------------


def test_startup_validation_deepgram_without_key_raises():
    """validate_startup() must fail when STT_PROVIDER=deepgram and key is absent."""
    settings = Settings(APP_ENV="test", STT_PROVIDER="deepgram", DEEPGRAM_API_KEY=None)
    with pytest.raises(RuntimeError, match="DEEPGRAM_API_KEY"):
        settings.validate_startup()


def test_startup_validation_deepgram_blank_key_treated_as_missing():
    """A blank DEEPGRAM_API_KEY must be treated the same as absent."""
    settings = Settings(APP_ENV="test", STT_PROVIDER="deepgram", DEEPGRAM_API_KEY="   ")
    with pytest.raises(RuntimeError, match="DEEPGRAM_API_KEY"):
        settings.validate_startup()


def test_startup_validation_fake_does_not_require_key():
    """validate_startup() must not raise when STT_PROVIDER=fake (default)."""
    settings = Settings(APP_ENV="test", STT_PROVIDER="fake")
    settings.validate_startup()  # must not raise


def test_startup_validation_fake_ignores_absent_deepgram_key():
    """Fake mode with no DEEPGRAM_API_KEY must still pass startup validation."""
    settings = Settings(APP_ENV="test", STT_PROVIDER="fake", DEEPGRAM_API_KEY=None)
    settings.validate_startup()  # must not raise


# ---------------------------------------------------------------------------
# FakeSttProvider stream behaviour
# ---------------------------------------------------------------------------


async def test_fake_provider_emits_interim_then_final():
    """
    FakeSttProvider.stream() must:
      1. Yield an InterimTranscriptEvent after the first audio frame.
      2. Yield a FinalTranscriptEvent after the frame generator is exhausted.
      3. Yield events in that order with no duplicates.
    """
    async def single_frame():
        yield b"\x00\x01\x02\x03"  # one 100ms-shaped binary chunk

    provider = FakeSttProvider()
    events: list[object] = []
    async for event in provider.stream(single_frame()):
        events.append(event)

    assert len(events) == 2, "Expected exactly interim + final"
    assert isinstance(events[0], InterimTranscriptEvent)
    assert events[0].text == "Show revenue"
    assert events[0].is_final is False

    assert isinstance(events[1], FinalTranscriptEvent)
    assert events[1].text == "Show revenue by region"
    assert events[1].confidence == pytest.approx(0.97)
    assert events[1].is_final is True


async def test_fake_provider_emits_single_interim_across_multiple_frames():
    """
    FakeSttProvider must yield exactly one InterimTranscriptEvent
    regardless of how many binary frames it receives.
    """
    async def many_frames():
        for _ in range(5):
            yield b"\x00" * 3200  # five chunks

    provider = FakeSttProvider()
    events: list[object] = []
    async for event in provider.stream(many_frames()):
        events.append(event)

    interim_events = [e for e in events if isinstance(e, InterimTranscriptEvent)]
    final_events = [e for e in events if isinstance(e, FinalTranscriptEvent)]
    assert len(interim_events) == 1
    assert len(final_events) == 1


# ---------------------------------------------------------------------------
# DeepgramSttProvider Slice 4 behaviour
# ---------------------------------------------------------------------------

class MockDeepgramWS:
    def __init__(self, messages_to_yield, throw_on_close=False):
        self.messages = messages_to_yield
        self.throw_on_close = throw_on_close
        self.closed = False
        self.send = AsyncMock()
        self.close = AsyncMock()
        self._msg_iter = iter(self.messages)
        
        async def mock_recv():
            try:
                return next(self._msg_iter)
            except StopIteration:
                from websockets.exceptions import ConnectionClosedOK
                import websockets.frames
                raise ConnectionClosedOK(websockets.frames.Close(1000, ""), None)
                
        self.recv = AsyncMock(side_effect=mock_recv)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.throw_on_close and not exc_type:
            from websockets.exceptions import ConnectionClosed
            raise ConnectionClosed(None, None)
        self.closed = True

@pytest.fixture
def mock_logger():
    class TestLogger(StructuredLogger):
        def __init__(self):
            super().__init__()
            self.emitted = []
        def emit(self, event, tier=2, **payload):
            self.emitted.append({"event": event, "tier": tier, **payload})
    return TestLogger()

async def test_deepgram_provider_happy_path_interim_then_final(mock_logger):
    interim_resp = json.dumps({"type": "Results", "channel": {"alternatives": [{"transcript": "show revenue", "confidence": 0.89}]}, "is_final": False, "speech_final": False})
    final_resp = json.dumps({"type": "Results", "channel": {"alternatives": [{"transcript": "show revenue by region", "confidence": 0.94}]}, "is_final": True, "speech_final": True})

    mock_ws = MockDeepgramWS([interim_resp, final_resp])

    async def fake_frames():
        yield b"chunk"
        await asyncio.sleep(0.01)

    provider = DeepgramSttProvider(api_key="sk-test-placeholder", logger=mock_logger)

    with patch("websockets.connect", return_value=mock_ws):
        events = []
        async for evt in provider.stream(fake_frames()):
            events.append(evt)

    assert len(events) == 2
    assert isinstance(events[0], InterimTranscriptEvent)
    assert events[0].text == "show revenue"
    assert isinstance(events[1], FinalTranscriptEvent)
    assert events[1].text == "show revenue by region"
    assert events[1].confidence == 0.94

async def test_deepgram_provider_client_disconnect_closes_upstream(mock_logger):
    mock_ws = MockDeepgramWS([])

    async def disconnect_frames():
        yield b"chunk"
        raise StopAsyncIteration()

    provider = DeepgramSttProvider(api_key="sk-test-placeholder", logger=mock_logger)

    with patch("websockets.connect", return_value=mock_ws):
        async for evt in provider.stream(disconnect_frames()):
            pass

    assert mock_ws.closed is True

async def test_deepgram_provider_deepgram_close_yields_safe_error(mock_logger):
    from websockets.exceptions import ConnectionClosedError
    import websockets.frames
    from app.core.stt import DeepgramUnavailableError

    class ThrowingWS(MockDeepgramWS):
        def __init__(self):
            super().__init__([])
            self.count = 0
            
            async def mock_recv():
                if self.count == 0:
                    self.count += 1
                    return json.dumps({"type": "Metadata"})
                raise ConnectionClosedError(websockets.frames.Close(1011, ""), None)
            
            self.recv = AsyncMock(side_effect=mock_recv)

    mock_ws = ThrowingWS()

    async def fake_frames():
        yield b"chunk"
        await asyncio.sleep(0.05)

    provider = DeepgramSttProvider(api_key="sk-test-placeholder", logger=mock_logger)

    with patch("websockets.connect", return_value=mock_ws):
        with pytest.raises(DeepgramUnavailableError) as exc:
            async for evt in provider.stream(fake_frames()):
                pass

        assert "sk-test-placeholder" not in str(exc.value)

async def test_deepgram_provider_idle_timeout_closes_both_sides(mock_logger):
    mock_ws = MockDeepgramWS([])
    from app.core.stt import DeepgramUnavailableError

    async def hanging_frames():
        await asyncio.sleep(20.0) # More than 15s timeout
        yield b"chunk"

    provider = DeepgramSttProvider(api_key="sk-test-placeholder", logger=mock_logger)

    with patch("websockets.connect", return_value=mock_ws):
        with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError):
            with pytest.raises(DeepgramUnavailableError) as exc:
                async for evt in provider.stream(hanging_frames()):
                    pass
            assert "idle timeout" in str(exc.value)

async def test_deepgram_provider_api_key_never_appears_in_exceptions(mock_logger):
    mock_ws = MockDeepgramWS([json.dumps({"type": "Error", "err_msg": "sk-test-abc123"})])
    from app.core.stt import DeepgramUnavailableError

    async def fake_frames():
        yield b"chunk"

    provider = DeepgramSttProvider(api_key="sk-test-abc123", logger=mock_logger)

    with patch("websockets.connect", return_value=mock_ws):
        with pytest.raises(DeepgramUnavailableError) as exc:
            async for evt in provider.stream(fake_frames()):
                pass

        assert "sk-test-abc123" not in str(exc.value)
        assert "[REDACTED]" in str(exc.value)

async def test_deepgram_provider_sender_failure_propagates_safely(mock_logger):
    mock_ws = MockDeepgramWS([])
    from app.core.stt import DeepgramUnavailableError
    from websockets.exceptions import ConnectionClosedOK
    import websockets.frames

    async def blocking_recv():
        await asyncio.sleep(0.1)
        raise ConnectionClosedOK(websockets.frames.Close(1000, ""), None)
    mock_ws.recv = blocking_recv

    async def failing_frames():
        yield b"chunk"
        raise RuntimeError("Something bad happened with microphone sk-test-abc123")

    provider = DeepgramSttProvider(api_key="sk-test-abc123", logger=mock_logger)

    with patch("websockets.connect", return_value=mock_ws):
        with pytest.raises(DeepgramUnavailableError) as exc:
            async for evt in provider.stream(failing_frames()):
                pass

        assert "sk-test-abc123" not in str(exc.value)
        assert "Deepgram send failed" in str(exc.value)

async def test_deepgram_provider_websocket_disconnect_passes_transparently(mock_logger):
    mock_ws = MockDeepgramWS([])
    from websockets.exceptions import ConnectionClosedOK
    import websockets.frames

    async def blocking_recv():
        await asyncio.sleep(0.1)
        raise ConnectionClosedOK(websockets.frames.Close(1000, ""), None)
    mock_ws.recv = blocking_recv

    from starlette.websockets import WebSocketDisconnect
    
    async def disconnect_frames():
        yield b"chunk"
        raise WebSocketDisconnect(code=1006)

    provider = DeepgramSttProvider(api_key="sk-test-abc123", logger=mock_logger)

    with patch("websockets.connect", return_value=mock_ws):
        with pytest.raises(WebSocketDisconnect):
            async for evt in provider.stream(disconnect_frames()):
                pass
