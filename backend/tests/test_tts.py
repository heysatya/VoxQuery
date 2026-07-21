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
