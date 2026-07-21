import hashlib
import re

from app.models.contracts import ConfidenceTier, ResultPayload, ResultTrust, TurnRecord


def confidence_reasons_for_turn(turn: TurnRecord) -> list[str]:
    reasons: list[str] = []
    latest_attempt = turn.attempts[-1] if turn.attempts else None
    evidence = latest_attempt.confidence_evidence if latest_attempt else None

    if turn.result_warnings:
        reasons.extend(warning.message for warning in turn.result_warnings)
    if evidence:
        if evidence.retrieval_score < 0.7:
            reasons.append("Schema match was weaker than usual.")
        if evidence.ambiguity_signals:
            signal_descriptions = {
                "entity_ambiguity": "unclear which specific product, company, or entity you meant",
                "metric_ambiguity": "unclear exactly how to calculate the requested metric",
                "missing_join_path": "unclear how to connect the required data tables",
                "pronoun_reference_failure": "unclear what 'it' or 'they' referred to",
                "temporal_ambiguity": "unclear what time range or date you were asking about",
                "scope_ambiguity": "unclear how broadly to apply your filters",
            }
            signals = [signal_descriptions.get(s.value, s.value.replace("_", " ")) for s in evidence.ambiguity_signals]
            
            if len(signals) == 1:
                reasons.append(f"It was {signals[0]}.")
            else:
                joined_signals = ", ".join(signals[:-1]) + ", and " + signals[-1]
                reasons.append(f"It was {joined_signals}.")
                
        if not evidence.validation_outcome:
            reasons.append("The first generated SQL needed validation repair.")
        if "llm_self_confidence" in evidence.inputs_absent:
            reasons.append("LLM self-confidence was not available for this answer.")
    if not reasons and turn.confidence_tier == ConfidenceTier.medium:
        reasons.append("Some assumptions were needed to answer this question.")
    if not reasons and turn.confidence_tier == ConfidenceTier.low:
        reasons.append("Multiple assumptions were needed to answer this question.")
    if not reasons and turn.confidence_tier == ConfidenceTier.high:
        reasons.append("Schema retrieval, SQL validation, and execution checks passed.")

    return _dedupe(reasons)[:3]


def data_sources_for_sql(sql: str) -> list[str]:
    matches = re.findall(r"(?:FROM|JOIN)\s+([a-zA-Z_][a-zA-Z0-9_.]*)", sql, flags=re.IGNORECASE)
    return _dedupe(match.lower() for match in matches)


def build_result_trust(turn: TurnRecord, result: ResultPayload) -> ResultTrust:
    latest_attempt = turn.attempts[-1] if turn.attempts else None
    evidence = latest_attempt.confidence_evidence if latest_attempt else None
    sql_hash = evidence.sql_hash if evidence else _hash_sql(turn.generated_sql)

    return ResultTrust(
        confidence_tier=turn.confidence_tier,
        confidence_reasons=confidence_reasons_for_turn(turn),
        row_count=result.row_count,
        warning_count=len(turn.result_warnings),
        generated_sql_present=bool(turn.generated_sql),
        semantic_columns_present=bool(result.semantic_columns),
        execution_time_ms=turn.latency_ms,
        data_sources=data_sources_for_sql(turn.generated_sql),
        sql_hash=sql_hash,
        data_freshness_note="Served from cache" if turn.from_cache else "Live warehouse query",
    )


def derive_proactive_questions(turn: TurnRecord, result: ResultPayload) -> list[str]:
    if result.row_count == 0:
        return ["Broaden the filters", "Show recent available data", "Try a different segment"]

    columns = result.semantic_columns or []
    dimensions = [column.display_name for column in columns if column.role in {"dimension", "time"}]
    metrics = [column.display_name for column in columns if column.role == "metric"]
    sources = data_sources_for_sql(turn.generated_sql)

    suggestions: list[str] = []
    if dimensions:
        suggestions.append(f"Break this down by {dimensions[0]}")
    if metrics:
        suggestions.append(f"Show the trend for {metrics[0]}")
    if sources:
        suggestions.append(f"Compare this across {sources[0]}")
    if turn.confidence_tier in {ConfidenceTier.medium, ConfidenceTier.low}:
        suggestions.append("Show the assumptions behind this answer")
    suggestions.append("Compare this with the previous period")

    return _dedupe(suggestions)[:3]


def _hash_sql(sql: str) -> str | None:
    if not sql:
        return None
    return hashlib.sha256(sql.encode()).hexdigest()


def _dedupe(values) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        text = str(value).strip()
        key = text.casefold()
        if text and key not in seen:
            deduped.append(text)
            seen.add(key)
    return deduped
