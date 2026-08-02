import json
import re
from dataclasses import dataclass
import anthropic

_client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env

_SQL_GEN_SYSTEM_PROMPT = """You generate a single read-only SQL SELECT statement to answer an executive's
question, using ONLY the schema context, business glossary, and join-path context provided.
Rules:
- Output ONLY valid JSON: {"sql": string, "confidence": number between 0 and 1}
- confidence should be LOW if the question is ambiguous, or references a term not in the glossary,
  or requires a join path not present in the provided context.
- Never invent table or column names not present in the schema context.
- Never write DDL or DML — SELECT only."""


@dataclass
class GeneratedSQL:
    sql: str
    confidence: float


def _extract_json(text: str) -> dict:
    cleaned = re.sub(r"```json|```", "", text).strip()
    return json.loads(cleaned)


def generate_sql(user_question: str, schema_context: str, conversation_history: str) -> GeneratedSQL:
    message = _client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=500,
        system=_SQL_GEN_SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": f"Schema context:\n{schema_context}\n\nConversation history:\n{conversation_history}\n\nQuestion: {user_question}",
            }
        ],
    )
    text = next((b.text for b in message.content if b.type == "text"), "{}")
    parsed = _extract_json(text)
    return GeneratedSQL(sql=parsed["sql"], confidence=parsed.get("confidence", 0.5))


def correct_sql(original_sql: str, validation_error: str, schema_context: str) -> GeneratedSQL:
    """
    One-shot retry on validation failure. Deliberately routed to Haiku —
    fixing a known parse/schema error given the exact error message is a
    narrower task than the original generation and doesn't need Sonnet.
    """
    message = _client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=500,
        system=_SQL_GEN_SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": f"Schema context:\n{schema_context}\n\nThis SQL failed validation:\n{original_sql}\n\nValidation error: {validation_error}\n\nFix it and return the same JSON format.",
            }
        ],
    )
    text = next((b.text for b in message.content if b.type == "text"), "{}")
    parsed = _extract_json(text)
    return GeneratedSQL(sql=parsed["sql"], confidence=parsed.get("confidence", 0.5))
