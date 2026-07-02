from app.config import get_settings
from app.llm.adapter import LlmAdapter, SqlGenerationResult
from app.services.providers import clarification_options_for_signal, metric_column


class FakeClaudeAdapter(LlmAdapter):
    """Credential-free local stand-in for the canonical Claude adapter."""

    model_name = get_settings().canonical_sql_model

    async def generate_sql(self, submitted_text: str, *, resolved_metric: str | None = None) -> SqlGenerationResult:
        metric = metric_column(resolved_metric or submitted_text)
        confidence = 0.87 if resolved_metric or "revenue" not in submitted_text.lower() else 0.58
        expression = (
            "order_items.price + order_items.freight_value"
            if metric == "gross_revenue"
            else "order_items.price * (1 - order_items.discount_rate) + order_items.freight_value"
        )
        return SqlGenerationResult(
            sql=(
                f"SELECT customers.customer_segment, SUM({expression}) AS total_{metric} "
                "FROM order_items "
                "JOIN orders ON order_items.order_id = orders.order_id "
                "JOIN customers ON orders.customer_id = customers.customer_id "
                "WHERE orders.order_status = 'delivered' "
                "GROUP BY customers.customer_segment "
                f"ORDER BY total_{metric} DESC "
                "LIMIT 100"
            ),
            llm_self_confidence=confidence,
            validation_passed=True,
        )

    async def generate_clarification(self, dominant_signal: str) -> tuple[str, list[str]]:
        return clarification_options_for_signal()
