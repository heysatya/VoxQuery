"""Tests for 1-Click Executive PDF Exporter."""

import pytest
from app.models.contracts import BriefingAnomaly, BriefingKpi, ExecutiveBriefingResponse
from app.services.pdf_exporter import generate_briefing_pdf


@pytest.mark.asyncio
async def test_generate_briefing_pdf_output():
    briefing = ExecutiveBriefingResponse(
        date="2026-07-23",
        greeting="Good morning, Executive",
        kpis=[
            BriefingKpi(
                label="Monthly Revenue",
                value="$14,250,000",
                change_pct=12.4,
                trend="up",
                insight="Strong enterprise adoption",
            )
        ],
        summary_narrative="Enterprise revenue grew by 12.4% month-over-month.",
        anomalies=[
            BriefingAnomaly(
                severity="critical",
                title="Return Rate Spike",
                description="Return rate increased by 5.2% in West Region",
            )
        ],
        proactive_insights=["Investigate West Region fulfillment latency"],
    )

    try:
        pdf_bytes = await generate_briefing_pdf(briefing, tenant_name="Acme Corp")
        assert isinstance(pdf_bytes, bytes)
        assert len(pdf_bytes) > 0
        # PDF header signature
        assert pdf_bytes.startswith(b"%PDF")
    except RuntimeError as exc:
        if "PDF generation unavailable" in str(exc):
            pytest.skip("WeasyPrint system libraries (Pango/Cairo) not installed on local host")
        raise
