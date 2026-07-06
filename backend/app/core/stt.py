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


class DeepgramUnavailableError(Exception):
    pass


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

        url = "wss://api.deepgram.com/v1/listen?model=nova-2&smart_format=true&encoding=linear16&sample_rate=16000&channels=1&interim_results=true"
        headers = {"Authorization": f"Token {self._api_key}"}

        try:
            async with websockets.connect(url, additional_headers=headers) as ws:
                sender_exception = None
                async def sender():
                    nonlocal sender_exception
                    try:
                        async for frame in audio_frames:
                            await ws.send(frame)
                        await ws.send(json.dumps({"type": "CloseStream"}))
                    except asyncio.CancelledError:
                        pass
                    except websockets.exceptions.ConnectionClosed:
                        # Upstream closed, recv loop will catch the same closure
                        pass
                    except Exception as e:
                        from starlette.websockets import WebSocketDisconnect
                        if isinstance(e, WebSocketDisconnect):
                            sender_exception = e
                        else:
                            sender_exception = DeepgramUnavailableError("Deepgram send failed")
                        # Unblock the recv loop
                        try:
                            await ws.close()
                        except Exception:
                            pass

                sender_task = asyncio.create_task(sender())

                try:
                    while True:
                        if sender_exception:
                            raise sender_exception
                        try:
                            msg = await asyncio.wait_for(ws.recv(), timeout=15.0)
                        except asyncio.TimeoutError:
                            sender_task.cancel()
                            if sender_exception:
                                raise sender_exception
                            raise DeepgramUnavailableError("No messages received from Deepgram for 15s (idle timeout)")

                        if isinstance(msg, bytes):
                            continue

                        data = json.loads(msg)

                        if data.get("type") == "Error":
                            err_msg = data.get("err_msg", "Unknown error")
                            if self._api_key in err_msg:
                                err_msg = err_msg.replace(self._api_key, "[REDACTED]")
                            raise DeepgramUnavailableError(f"Deepgram returned error frame: {err_msg}")

                        if data.get("type") == "Results":
                            channel = data.get("channel", {})
                            alts = channel.get("alternatives", [])
                            if alts:
                                transcript = alts[0].get("transcript", "")
                                words = alts[0].get("words", [])
                                if words:
                                    confidence = sum(w.get("confidence", 0.0) for w in words) / len(words)
                                else:
                                    confidence = alts[0].get("confidence", 0.0)
                                is_final = data.get("is_final", False)
                                
                                if transcript.strip():
                                    if is_final:
                                        yield FinalTranscriptEvent(text=transcript, confidence=confidence)
                                    else:
                                        yield InterimTranscriptEvent(text=transcript)
                except websockets.exceptions.ConnectionClosedOK:
                    if sender_exception:
                        raise sender_exception
                except websockets.exceptions.ConnectionClosedError as e:
                    if sender_exception:
                        raise sender_exception
                    raise e
                finally:
                    sender_task.cancel()

        except DeepgramUnavailableError:
            raise
        except Exception as e:
            from starlette.websockets import WebSocketDisconnect
            if isinstance(e, WebSocketDisconnect):
                raise
            err_msg = str(e)
            if self._api_key in err_msg:
                err_msg = err_msg.replace(self._api_key, "[REDACTED]")
            raise DeepgramUnavailableError(f"Deepgram connection error: {err_msg}") from e


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
