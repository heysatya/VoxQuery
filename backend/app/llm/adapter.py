from __future__ import annotations

from abc import ABC, abstractmethod


class SqlGenerationResult:
    def __init__(self, sql: str, llm_self_confidence: float, validation_passed: bool) -> None:
        self.sql = sql
        self.llm_self_confidence = llm_self_confidence
        self.validation_passed = validation_passed


class LlmAdapter(ABC):
    @abstractmethod
    async def generate_sql(self, submitted_text: str, *, resolved_metric: str | None = None) -> SqlGenerationResult:
        """Generate SQL without exposing provider-specific prompt mechanics upstream."""

    @abstractmethod
    async def generate_clarification(self, dominant_signal: str) -> tuple[str, list[str]]:
        """Return exactly one clarification question and 2-4 options."""
