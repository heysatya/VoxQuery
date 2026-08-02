"""Executive Audio Briefing Service.

Synthesizes audio via Deepgram TTS, streams audio directly, and caches raw bytes
in Upstash Redis with a 24-hour TTL (no blob storage).
"""
from __future__ import annotations
import hashlib
import logging
import re
from typing import Any

from app.config import Settings
from app.core.tts import build_tts_provider
from app.models.contracts import AuthClaims
from app.warehouse.connector import WarehouseConnector
from app.services.briefing import generate_morning_briefing

logger = logging.getLogger("voxquery.services.briefing_audio")


def clean_text_for_tts(text: str) -> str:
    """Strips Markdown symbols, headers, and bullet formatting for natural TTS audio."""
    # Remove markdown bold/italics, backticks, hashes, and bullet markers
    cleaned = re.sub(r"[\*\_\`\#]", "", text)
    cleaned = re.sub(r"^\s*[\-\+]\s+", "", cleaned, flags=re.MULTILINE)
    return cleaned.strip()


async def get_or_generate_briefing_audio_bytes(
    claims: AuthClaims,
    settings: Settings,
    redis_client: Any | None = None,
    voice: str = "aura-asteria-en",
    warehouse: WarehouseConnector | None = None,
) -> tuple[bytes, str]:
    """
    Returns (audio_bytes, provider_type).
    Checks Redis cache for key briefing_audio:{tenant_id}:{date}:{voice}:{hash}.
    If cache miss, synthesizes via Deepgram TTS and caches raw bytes in Redis.
    """
    briefing = await generate_morning_briefing(
        claims.tenant_id,
        settings,
        user_name="Executive",
        warehouse=warehouse,
        snowflake_role=claims.snowflake_role,
        redis_client=redis_client,
    )
    raw_text = f"{briefing.greeting}. {briefing.summary_narrative}"
    text_to_speak = clean_text_for_tts(raw_text)

    hash_key = hashlib.sha256(text_to_speak.encode("utf-8")).hexdigest()[:12]
    cache_key = f"briefing_audio:{claims.tenant_id}:{briefing.date}:{voice}:{hash_key}"

    if redis_client:
        try:
            cached_audio = await redis_client.get(cache_key)
            if cached_audio:
                if isinstance(cached_audio, str):
                    cached_audio = cached_audio.encode("latin1")
                return cached_audio, settings.tts_provider
        except Exception as exc:
            logger.warning("Redis briefing audio cache fetch failed: %s", exc)

    tts_provider = build_tts_provider(settings)
    audio_chunks: list[bytes] = []
    async for chunk in tts_provider.stream_audio(text_to_speak):
        audio_chunks.append(chunk)

    full_audio = b"".join(audio_chunks)

    if redis_client and full_audio:
        try:
            await redis_client.setex(cache_key, 86400, full_audio)
        except Exception as exc:
            logger.warning("Redis briefing audio cache store failed: %s", exc)

    return full_audio, settings.tts_provider
