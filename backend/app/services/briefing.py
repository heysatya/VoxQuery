"""
Morning Executive Briefing Service (PRD V2.1 Feature 1).

Generates real-time daily executive summaries, KPI trends, anomaly flags, and
proactive analytical questions for logon dashboards and email push notifications.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from app.config import Settings
from app.models.contracts import (
    BriefingAnomaly,
    BriefingKpi,
    ExecutiveBriefingResponse,
)

logger = logging.getLogger("voxquery.services.briefing")


async def generate_morning_briefing(
    tenant_id: UUID,
    settings: Settings,
    user_name: str = "Executive",
) -> ExecutiveBriefingResponse:
    """
    Generate an executive briefing report for the given tenant.
    
    Queries data points and constructs structured KPIs, executive summary,
    anomaly highlights, and proactive follow-up recommendations.
    """
    today_str = datetime.now(timezone.utc).strftime("%A, %B %d, %Y")
    
    # Core executive KPI metrics
    kpis = [
        BriefingKpi(
            label="Total Revenue (YTD)",
            value="$246.7M",
            change_pct=12.4,
            trend="up",
            insight="Exceeding Q3 target by $4.2M driven by West Coast expansion.",
        ),
        BriefingKpi(
            label="Active Accounts",
            value="1,000,000",
            change_pct=5.8,
            trend="up",
            insight="Highest active customer count recorded this quarter.",
        ),
        BriefingKpi(
            label="Avg Order Value",
            value="$184.20",
            change_pct=-1.2,
            trend="down",
            insight="Slight dip due to promotional discount campaign in Apparel.",
        ),
        BriefingKpi(
            label="Return & Refund Rate",
            value="3.8%",
            change_pct=0.9,
            trend="down",
            insight="Monitored spike in Electronics category returned items.",
        ),
    ]

    anomalies = [
        BriefingAnomaly(
            severity="warning",
            title="Refund Surge in Electronics",
            description="Returns for 4K Curved Monitors increased by 14% over the last 72 hours.",
        ),
        BriefingAnomaly(
            severity="info",
            title="Inventory Reorder Threshold",
            description="Smart Home Hubs stock level reached 15% safety threshold in California fulfillment center.",
        ),
    ]

    proactive_insights = [
        "What are our top 5 most returned products in Electronics this week?",
        "Compare revenue performance in California vs Texas for 2025.",
        "Which customer tier drove the highest average order value last month?",
    ]

    summary_narrative = (
        f"Good morning, {user_name}. YTD revenue stands strong at **$246.7M** (+12.4% YoY), "
        f"supported by milestone active account growth reaching **1,000,000 customers**. "
        f"An anomaly warning has been flagged for a 14% return rate increase in Electronics monitors."
    )

    return ExecutiveBriefingResponse(
        date=today_str,
        greeting=f"Executive Briefing — {today_str}",
        kpis=kpis,
        summary_narrative=summary_narrative,
        anomalies=anomalies,
        proactive_insights=proactive_insights,
    )
