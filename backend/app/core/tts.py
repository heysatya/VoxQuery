import logging
from collections.abc import AsyncGenerator
from typing import Protocol

import aiohttp

from app.config import Settings

DEEPGRAM_AURA_MODEL = "aura-asteria-en"
DEEPGRAM_AURA_URL = (
    "https://api.deepgram.com/v1/speak"
    f"?model={DEEPGRAM_AURA_MODEL}&encoding=linear16&sample_rate=16000&container=none"
)
DEEPGRAM_TTS_TIMEOUT = aiohttp.ClientTimeout(total=30, sock_connect=5, sock_read=10)


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
        mip_opt_out: bool = False,
    ) -> None:
        self.api_key = api_key
        self.logger = logger or logging.getLogger("voxquery.tts")
        self._mip_opt_out = mip_opt_out

    async def stream_audio(self, text: str) -> AsyncGenerator[bytes, None]:
        text = text.strip()
        if not text:
            return

        headers = {
            "Authorization": f"Token {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {"text": text}
        url = DEEPGRAM_AURA_URL + ("&mip_opt_out=true" if self._mip_opt_out else "")

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=DEEPGRAM_TTS_TIMEOUT,
                ) as response:
                    if response.status != 200:
                        body = await response.text()
                        if self.api_key in body:
                            body = body.replace(self.api_key, "[REDACTED]")
                        self.logger.error("Deepgram TTS error %d: %s", response.status, body)
                        raise TTSUnavailableError(f"Deepgram returned HTTP {response.status}")

                    yielded_audio = False
                    async for chunk in response.content.iter_chunked(4096):
                        if chunk:
                            yielded_audio = True
                            yield chunk

                    if not yielded_audio:
                        raise TTSUnavailableError("Deepgram returned an empty TTS stream")
        except TimeoutError as exc:
            raise TTSUnavailableError("Timed out waiting for Deepgram TTS") from exc
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
        return DeepgramTTSProvider(
            settings.deepgram_api_key,
            logger=logger,
            mip_opt_out=settings.deepgram_mip_opt_out,
        )
    return FakeTTSProvider(logger=logger)
