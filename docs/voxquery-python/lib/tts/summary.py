import base64
import json
from dataclasses import dataclass
import anthropic
from openai import OpenAI
from lib.db.types import QueryExecutionResult

_anthropic_client = anthropic.Anthropic()
_openai_client = OpenAI()


@dataclass
class TTSOutput:
    summary_text: str
    audio_base64: str | None = None  # None if TTS generation failed — fails silently per 4.7


def _generate_summary_text(user_question: str, result: QueryExecutionResult) -> str:
    """Haiku, not Sonnet — summarizing a result set into 1-3 sentences is a
    narrow templated task and doesn't need the larger model."""
    sample = json.dumps(result.rows[:20], default=str)
    message = _anthropic_client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=150,
        system=(
            "Write a 1-3 sentence spoken summary of this query result, highlighting the key insight. "
            "Plain conversational language, no markdown, no numbers read out to excessive precision."
        ),
        messages=[{"role": "user", "content": f"Question: {user_question}\n\nResult sample: {sample}"}],
    )
    return next((b.text for b in message.content if b.type == "text"), "")


def generate_tts_summary(user_question: str, result: QueryExecutionResult) -> TTSOutput:
    summary_text = _generate_summary_text(user_question, result)

    try:
        speech = _openai_client.audio.speech.create(model="tts-1", voice="alloy", input=summary_text)
        audio_bytes = speech.read()
        return TTSOutput(summary_text=summary_text, audio_base64=base64.b64encode(audio_bytes).decode("utf-8"))
    except Exception:
        # Per 4.7: if TTS generation fails, show the text summary silently — no error surfaced.
        return TTSOutput(summary_text=summary_text, audio_base64=None)
