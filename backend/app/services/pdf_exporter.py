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


def _escape_pdf_text(text: str) -> str:
    if not text:
        return ""
    ascii_text = text.encode("ascii", errors="replace").decode("ascii")
    return ascii_text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _wrap_text(text: str, max_chars: int = 80) -> list[str]:
    if not text:
        return []
    lines: list[str] = []
    for raw_line in text.split("\n"):
        raw_line = raw_line.strip()
        while len(raw_line) > max_chars:
            split_idx = raw_line.rfind(" ", 0, max_chars)
            if split_idx <= 0:
                split_idx = max_chars
            lines.append(raw_line[:split_idx])
            raw_line = raw_line[split_idx:].strip()
        if raw_line:
            lines.append(raw_line)
    return lines


def _generate_fallback_pdf(
    briefing: ExecutiveBriefingResponse, tenant_name: str, generated_at: str
) -> bytes:
    """Pure Python fallback PDF generator when WeasyPrint / system GTK DLLs are unavailable."""
    commands: list[str] = []
    y = 790

    def add_line(font: str, size: int, text: str, y_pos: int, x_pos: int = 50):
        commands.append("BT")
        commands.append(f"/{font} {size} Tf")
        commands.append(f"{x_pos} {y_pos} Td")
        commands.append(f"({_escape_pdf_text(text)}) Tj")
        commands.append("ET")

    # Document Header
    add_line("F1", 18, "VoxQuery Morning Briefing", y)
    y -= 22
    subtitle = (
        f"Date: {briefing.date or '—'} | Tenant: {tenant_name or '—'} | Generated: {generated_at}"
    )
    add_line("F2", 9, subtitle, y)
    y -= 30

    # Executive Summary
    add_line("F1", 12, "Executive Summary:", y)
    y -= 16
    summary_lines = _wrap_text(briefing.summary_narrative or "No executive summary available.", 85)
    for line in summary_lines:
        if y < 60:
            break
        add_line("F2", 10, line, y)
        y -= 14
    y -= 15

    # Key Performance Indicators
    if briefing.kpis and y >= 100:
        add_line("F1", 12, "Key Performance Indicators:", y)
        y -= 18
        for kpi in briefing.kpis:
            if y < 60:
                break
            change_str = f"{kpi.change_pct}%" if kpi.change_pct is not None else "—"
            trend_str = (kpi.trend or "—").upper()
            kpi_line = (
                f"* {kpi.label or '—'}: {kpi.value} (Change: {change_str}, Trend: {trend_str})"
            )
            add_line("F1", 10, kpi_line, y)
            y -= 14
            if kpi.insight:
                insight_lines = _wrap_text(f"  Insight: {kpi.insight}", 80)
                for il in insight_lines:
                    if y < 60:
                        break
                    add_line("F2", 9, il, y, x_pos=60)
                    y -= 12
            y -= 4
        y -= 10

    # Recommended Actions
    if briefing.proactive_insights and y >= 80:
        add_line("F1", 12, "Recommended Proactive Actions:", y)
        y -= 16
        for action in briefing.proactive_insights:
            if y < 60:
                break
            action_lines = _wrap_text(f"- {action}", 80)
            for al in action_lines:
                if y < 60:
                    break
                add_line("F2", 10, al, y)
                y -= 14
        y -= 10

    # Anomalies
    if briefing.anomalies and y >= 80:
        add_line("F1", 12, "Detected Statistical Outliers:", y)
        y -= 16
        for anom in briefing.anomalies:
            if y < 60:
                break
            sev = (anom.severity or "info").upper()
            anom_text = f"[{sev}] {anom.title or 'Untitled'}: {anom.description or ''}"
            anom_lines = _wrap_text(anom_text, 80)
            for al in anom_lines:
                if y < 60:
                    break
                add_line("F2", 9, al, y)
                y -= 12

    stream_content = "\n".join(commands).encode("latin1", errors="replace")

    body: list[bytes] = [b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"]
    offsets: list[int] = []

    obj1 = b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
    obj2 = b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
    obj3 = b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R /F2 5 0 R >> >> /Contents 6 0 R >>\nendobj\n"
    obj4 = b"4 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>\nendobj\n"
    obj5 = b"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n"
    obj6 = (
        f"6 0 obj\n<< /Length {len(stream_content)} >>\nstream\n".encode("latin1")
        + stream_content
        + b"\nendstream\nendobj\n"
    )

    objects = [obj1, obj2, obj3, obj4, obj5, obj6]

    current_offset = len(body[0])
    for obj in objects:
        offsets.append(current_offset)
        body.append(obj)
        current_offset += len(obj)

    xref_offset = current_offset
    xref = [f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("latin1")]
    for off in offsets:
        xref.append(f"{off:010d} 0000 n \n".encode("latin1"))

    trailer = f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode(
        "latin1"
    )

    return b"".join(body) + b"".join(xref) + trailer


async def generate_briefing_pdf(
    briefing: ExecutiveBriefingResponse, tenant_name: str = "Default Tenant"
) -> bytes:
    """Renders an ExecutiveBriefingResponse into valid PDF bytes."""
    template = env.get_template("briefing_report.html.j2")
    generated_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    html_str = template.render(
        briefing=briefing,
        tenant_name=tenant_name,
        generated_at=generated_at,
    )

    try:
        from weasyprint import HTML

        return await asyncio.to_thread(lambda: HTML(string=html_str).write_pdf())
    except Exception as exc:
        logger.warning(
            "WeasyPrint PDF generation unavailable (%s). Using pure-Python PDF generator.", exc
        )
        return _generate_fallback_pdf(briefing, tenant_name=tenant_name, generated_at=generated_at)
