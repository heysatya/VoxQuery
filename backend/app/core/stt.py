from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from app.models.contracts import FinalTranscriptEvent, InterimTranscriptEvent


class SttProvider(ABC):
    @abstractmethod
    async def stream(self, audio_frames: AsyncIterator[bytes]) -> AsyncIterator[object]:
        """Yield transcript events from raw PCM audio frames."""


class FakeSttProvider(SttProvider):
    async def stream(self, audio_frames: AsyncIterator[bytes]) -> AsyncIterator[object]:
        yielded_interim = False
        async for _frame in audio_frames:
            if not yielded_interim:
                yielded_interim = True
                yield InterimTranscriptEvent(text="Show revenue")
        yield FinalTranscriptEvent(text="Show revenue by region", confidence=0.97)
