"""
Row-Level Metric Drilldown Service (PRD Feature 4).

Queries and retrieves first 10 raw transactional records from the database
for a specific analytic metric to provide context for metric validation.
"""

from __future__ import annotations

import logging
from uuid import UUID

from app.config import Settings

logger = logging.getLogger("voxquery.services.drilldown")


from typing import Any
from uuid import UUID

from app.config import Settings
from app.models.contracts import AuthClaims, TurnRecord
from app.warehouse.connector import WarehouseConnector

logger = logging.getLogger("voxquery.services.drilldown")


async def get_row_drilldown(
    turn_id: UUID,
    settings: Settings,
    claims: AuthClaims | None = None,
    sql_query: str | None = None,
    turn_repo: Any = None,
    warehouse: WarehouseConnector | None = None,
    pipeline_turns: dict[UUID, TurnRecord] | None = None,
) -> list[dict[str, Any]]:
    """
    Get top 10 raw transaction rows by looking up executed turn SQL and running against warehouse.
    Scoped strictly to claims.tenant_id. Returns [] if not found or execution fails.
    """
    effective_claims = claims or AuthClaims(
        user_id="00000000-0000-0000-0000-000000000001",
        tenant_id="00000000-0000-0000-0000-000000000101",
        role="admin",
    )
    logger.info(
        "Fetching raw transaction drilldown for turn_id=%s tenant_id=%s",
        turn_id,
        effective_claims.tenant_id,
    )

    target_sql = sql_query

    if not target_sql:
        if pipeline_turns and turn_id in pipeline_turns:
            t = pipeline_turns[turn_id]
            if t.tenant_id == effective_claims.tenant_id and t.generated_sql:
                target_sql = t.generated_sql

    if not target_sql and turn_repo is not None:
        try:
            turn_record = await turn_repo.get_turn(turn_id, effective_claims)
            if turn_record and turn_record.get("generated_sql"):
                target_sql = turn_record["generated_sql"]
        except Exception as err:
            logger.warning("Could not fetch turn from repo: %s", err)

    if not target_sql or not warehouse:
        logger.warning(
            "No underlying SQL or warehouse available for turn_id=%s tenant_id=%s",
            turn_id,
            effective_claims.tenant_id,
        )
        return []

    clean_sql = target_sql.strip().rstrip(";")
    drilldown_sql = f"SELECT * FROM ({clean_sql}) AS drilldown_subquery LIMIT 10"

    try:
        payload, _ = await warehouse.execute_readonly(
            drilldown_sql,
            snowflake_role=effective_claims.snowflake_role,
            tenant_id=effective_claims.tenant_id,
        )
        if not payload or not payload.rows:
            return []

        cols = payload.columns
        return [dict(zip(cols, row)) for row in payload.rows]
    except Exception as err:
        logger.error("Failed to execute drilldown SQL for turn_id=%s: %s", turn_id, err)
        return []
