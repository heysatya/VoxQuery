from dataclasses import dataclass
from lib.db.types import QueryExecutionResult


@dataclass
class DedupCheckResult:
    suspicious_inflation: bool
    message: str | None = None


INFLATION_MULTIPLIER = 3  # generous — real cross-join blowups are usually 3x+, not 1.2x


def check_for_cross_join_inflation(
    result: QueryExecutionResult,
    expected_max_rows: int | None,
) -> DedupCheckResult:
    """
    Heuristic guardrail from 4.5: if a result set looks inflated by an
    implicit cross-join (e.g. joining order_items and order_payments
    directly, both of which fan out from orders, without careful join keys),
    flag it rather than silently returning inflated totals. Intentionally
    conservative — flags for user confirmation, does not auto-rewrite the query.
    """
    if not expected_max_rows:
        return DedupCheckResult(suspicious_inflation=False)

    if result.row_count > expected_max_rows * INFLATION_MULTIPLIER:
        return DedupCheckResult(
            suspicious_inflation=True,
            message=(
                "This result may contain duplicate rows from a multi-table join "
                "(e.g. an order with several items and several payment installments). "
                "Want me to re-run with DISTINCT?"
            ),
        )

    return DedupCheckResult(suspicious_inflation=False)
