from app.config import Settings
from app.core.tts import (
    DEEPGRAM_AURA_MODEL,
    DEEPGRAM_AURA_URL,
    DeepgramTTSProvider,
    FakeTTSProvider,
    build_tts_provider,
)


def test_deepgram_aura_is_the_only_production_tts_model():
    assert DEEPGRAM_AURA_MODEL == "aura-asteria-en"
    assert "api.deepgram.com/v1/speak" in DEEPGRAM_AURA_URL
    assert f"model={DEEPGRAM_AURA_MODEL}" in DEEPGRAM_AURA_URL
    assert "encoding=linear16" in DEEPGRAM_AURA_URL
    assert "sample_rate=16000" in DEEPGRAM_AURA_URL
    assert "container=none" in DEEPGRAM_AURA_URL


def test_build_tts_provider_uses_deepgram_aura_when_configured():
    provider = build_tts_provider(
        Settings(APP_ENV="test", TTS_PROVIDER="deepgram", DEEPGRAM_API_KEY="test-key")
    )

    assert isinstance(provider, DeepgramTTSProvider)


def test_fake_tts_provider_remains_test_and_local_fallback():
    provider = build_tts_provider(Settings(APP_ENV="test", TTS_PROVIDER="fake"))

    assert isinstance(provider, FakeTTSProvider)


def test_deepgram_tts_provider_mip_opt_out_defaults_false():
    provider = DeepgramTTSProvider(api_key="sk-test")
    assert provider._mip_opt_out is False


def test_deepgram_tts_provider_mip_opt_out_can_be_enabled():
    provider = DeepgramTTSProvider(api_key="sk-test", mip_opt_out=True)
    assert provider._mip_opt_out is True


def test_build_tts_provider_wires_mip_opt_out_setting():
    provider = build_tts_provider(
        Settings(
            APP_ENV="test",
            TTS_PROVIDER="deepgram",
            DEEPGRAM_API_KEY="sk-test",
            DEEPGRAM_MIP_OPT_OUT=True,
        )
    )
    assert isinstance(provider, DeepgramTTSProvider)
    assert provider._mip_opt_out is True


import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class _MockAiohttpResponse:
    def __init__(self, status=200, chunks=None):
        self.status = status
        self._chunks = chunks or [b"\x00" * 1024]

    async def text(self):
        return ""

    @property
    def content(self):
        chunks = self._chunks

        class _Content:
            def iter_chunked(self, size):
                async def gen():
                    for c in chunks:
                        yield c

                return gen()

        return _Content()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


@pytest.mark.asyncio
async def test_deepgram_tts_provider_url_omits_mip_opt_out_by_default():
    """Verifies the actual HTTP request URL used by stream_audio, not just
    constructor state — confirms the query param is genuinely absent, matching
    the STT-side verification of the same setting."""
    captured = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        return _MockAiohttpResponse(status=200)

    mock_session = MagicMock()
    mock_session.post = fake_post
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    provider = DeepgramTTSProvider(api_key="sk-test")
    with patch("aiohttp.ClientSession", return_value=mock_session):
        async for _ in provider.stream_audio("hello world"):
            pass

    assert "mip_opt_out" not in captured["url"]


@pytest.mark.asyncio
async def test_deepgram_tts_provider_url_includes_mip_opt_out_when_enabled():
    captured = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        return _MockAiohttpResponse(status=200)

    mock_session = MagicMock()
    mock_session.post = fake_post
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    provider = DeepgramTTSProvider(api_key="sk-test", mip_opt_out=True)
    with patch("aiohttp.ClientSession", return_value=mock_session):
        async for _ in provider.stream_audio("hello world"):
            pass

    assert "mip_opt_out=true" in captured["url"]
