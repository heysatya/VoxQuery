import logging
from collections.abc import AsyncGenerator
from typing import Protocol

import aiohttp

from app.config import Settings

DEEPGRAM_AURA_MODEL = "aura-asteria-en"
DEEPGRAM_AURA_URL = (
    "https://api.deepgram.com/v1/speak"
    f"?model={DEEPGRAM_AURA_MODEL}&encoding=linear16&sample_rate=16000"
)


class TTSUnavailableError(Exception):
    """Raised when the TTS provider fails to connect or returns an error."""
    pass


class TTSProvider(Protocol):
    async def stream_audio(self, text: str) -> AsyncGenerator[bytes, None]:
        """Yields raw PCM audio chunks."""
        yield b""


class FakeTTSProvider:
    def __init__(self, logger: logging.LoggerAdapter | logging.Logger | None = None) -> None:
        self.logger = logger or logging.getLogger("voxquery.tts")

    async def stream_audio(self, text: str) -> AsyncGenerator[bytes, None]:
        """Yields a fake PCM stream."""
        self.logger.info("Fake TTS: starting playback for text length %d", len(text))
        # Yield a few chunks of silence (0x00) for 16-bit linear PCM
        for _ in range(5):
            yield b"\x00" * 1024


class DeepgramTTSProvider:
    def __init__(
        self,
        api_key: str,
        logger: logging.LoggerAdapter | logging.Logger | None = None,
    ) -> None:
        self.api_key = api_key
        self.logger = logger or logging.getLogger("voxquery.tts")

    async def stream_audio(self, text: str) -> AsyncGenerator[bytes, None]:
        headers = {
            "Authorization": f"Token {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {"text": text}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(DEEPGRAM_AURA_URL, headers=headers, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as response:
                    if response.status != 200:
                        body = await response.text()
                        if self.api_key in body:
                            body = body.replace(self.api_key, "[REDACTED]")
                        self.logger.error("Deepgram TTS error %d: %s", response.status, body)
                        raise TTSUnavailableError(f"Deepgram returned HTTP {response.status}")
                    
                    async for chunk in response.content.iter_chunked(4096):
                        yield chunk
        except aiohttp.ClientError as exc:
            err_msg = str(exc)
            if self.api_key in err_msg:
                err_msg = err_msg.replace(self.api_key, "[REDACTED]")
            self.logger.error("Deepgram TTS network error: %s", err_msg)
            raise TTSUnavailableError("Network error connecting to Deepgram TTS") from exc


def build_tts_provider(
    settings: Settings, logger: logging.LoggerAdapter | logging.Logger | None = None
) -> TTSProvider:
    if settings.tts_provider == "deepgram":
        if not settings.deepgram_api_key:
            raise RuntimeError("DEEPGRAM_API_KEY must be set when TTS_PROVIDER=deepgram")
        return DeepgramTTSProvider(settings.deepgram_api_key, logger=logger)
    return FakeTTSProvider(logger=logger)
