"""
STT provider abstraction (engineering-spec.md §3 module: core/stt.py).

Provider hierarchy:
  SttProvider (ABC)
    ├── FakeSttProvider   – default; no external credentials; used in tests and dev.
    └── DeepgramSttProvider – skeleton for Slice 4; raises NotImplementedError at stream time.

build_stt_provider(settings) is the single factory entry-point used by ws_audio.py.
Provider-specific logic must never appear in the route handler.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from app.models.contracts import FinalTranscriptEvent, InterimTranscriptEvent

if TYPE_CHECKING:
    from app.config import Settings


class SttProvider(ABC):
    @abstractmethod
    async def stream(self, audio_frames: AsyncIterator[bytes]) -> AsyncIterator[object]:
        """Yield transcript events (InterimTranscriptEvent / FinalTranscriptEvent) from raw PCM audio frames."""


class FakeSttProvider(SttProvider):
    """
    Deterministic fake provider for tests and local dev.
    Emits one interim transcript after the first audio frame, then a final transcript
    after the frame generator is exhausted (i.e. after stop_recording is received).
    No external network call is made.
    """

    async def stream(self, audio_frames: AsyncIterator[bytes]) -> AsyncIterator[object]:
        yielded_interim = False
        async for _frame in audio_frames:
            if not yielded_interim:
                yielded_interim = True
                yield InterimTranscriptEvent(text="Show revenue")
        yield FinalTranscriptEvent(text="Show revenue by region", confidence=0.97)


class DeepgramSttProvider(SttProvider):
    """
    Deepgram Nova-2 streaming provider — Slice 4 placeholder.

    This skeleton exists so that:
      - build_stt_provider() can return the correct type when STT_PROVIDER=deepgram.
      - Startup validation (Settings.validate_startup) can enforce key presence.
      - Tests can assert provider type without touching the Deepgram network.

    The stream() method raises NotImplementedError until Slice 4 is implemented.
    The API key is accepted at construction but never logged.
    """

    def __init__(self, api_key: str) -> None:
        # Store privately; never log or expose this value.
        self._api_key = api_key

    async def stream(self, audio_frames: AsyncIterator[bytes]) -> AsyncIterator[object]:
        raise NotImplementedError(
            "DeepgramSttProvider.stream() is not yet implemented. "
            "Set STT_PROVIDER=fake to use the fake provider. "
            "Real Deepgram relay will be added in Slice 4."
        )
        # unreachable; presence of yield makes this an async generator so the
        # return type AsyncIterator[object] is satisfied by the type checker.
        yield  # type: ignore[misc]


def build_stt_provider(settings: Settings) -> SttProvider:
    """
    Factory that maps Settings → SttProvider.

    Rules (from gate-4-deepgram-plan.md Slice 3):
      - STT_PROVIDER=fake  → FakeSttProvider (default; no credentials needed)
      - STT_PROVIDER=deepgram → DeepgramSttProvider (key must be present;
        validated earlier by Settings.validate_startup())

    Provider-specific construction details must not leak into the route handler.
    """
    if settings.stt_provider == "deepgram":
        if not settings.deepgram_api_key:
            # Defensive guard: validate_startup() should catch this first,
            # but guard here too so the factory is safe if called independently.
            raise RuntimeError("DEEPGRAM_API_KEY is required when STT_PROVIDER=deepgram.")
        return DeepgramSttProvider(api_key=settings.deepgram_api_key)
    return FakeSttProvider()
