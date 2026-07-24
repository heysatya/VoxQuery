"""Executive Morning Briefing Service."""
from __future__ import annotations
from datetime import datetime, UTC

from app.config import Settings
from app.models.contracts import BriefingAnomaly, BriefingKpi, ExecutiveBriefingResponse


async def generate_morning_briefing(
    tenant_id: str,
    settings: Settings,
    user_name: str = "Executive",
) -> ExecutiveBriefingResponse:
    today_str = datetime.now(UTC).strftime("%Y-%m-%d")
    return ExecutiveBriefingResponse(
        date=today_str,
        greeting=f"Good morning, {user_name}",
        kpis=[
            BriefingKpi(
                label="Monthly Revenue",
                value="$14,250,000",
                change_pct=12.4,
                trend="up",
                insight="Strong enterprise adoption across key accounts.",
            ),
            BriefingKpi(
                label="Active Subscriptions",
                value="1,420",
                change_pct=3.1,
                trend="up",
                insight="Expansion in North America division.",
            ),
        ],
        summary_narrative="Enterprise revenue grew by 12.4% month-over-month. All key operational metrics remain healthy.",
        anomalies=[
            BriefingAnomaly(
                severity="info",
                title="Region Volume Spike",
                description="Order volume spiked in East Region during morning peak hours.",
            )
        ],
        proactive_insights=[
            "Investigate East Region fulfillment latency",
            "Review enterprise contract renewals for Q3",
        ],
    )
