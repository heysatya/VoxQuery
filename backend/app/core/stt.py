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
from app.services.telemetry import StructuredLogger

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

    def __init__(self, api_key: str, logger: StructuredLogger | None = None) -> None:
        # Store privately; never log or expose this value.
        self._api_key = api_key
        self._logger = logger or StructuredLogger()

    async def stream(self, audio_frames: AsyncIterator[bytes]) -> AsyncIterator[object]:
        import json
        import asyncio
        import websockets
        from websockets.exceptions import ConnectionClosed

        url = "wss://api.deepgram.com/v1/listen?model=nova-2&smart_format=true"
        headers = {"Authorization": f"Token {self._api_key}"}

        self._logger.emit("stt.ws.lifecycle", tier=2, action="opened", provider="deepgram")

        try:
            async with websockets.connect(url, additional_headers=headers) as ws:
                async def sender():
                    try:
                        async for frame in audio_frames:
                            await ws.send(frame)
                        await ws.send(json.dumps({"type": "CloseStream"}))
                    except asyncio.CancelledError:
                        pass
                    except Exception:
                        pass

                sender_task = asyncio.create_task(sender())

                try:
                    while True:
                        try:
                            msg = await asyncio.wait_for(ws.recv(), timeout=15.0)
                        except asyncio.TimeoutError:
                            self._logger.emit("stt.error", tier=2, error_type="idle_timeout", details="No messages received from Deepgram for 15s")
                            sender_task.cancel()
                            break

                        if isinstance(msg, bytes):
                            continue

                        data = json.loads(msg)

                        if data.get("type") == "Error":
                            continue

                        if data.get("type") == "Results":
                            channel = data.get("channel", {})
                            alts = channel.get("alternatives", [])
                            if alts:
                                transcript = alts[0].get("transcript", "")
                                confidence = alts[0].get("confidence", 0.0)
                                is_final = data.get("is_final", False)
                                
                                if transcript.strip():
                                    if is_final:
                                        self._logger.emit("stt.transcript.final", tier=3, provider="deepgram", confidence=confidence)
                                        yield FinalTranscriptEvent(text=transcript, confidence=confidence)
                                    else:
                                        yield InterimTranscriptEvent(text=transcript)
                except websockets.exceptions.ConnectionClosedOK:
                    pass
                except websockets.exceptions.ConnectionClosedError as e:
                    raise e
                finally:
                    sender_task.cancel()

        except Exception as e:
            err_msg = str(e)
            if self._api_key in err_msg:
                err_msg = err_msg.replace(self._api_key, "[REDACTED]")
            self._logger.emit("stt.error", tier=2, error_type="deepgram_connection", details=err_msg)
            raise Exception("Deepgram connection error") from e
        finally:
            self._logger.emit("stt.ws.lifecycle", tier=2, action="closed", provider="deepgram")


def build_stt_provider(settings: Settings, logger: StructuredLogger | None = None) -> SttProvider:
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
        return DeepgramSttProvider(api_key=settings.deepgram_api_key, logger=logger)
    return FakeSttProvider()
