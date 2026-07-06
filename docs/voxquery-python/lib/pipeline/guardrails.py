from dataclasses import dataclass
from lib.db.factory import get_db_adapter, get_active_provider_config
from lib.db.types import QueryExecutionResult
from lib.validation.sql_validator import validate_and_cap_sql, build_allowlist
from lib.pipeline.dedup_check import check_for_cross_join_inflation
from lib.chart.selector import select_chart, ChartSelection
from lib.llm.sql_generator import correct_sql
from lib.query_sources.resolver import QueryCandidate


@dataclass
class PipelineSuccess:
    ok: bool
    sql: str
    source: str
    result: QueryExecutionResult
    chart: ChartSelection
    dedup_warning: str | None = None


@dataclass
class PipelineFailure:
    ok: bool
    stage: str  # "validation" | "execution"
    error: str


def run_query_pipeline(candidate: QueryCandidate, schema_context_for_retry: str):
    """
    Checkpoints, in order:
      1. sqlglot validation (SELECT-only, known tables/columns, row cap)
         -> on failure: ONE retry via Haiku error-correction, then give up
      2. execution against whichever DB adapter is active in config
      3. post-execution dedup/cross-join anomaly check
      4. rule-based chart selection

    Deliberately source-agnostic: an LLM-generated query, a RAG-retrieved
    historical query, and an admin's predetermined query all pass through
    the exact same four checkpoints. "Trusted source" is not a bypass here.
    """
    adapter = get_db_adapter()
    provider_config = get_active_provider_config()
    schema = adapter.fetch_schema_snapshot()
    allowlist = build_allowlist(schema)

    validation = validate_and_cap_sql(candidate.sql, adapter.validator_dialect, allowlist, provider_config["default_row_cap"])

    # Single retry, only for LLM-generated candidates.
    if not validation.ok and candidate.source == "llm_generated":
        corrected = correct_sql(candidate.sql, validation.error or "unknown error", schema_context_for_retry)
        validation = validate_and_cap_sql(corrected.sql, adapter.validator_dialect, allowlist, provider_config["default_row_cap"])

    if not validation.ok or not validation.sql:
        return PipelineFailure(ok=False, stage="validation", error=validation.error or "Query failed validation.")

    try:
        result = adapter.execute_select(validation.sql, provider_config["statement_timeout_ms"])
    except Exception:
        return PipelineFailure(
            ok=False,
            stage="execution",
            error="The query could not be executed against the database. Please try again or rephrase your question.",
        )

    dedup_check = check_for_cross_join_inflation(result, expected_max_rows=None)  # wire up expected_max_rows if precomputed
    chart = select_chart(result)

    return PipelineSuccess(
        ok=True,
        sql=validation.sql,
        source=candidate.source,
        result=result,
        chart=chart,
        dedup_warning=dedup_check.message if dedup_check.suspicious_inflation else None,
    )
