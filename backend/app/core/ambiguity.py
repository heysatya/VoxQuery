from __future__ import annotations

import re

from app.models.contracts import (
    AMBIGUITY_SEVERITY,
    AmbiguityDetectionResult,
    AmbiguitySignal,
    ResolvedEntity,
    SchemaChunk,
    SessionHistoryTurn,
)

GENERIC_METRICS = {"revenue", "sales", "bookings", "churn", "customers", "orders"}
RELATIVE_TIME_TERMS = {
    "today",
    "yesterday",
    "this month",
    "last month",
    "this quarter",
    "last quarter",
    "q1",
    "q2",
    "q3",
    "q4",
}
SCOPE_TERMS = {"top", "bottom", "best", "worst", "largest", "smallest", "highest", "lowest"}
PRONOUNS = {"it", "that", "those", "these", "them", "they", "this"}


def detect_ambiguity(
    submitted_text: str,
    schema_chunks: list[SchemaChunk],
    *,
    resolved_entities: dict[str, ResolvedEntity] | None = None,
    history: list[SessionHistoryTurn] | None = None,
) -> AmbiguityDetectionResult:
    resolved_entities = resolved_entities or {}
    history = history or []
    query = submitted_text.lower()
    tokens = set(re.findall(r"[a-z0-9_]+", query))
    signals: list[AmbiguitySignal] = []
    ambiguous_terms: list[str] = []

    metric_matches = _metric_matches(tokens, schema_chunks)
    if any(len(matches) >= 2 for matches in metric_matches.values()):
        signals.append(AmbiguitySignal.metric_ambiguity)
        ambiguous_terms.extend(
            term for term, matches in metric_matches.items() if len(matches) >= 2
        )

    entity_terms = _entity_collision_terms(tokens, schema_chunks)
    entity_terms = [
        term
        for term in entity_terms
        if not (term == "customer" and {"segment", "state", "city"} & tokens)
    ]
    if entity_terms:
        signals.append(AmbiguitySignal.entity_ambiguity)
        ambiguous_terms.extend(entity_terms)

    if _has_relative_time(query) and _date_column_count(schema_chunks) >= 2:
        signals.append(AmbiguitySignal.temporal_ambiguity)

    if tokens & SCOPE_TERMS and not any(token.isdigit() for token in tokens):
        signals.append(AmbiguitySignal.scope_ambiguity)

    if tokens & PRONOUNS and not history:
        signals.append(AmbiguitySignal.pronoun_reference_failure)

    if _mentions_multiple_unrelated_tables(tokens, schema_chunks):
        signals.append(AmbiguitySignal.missing_join_path)

    suppressed = _suppressed_signals(signals, query, resolved_entities)
    active = [signal for signal in signals if signal not in suppressed]
    active_sorted = _severity_sorted(active)
    return AmbiguityDetectionResult(
        signals_detected=active_sorted,
        signals_suppressed=_severity_sorted(suppressed),
        dominant_signal=active_sorted[0] if active_sorted else None,
        ambiguous_terms=sorted(set(ambiguous_terms)),
    )


def _metric_matches(
    tokens: set[str], schema_chunks: list[SchemaChunk]
) -> dict[str, list[SchemaChunk]]:
    matches: dict[str, list[SchemaChunk]] = {}
    for term in GENERIC_METRICS & tokens:
        if term == "revenue" and tokens & {"gross", "net", "recognized", "recognised"}:
            matches[term] = [
                chunk
                for chunk in schema_chunks
                if any(
                    qualifier in chunk.source_ref.lower() or qualifier in chunk.content.lower()
                    for qualifier in tokens & {"gross", "net", "recognized", "recognised"}
                )
            ][:1]
            continue
        matches[term] = [
            chunk
            for chunk in schema_chunks
            if term in chunk.content.lower() or term in chunk.source_ref.lower()
        ]
    return matches


STOP_WORDS = {
    "a",
    "an",
    "the",
    "in",
    "on",
    "at",
    "to",
    "for",
    "of",
    "and",
    "or",
    "is",
    "are",
    "show",
    "me",
    "what",
    "by",
    "with",
}


def _entity_collision_terms(tokens: set[str], schema_chunks: list[SchemaChunk]) -> list[str]:
    refs_by_term: dict[str, set[str]] = {}
    for token in tokens:
        if len(token) < 2 or token in STOP_WORDS:
            continue
        for chunk in schema_chunks:
            if token in chunk.source_ref.lower() or token in chunk.content.lower():
                refs_by_term.setdefault(token, set()).add(chunk.source_ref)
    return [
        term
        for term, refs in refs_by_term.items()
        if len(refs) >= 2 and term not in GENERIC_METRICS
    ]


def _has_relative_time(query: str) -> bool:
    return any(term in query for term in RELATIVE_TIME_TERMS)


def _date_column_count(schema_chunks: list[SchemaChunk]) -> int:
    return sum(
        1
        for chunk in schema_chunks
        if "date" in chunk.source_ref.lower()
        or "date" in chunk.content.lower()
        or "timestamp" in chunk.content.lower()
    )


def _mentions_multiple_unrelated_tables(tokens: set[str], schema_chunks: list[SchemaChunk]) -> bool:
    mentioned_tables = {
        chunk.table or chunk.source_ref.split(".")[0]
        for chunk in schema_chunks
        if any(
            token in chunk.source_ref.lower() or token in chunk.content.lower() for token in tokens
        )
    }
    has_join_context = any("join_path:" in chunk.content.lower() for chunk in schema_chunks)
    return len(mentioned_tables) >= 2 and not has_join_context and "by" in tokens


def _suppressed_signals(
    signals: list[AmbiguitySignal], query: str, resolved_entities: dict[str, ResolvedEntity]
) -> list[AmbiguitySignal]:
    if not resolved_entities:
        return []
    has_resolved_term = any(term.lower() in query for term in resolved_entities)
    if not has_resolved_term:
        return []
    suppressible = {
        AmbiguitySignal.metric_ambiguity,
        AmbiguitySignal.entity_ambiguity,
        AmbiguitySignal.temporal_ambiguity,
    }
    return [signal for signal in signals if signal in suppressible]


def _severity_sorted(signals: list[AmbiguitySignal]) -> list[AmbiguitySignal]:
    unique = set(signals)
    return [signal for signal in AMBIGUITY_SEVERITY if signal in unique]
