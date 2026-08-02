from typing import TypedDict, Optional, Any
from langgraph.graph import StateGraph, END
from lib.db.factory import get_db_adapter, get_active_provider_config
from lib.validation.sql_validator import validate_and_cap_sql, build_allowlist
from lib.pipeline.dedup_check import check_for_cross_join_inflation
from lib.chart.selector import select_chart
from lib.llm.sql_generator import correct_sql
from lib.query_sources.resolver import QueryCandidate


class PipelineState(TypedDict, total=False):
    candidate: QueryCandidate
    schema_context: str
    current_sql: str
    validation_error: Optional[str]
    retried: bool
    result: Optional[Any]
    chart: Optional[Any]
    dedup_warning: Optional[str]
    failure_stage: Optional[str]
    failure_message: Optional[str]


def _validate_node(state: PipelineState) -> dict:
    adapter = get_db_adapter()
    provider_config = get_active_provider_config()
    schema = adapter.fetch_schema_snapshot()
    allowlist = build_allowlist(schema)

    validation = validate_and_cap_sql(
        state["current_sql"], adapter.validator_dialect, allowlist, provider_config["default_row_cap"]
    )
    if validation.ok and validation.sql:
        return {"current_sql": validation.sql, "validation_error": None}
    return {"validation_error": validation.error or "Validation failed."}


def _retry_node(state: PipelineState) -> dict:
    corrected = correct_sql(state["current_sql"], state.get("validation_error") or "", state["schema_context"])
    return {"current_sql": corrected.sql, "retried": True}


def _execute_node(state: PipelineState) -> dict:
    adapter = get_db_adapter()
    provider_config = get_active_provider_config()
    try:
        result = adapter.execute_select(state["current_sql"], provider_config["statement_timeout_ms"])
        return {"result": result}
    except Exception:
        return {
            "failure_stage": "execution",
            "failure_message": "The query could not be executed. Please try again or rephrase your question.",
        }


def _dedup_node(state: PipelineState) -> dict:
    if not state.get("result"):
        return {}
    check = check_for_cross_join_inflation(state["result"], expected_max_rows=None)
    return {"dedup_warning": check.message if check.suspicious_inflation else None}


def _chart_node(state: PipelineState) -> dict:
    if not state.get("result"):
        return {}
    return {"chart": select_chart(state["result"])}


def _route_after_validation(state: PipelineState) -> str:
    if not state.get("validation_error"):
        return "execute"
    if not state.get("retried") and state["candidate"].source == "llm_generated":
        return "retry"
    return END


def _route_after_execution(state: PipelineState) -> str:
    return END if state.get("failure_stage") else "dedup"


def build_pipeline_graph():
    """
    Why LangGraph instead of the hand-written orchestrator in
    lib/pipeline/guardrails.py:
      - Each checkpoint becomes an inspectable node, easier to unit test
        and trace (Langfuse can hook into LangGraph's per-node runs).
      - The retry-once rule becomes an explicit conditional edge instead of
        an if-statement buried in a function body.
      - Extending with the 4.2 clarification loop later is another
        conditional branch, not a separate code path.
    """
    graph = StateGraph(PipelineState)
    graph.add_node("validate", _validate_node)
    graph.add_node("retry", _retry_node)
    graph.add_node("execute", _execute_node)
    graph.add_node("dedup", _dedup_node)
    graph.add_node("chart", _chart_node)

    graph.set_entry_point("validate")
    graph.add_conditional_edges("validate", _route_after_validation)
    graph.add_edge("retry", "validate")
    graph.add_conditional_edges("execute", _route_after_execution)
    graph.add_edge("dedup", "chart")
    graph.add_edge("chart", END)

    return graph.compile()


def run_pipeline_graph(candidate: QueryCandidate, schema_context: str) -> PipelineState:
    app = build_pipeline_graph()
    return app.invoke({
        "candidate": candidate,
        "schema_context": schema_context,
        "current_sql": candidate.sql,
        "retried": False,
    })
