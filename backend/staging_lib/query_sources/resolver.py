import json
import os
from dataclasses import dataclass
from lib.db.factory import get_query_source_config


@dataclass
class QueryCandidate:
    sql: str
    source: str  # "llm_generated" | "rag_retrieved" | "predetermined_file" | "external_system"
    label: str | None = None
    confidence: float | None = None


@dataclass
class PredeterminedQueryEntry:
    id: str
    label: str
    sql: str
    description: str | None = None


class QuerySourceResolver:
    """
    Every candidate — however it arrived — funnels through this same shape,
    and every candidate goes through the SAME validator/executor pipeline
    afterward. "Predetermined" or "admin-provided" is not a bypass; it just
    means the confidence check in 4.2 is skipped since there's no LLM guess
    to be uncertain about.
    """

    def __init__(self):
        self._predetermined_cache: list[PredeterminedQueryEntry] | None = None

    def from_llm(self, sql: str, confidence: float) -> QueryCandidate:
        """Path A: SQL Claude generated fresh for this turn (4.5's normal path)."""
        return QueryCandidate(sql=sql, source="llm_generated", confidence=confidence)

    def from_rag_retrieval(self, sql: str, chunk_label: str) -> QueryCandidate:
        """Path B: a query the 4.4 RAG layer surfaced directly (e.g. a
        top-200 QUERY_HISTORY match or a close admin sample query)."""
        return QueryCandidate(sql=sql, source="rag_retrieved", label=chunk_label)

    def load_predetermined_queries(self) -> list[PredeterminedQueryEntry]:
        """Path C: a fixed, admin-curated list of vetted queries."""
        if self._predetermined_cache is not None:
            return self._predetermined_cache

        config = get_query_source_config()
        if not config.get("accept_predetermined_file"):
            return []

        file_path = config["predetermined_queries_path"]
        if not os.path.exists(file_path):
            return []

        with open(file_path) as f:
            raw = json.load(f)
        self._predetermined_cache = [PredeterminedQueryEntry(**entry) for entry in raw]
        return self._predetermined_cache

    def from_predetermined_id(self, query_id: str) -> QueryCandidate | None:
        entry = next((q for q in self.load_predetermined_queries() if q.id == query_id), None)
        if not entry:
            return None
        return QueryCandidate(sql=entry.sql, source="predetermined_file", label=entry.label)

    def from_external_system(self, sql: str, system_label: str) -> QueryCandidate:
        """Path D: a query handed in by an external system directly."""
        return QueryCandidate(sql=sql, source="external_system", label=system_label)
