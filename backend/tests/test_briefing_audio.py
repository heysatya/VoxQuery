"""Tests for Executive Audio Briefing Service and Redis Byte Caching."""

from unittest.mock import AsyncMock
import pytest
from uuid import uuid4

from app.config import get_settings
from app.models.contracts import AuthClaims
from app.services.briefing_audio import get_or_generate_briefing_audio_bytes


@pytest.mark.asyncio
async def test_get_or_generate_briefing_audio_bytes_fake_tts():
    settings = get_settings()
    tenant_id = uuid4()
    user_id = uuid4()
    claims = AuthClaims(user_id=str(user_id), tenant_id=str(tenant_id), email="audio@test.com", role="admin", snowflake_role="ANALYST")

    audio_bytes, provider = await get_or_generate_briefing_audio_bytes(claims, settings)
    assert isinstance(audio_bytes, bytes)
    assert len(audio_bytes) > 0
    assert provider == settings.tts_provider


@pytest.mark.asyncio
async def test_get_or_generate_briefing_audio_bytes_redis_cache():
    settings = get_settings()
    tenant_id = uuid4()
    user_id = uuid4()
    claims = AuthClaims(user_id=str(user_id), tenant_id=str(tenant_id), email="audio@test.com", role="admin", snowflake_role="ANALYST")

    mock_redis = AsyncMock()
    mock_redis.get.side_effect = lambda key: b"\x01\x02\x03\x04" if "briefing_audio" in str(key) else None  # Cache hit for audio only

    audio_bytes, provider = await get_or_generate_briefing_audio_bytes(claims, settings, redis_client=mock_redis)
    assert audio_bytes == b"\x01\x02\x03\x04"
    assert mock_redis.get.call_count >= 1
