from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any
from dataclasses import dataclass


from app.models.contracts import ResultShape, SchemaChunk, SessionHistoryTurn


@dataclass
class SqlGenerationResult:
    sql: str
    llm_self_confidence: float | None = None
    validation_passed: bool = True
    validation_error: str | None = None


class LlmAdapter(ABC):
    @abstractmethod
    async def generate_sql(
        self,
        submitted_text: str,
        schema_chunks: list[SchemaChunk],
        conversation_history: list[SessionHistoryTurn],
        *,
        resolved_entities: dict[str, Any] | None = None,
        feedback: str | None = None,
        previous_sql: str | None = None,
    ) -> SqlGenerationResult:
        """Generate SQL without exposing provider-specific prompt mechanics upstream."""

    @abstractmethod
    async def generate_clarification(
        self, dominant_signal: Any, user_input: str = ""
    ) -> tuple[str, list[str]]:
        """Return exactly one clarification question and 2-4 options."""


class Storyteller(ABC):
    @abstractmethod
    async def summarize(self, result_shape: ResultShape, user_query: str) -> str:
        """Generate a 1-3 sentence narrative (Headline, Driver, Implication)."""

    @abstractmethod
    async def generate_proactive_questions(
        self, result_shape: ResultShape, user_query: str
    ) -> list[str]:
        """Generate 3 proactive follow-up questions for the user based on the result shape and context."""
