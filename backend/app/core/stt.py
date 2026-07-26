"""
STT provider abstraction (engineering-spec.md section 3 module: core/stt.py).

Provider hierarchy:
  SttProvider (ABC)
    - FakeSttProvider: default; no external credentials; used in tests and dev.
    - DeepgramSttProvider: production Deepgram streaming STT relay.

build_stt_provider(settings) is the single factory entry-point used by ws_audio.py.
Provider-specific logic must never appear in the route handler.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

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


@dataclass
class _TranscriptSegment:
    text: str
    confidence: float
    weight: int


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
    Deepgram Nova streaming provider.

    Connects to Deepgram's WebSocket API to transcribe audio streams in real time.
    Deepgram can emit several finalized segments before the complete user query is
    done, so this provider buffers those segments and emits the app-level final
    transcript when Deepgram marks a natural endpoint or when the browser
    stops recording and Deepgram flushes.

    The API key is accepted at construction but never logged.
    """

    # Plain-phrase Keyterm Prompting for nova-3 (verified against Deepgram's docs:
    # the older `keywords` param with intensifier syntax like "ARR:2.5" is
    # explicitly documented as NOT supported on nova-3 — "For Nova-3, use Keyterm
    # Prompting instead." Keyterms are plain phrases with no boost syntax.
    # https://developers.deepgram.com/docs/keyterm
    DEFAULT_KEYTERMS: list[str] = [
        "Snowflake",
        "PostgreSQL",
        "ARR",
        "MRR",
        "churn",
        "cohort",
        "tenant",
        "schema",
        "warehouse",
        "pipeline",
    ]

    def __init__(
        self,
        api_key: str,
        logger: StructuredLogger | None = None,
        keyterms: list[str] | None = None,
        mip_opt_out: bool = False,
    ) -> None:
        self._api_key = api_key
        self._logger = logger or StructuredLogger()
        # Falls back to a generic analytics/BI vocabulary; callers can pass
        # tenant-specific terms (e.g. sourced from the existing tenant_glossary
        # table already populated by sync_schema.py) for better per-tenant
        # recall of domain-specific metric/table names.
        self._keyterms = keyterms if keyterms is not None else self.DEFAULT_KEYTERMS
        self._mip_opt_out = mip_opt_out

    async def stream(self, audio_frames: AsyncIterator[bytes]) -> AsyncIterator[object]:
        import asyncio
        import contextlib
        import json
        from urllib.parse import quote

        import websockets

        keyterm_params = "".join(f"&keyterm={quote(term)}" for term in self._keyterms)
        # NOTE on data retention: Deepgram has no "no_log=true" parameter — that
        # does not exist in their API. The real, documented control is
        # mip_opt_out (Model Improvement Program opt-out), which excludes this
        # request from Deepgram's model-training data retention in exchange for
        # forgoing a program discount. It is NOT full "zero data retention" —
        # per Deepgram's own docs, true ZDR requires an Enterprise Agreement.
        # Left as an explicit opt-in setting since it has a real cost tradeoff.
        mip_opt_out_param = "&mip_opt_out=true" if self._mip_opt_out else ""
        url = (
            "wss://api.deepgram.com/v1/listen"
            "?model=nova-3"
            "&language=en-US"
            "&smart_format=true"
            "&punctuate=true"
            "&encoding=linear16"
            "&sample_rate=16000"
            "&channels=1"
            "&interim_results=true"
            "&endpointing=1500"         # 1.5s silence before speech_final fires.
            "&utterance_end_ms=2500"    # 2.5s silence before UtteranceEnd fires — the authoritative submission signal.
            "&vad_events=true"
            f"{keyterm_params}"
            f"{mip_opt_out_param}"
        )
        headers = {"Authorization": f"Token {self._api_key}"}

        try:
            async with websockets.connect(url, additional_headers=headers) as ws:
                sender_exception: BaseException | None = None
                sender_done = asyncio.Event()
                receiver_done = asyncio.Event()
                final_segments: list[_TranscriptSegment] = []
                latest_interim: _TranscriptSegment | None = None

                def normalize_text(parts: list[str]) -> str:
                    return " ".join(part.strip() for part in parts if part and part.strip()).strip()

                def aggregate_final() -> FinalTranscriptEvent | None:
                    if final_segments:
                        text = normalize_text([segment.text for segment in final_segments])
                        total_weight = sum(segment.weight for segment in final_segments)
                        confidence = (
                            sum(segment.confidence * segment.weight for segment in final_segments) / total_weight
                            if total_weight
                            else 0.0
                        )
                        return FinalTranscriptEvent(text=text, confidence=confidence)

                    if latest_interim and latest_interim.text.strip():
                        return FinalTranscriptEvent(
                            text=latest_interim.text.strip(),
                            confidence=latest_interim.confidence,
                        )

                    return None

                def aggregate_interim(current: str | None = None) -> str:
                    parts = [segment.text for segment in final_segments]
                    if current:
                        parts.append(current)
                    return normalize_text(parts)

                def parse_segment(data: dict[str, Any]) -> _TranscriptSegment | None:
                    channel = data.get("channel", {})
                    if not isinstance(channel, dict):
                        return None
                    alts = channel.get("alternatives", [])
                    if not isinstance(alts, list) or not alts or not isinstance(alts[0], dict):
                        return None

                    alt = alts[0]
                    transcript = alt.get("transcript", "")
                    if not isinstance(transcript, str) or not transcript.strip():
                        return None

                    words = alt.get("words", [])
                    if isinstance(words, list) and words:
                        confidences = [
                            word.get("confidence", 0.0)
                            for word in words
                            if isinstance(word, dict) and isinstance(word.get("confidence", 0.0), int | float)
                        ]
                        confidence = sum(confidences) / len(confidences) if confidences else 0.0
                        weight = len(words)
                    else:
                        raw_confidence = alt.get("confidence", 0.0)
                        confidence = raw_confidence if isinstance(raw_confidence, int | float) else 0.0
                        weight = max(len(transcript.split()), 1)

                    return _TranscriptSegment(text=transcript, confidence=float(confidence), weight=weight)

                async def sender() -> None:
                    nonlocal sender_exception
                    try:
                        async for frame in audio_frames:
                            await ws.send(frame)
                        await ws.send(json.dumps({"type": "CloseStream"}))
                        sender_done.set()
                    except asyncio.CancelledError:
                        pass
                    except websockets.exceptions.ConnectionClosed:
                        if not receiver_done.is_set() and not sender_done.is_set():
                            sender_exception = DeepgramUnavailableError(
                                "Deepgram connection closed while sending audio"
                            )
                    except Exception as exc:
                        from starlette.websockets import WebSocketDisconnect

                        if isinstance(exc, WebSocketDisconnect):
                            sender_exception = exc
                        else:
                            sender_exception = DeepgramUnavailableError("Deepgram send failed")

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
                            # If sender already finished but Deepgram went quiet, flush what we have.
                            if sender_done.is_set():
                                final_event = aggregate_final()
                                if final_event:
                                    yield final_event
                                return
                            raise DeepgramUnavailableError("No messages received from Deepgram for 15s (idle timeout)")

                        if isinstance(msg, bytes):
                            continue

                        data = json.loads(msg)
                        if not isinstance(data, dict):
                            continue

                        if data.get("type") == "Error":
                            err_msg = data.get("err_msg", "Unknown error")
                            err_msg = str(err_msg)
                            if self._api_key in err_msg:
                                err_msg = err_msg.replace(self._api_key, "[REDACTED]")
                            raise DeepgramUnavailableError(f"Deepgram returned error frame: {err_msg}")

                        if data.get("type") == "UtteranceEnd":
                            final_event = aggregate_final()
                            if final_event:
                                yield final_event
                                break
                            continue

                        if data.get("type") != "Results":
                            continue

                        segment = parse_segment(data)
                        if not segment:
                            continue

                        is_final = data.get("is_final", False)
                        if is_final:
                            final_segments.append(segment)
                            latest_interim = None
                            text = aggregate_interim()

                            # speech_final=True means Deepgram's VAD detected
                            # an endpointing silence boundary. We accumulate it
                            # into final_segments but do NOT submit yet — we wait
                            # for UtteranceEnd (the authoritative signal) so that
                            # mid-sentence thinking pauses don't trigger early
                            # submission. Only a manual stop_recording bypasses
                            # this and flushes immediately.
                            if sender_done.is_set():
                                # Manual stop: keep reading until Deepgram flushes or closes.
                                if text:
                                    yield InterimTranscriptEvent(text=text)
                            elif text:
                                yield InterimTranscriptEvent(text=text)
                        else:
                            latest_interim = segment
                            text = aggregate_interim(segment.text)
                            if text:
                                yield InterimTranscriptEvent(text=text)
                except websockets.exceptions.ConnectionClosedOK:
                    if sender_exception:
                        raise sender_exception
                    # Deepgram closed the socket cleanly after CloseStream — flush everything.
                    final_event = aggregate_final()
                    if final_event:
                        yield final_event
                except websockets.exceptions.ConnectionClosedError as exc:
                    if sender_exception:
                        raise sender_exception
                    raise exc
                finally:
                    receiver_done.set()
                    sender_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await sender_task

        except DeepgramUnavailableError:
            raise
        except Exception as exc:
            from starlette.websockets import WebSocketDisconnect

            if isinstance(exc, WebSocketDisconnect):
                raise
            err_msg = str(exc)
            if self._api_key in err_msg:
                err_msg = err_msg.replace(self._api_key, "[REDACTED]")
            raise DeepgramUnavailableError(f"Deepgram connection error: {err_msg}") from exc


def build_stt_provider(settings: Settings, logger: StructuredLogger | None = None) -> SttProvider:
    """
    Factory that maps Settings to SttProvider.

    Rules:
      - STT_PROVIDER=fake -> FakeSttProvider (default; no credentials needed)
      - STT_PROVIDER=deepgram -> DeepgramSttProvider (key must be present,
        validated earlier by Settings.validate_startup())

    Provider-specific construction details must not leak into the route handler.
    """
    if settings.stt_provider == "deepgram":
        if not settings.deepgram_api_key:
            raise RuntimeError("DEEPGRAM_API_KEY is required when STT_PROVIDER=deepgram.")
        return DeepgramSttProvider(
            api_key=settings.deepgram_api_key,
            logger=logger,
            mip_opt_out=settings.deepgram_mip_opt_out,
        )
    return FakeSttProvider()
