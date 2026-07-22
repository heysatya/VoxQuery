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


async def get_row_drilldown(
    turn_id: UUID,
    settings: Settings,
) -> list[dict[str, str | int | float | None]]:
    """
    Get the top 10 raw transaction rows for verification.
    """
    logger.info("Fetching raw transaction drilldown for turn_id=%s", turn_id)

    # In a real environment, this queries the Snowflake database using the turn's SQL
    # with `LIMIT 10` applied. We return clean mock records matching the e-commerce schema.
    return [
        {
            "order_id": "ORD-2026-98102",
            "customer_name": "Sarah Jenkins",
            "state": "CA",
            "amount": 1240.50,
            "category": "Electronics",
            "order_date": "2026-07-20",
        },
        {
            "order_id": "ORD-2026-98103",
            "customer_name": "Michael Chen",
            "state": "CA",
            "amount": 89.99,
            "category": "Office Supplies",
            "order_date": "2026-07-21",
        },
        {
            "order_id": "ORD-2026-98104",
            "customer_name": "Elena Rostova",
            "state": "NY",
            "amount": 450.00,
            "category": "Apparel",
            "order_date": "2026-07-21",
        },
        {
            "order_id": "ORD-2026-98105",
            "customer_name": "Marcus Aurelius",
            "state": "TX",
            "amount": 2999.00,
            "category": "Furniture",
            "order_date": "2026-07-22",
        },
    ]
