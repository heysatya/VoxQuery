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
# DeepgramSttProvider skeleton safety
# ---------------------------------------------------------------------------


async def test_deepgram_provider_stream_raises_not_implemented():
    """
    The Slice 3 DeepgramSttProvider skeleton must raise NotImplementedError
    on the first iteration — it must never attempt a network call.
    """
    provider = DeepgramSttProvider(api_key="sk-test-placeholder")

    async def empty_frames():
        return
        yield  # make it an async generator

    with pytest.raises(NotImplementedError, match="Slice 4"):
        async for _ in provider.stream(empty_frames()):
            pass  # pragma: no cover
