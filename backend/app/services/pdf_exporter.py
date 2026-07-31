"""Executive PDF Exporter Service.

Renders server-side PDF document from WeasyPrint and Jinja2 templates.
"""
from __future__ import annotations
from datetime import datetime, UTC
from pathlib import Path
import logging
import asyncio
from jinja2 import Environment, FileSystemLoader

from app.models.contracts import ExecutiveBriefingResponse

logger = logging.getLogger("voxquery.services.pdf_exporter")

TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "templates" / "pdf"
env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)))


async def generate_briefing_pdf(briefing: ExecutiveBriefingResponse, tenant_name: str = "Default Tenant") -> bytes:
    """Renders an ExecutiveBriefingResponse into valid PDF bytes."""
    template = env.get_template("briefing_report.html.j2")
    html_str = template.render(
        briefing=briefing,
        tenant_name=tenant_name,
        generated_at=datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
    )

    try:
        from weasyprint import HTML
        return await asyncio.to_thread(lambda: HTML(string=html_str).write_pdf())
    except Exception as exc:
        logger.error("WeasyPrint PDF generation failed: %s", exc)
        raise RuntimeError(f"PDF generation unavailable: {exc}") from exc
