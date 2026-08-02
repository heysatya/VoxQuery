"""Reliable executive briefing email delivery.

The dispatcher deliberately has no fake-success path. A briefing is marked as
sent only after the configured provider accepts it, and delivery state is
scoped by tenant, user, and local delivery date.
"""

from __future__ import annotations

import asyncio
import html
import json
import logging
from datetime import date, datetime, timezone
from email.utils import parseaddr
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request as UrlRequest, urlopen

import asyncpg

from app.config import Settings
from app.models.contracts import ExecutiveBriefingResponse

logger = logging.getLogger("voxquery.services.briefing_dispatcher")


class BriefingDeliveryError(RuntimeError):
    """Raised when a configured briefing email provider rejects delivery."""


def _format_plain_text(briefing: ExecutiveBriefingResponse, dashboard_url: str) -> str:
    lines = [briefing.greeting, f"Date: {briefing.date}", "", briefing.summary_narrative]
    if briefing.kpis:
        lines.extend(["", "Key metrics:"])
        for kpi in briefing.kpis:
            change = f" ({kpi.change_pct:+.1f}%)" if kpi.change_pct is not None else ""
            lines.append(f"- {kpi.label}: {kpi.value}{change}")
    if briefing.anomalies:
        lines.extend(["", "Items to review:"])
        lines.extend(f"- {item.title}: {item.description}" for item in briefing.anomalies)
    lines.extend(["", f"Open the executive dashboard: {dashboard_url}"])
    return "\n".join(lines)


def _render_html(briefing: ExecutiveBriefingResponse, dashboard_url: str) -> str:
    def esc(value: Any) -> str:
        return html.escape(str(value), quote=True)
    kpi_rows = "".join(
        "<tr>"
        f"<td style='padding:8px 12px;border-bottom:1px solid #e5e7eb'>{esc(kpi.label)}</td>"
        f"<td style='padding:8px 12px;border-bottom:1px solid #e5e7eb;font-weight:600'>{esc(kpi.value)}</td>"
        f"<td style='padding:8px 12px;border-bottom:1px solid #e5e7eb'>{esc(kpi.insight)}</td>"
        "</tr>"
        for kpi in briefing.kpis
    )
    anomaly_rows = "".join(
        f"<li><strong>{esc(item.title)}</strong>: {esc(item.description)}</li>"
        for item in briefing.anomalies
    )
    kpi_section = (
        f"<h3>Key metrics</h3><table style='border-collapse:collapse;width:100%'>"
        f"<thead><tr><th align='left' style='padding:8px 12px'>Metric</th>"
        f"<th align='left' style='padding:8px 12px'>Value</th>"
        f"<th align='left' style='padding:8px 12px'>Context</th></tr></thead>"
        f"<tbody>{kpi_rows}</tbody></table>"
        if kpi_rows else ""
    )
    anomaly_section = f"<h3>Items to review</h3><ul>{anomaly_rows}</ul>" if anomaly_rows else ""
    return f"""<!doctype html>
<html><body style="font-family:Arial,sans-serif;color:#1f2937;line-height:1.5">
  <h2>{esc(briefing.greeting)}</h2>
  <p><strong>Date:</strong> {esc(briefing.date)}</p>
  <p>{esc(briefing.summary_narrative)}</p>
  {kpi_section}
  {anomaly_section}
  <p style="margin-top:24px"><a href="{esc(dashboard_url)}" style="display:inline-block;padding:10px 18px;background:#1677ff;color:#fff;text-decoration:none;border-radius:6px">Open executive dashboard</a></p>
</body></html>"""


async def _send_resend(
    *,
    settings: Settings,
    recipient: str,
    subject: str,
    html_content: str,
    text_content: str,
) -> None:
    if not settings.resend_api_key or not settings.briefing_email_from:
        raise BriefingDeliveryError("Resend email delivery is not configured.")

    payload = json.dumps({
        "from": settings.briefing_email_from,
        "to": [recipient],
        "subject": subject,
        "html": html_content,
        "text": text_content,
    }).encode("utf-8")

    def send() -> None:
        request = UrlRequest(
            settings.resend_api_url,
            data=payload,
            headers={
                "Authorization": f"Bearer {settings.resend_api_key}",
                "Content-Type": "application/json",
                "User-Agent": "VoxQuery/briefing-dispatcher",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=15) as response:
                if response.status < 200 or response.status >= 300:
                    raise BriefingDeliveryError(f"Email provider returned HTTP {response.status}.")
        except HTTPError as exc:
            raise BriefingDeliveryError(f"Email provider rejected delivery with HTTP {exc.code}.") from exc
        except URLError as exc:
            raise BriefingDeliveryError("Email provider could not be reached.") from exc

    await asyncio.to_thread(send)


async def _reserve_delivery(pool: asyncpg.Pool, user_id: str, tenant_id: str, delivery_date: date) -> bool:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO briefing_send_log (user_id, tenant_id, send_date, status, error, sent_at)
            VALUES ($1, $2, $3, 'sending', NULL, NOW())
            ON CONFLICT (tenant_id, user_id, send_date) DO UPDATE
              SET status = 'sending', error = NULL, sent_at = NOW()
              WHERE briefing_send_log.status = 'failed'
                 OR (briefing_send_log.status = 'sending'
                     AND briefing_send_log.sent_at < NOW() - INTERVAL '15 minutes')
            RETURNING id
            """,
            user_id,
            tenant_id,
            delivery_date,
        )
        return row is not None


async def _mark_delivery(
    pool: asyncpg.Pool,
    user_id: str,
    tenant_id: str,
    delivery_date: date,
    *,
    status: str,
    error: str | None = None,
) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE briefing_send_log
            SET status = $3, error = $4, sent_at = NOW()
            WHERE tenant_id = $1 AND user_id = $2 AND send_date = $5
            """,
            tenant_id,
            user_id,
            status,
            error[:500] if error else None,
            delivery_date,
        )


async def dispatch_briefing_email(
    user_id: str,
    email: str,
    briefing: ExecutiveBriefingResponse,
    settings: Settings,
    pool: asyncpg.Pool | None = None,
    tenant_id: str | None = None,
    delivery_date: date | None = None,
) -> bool:
    """Deliver one briefing and return True only after provider acceptance."""
    recipient = parseaddr(email)[1].strip()
    if not recipient or "@" not in recipient:
        raise BriefingDeliveryError("A valid briefing recipient email is required.")
    if not tenant_id:
        raise BriefingDeliveryError("Tenant context is required for briefing delivery.")
    if settings.briefing_email_provider == "disabled":
        raise BriefingDeliveryError("Briefing email delivery is disabled by configuration.")

    effective_delivery_date = delivery_date or datetime.now(timezone.utc).date()
    if pool and not await _reserve_delivery(pool, user_id, tenant_id, effective_delivery_date):
        logger.info("Briefing delivery already sent or in progress user_id=%s tenant_id=%s", user_id, tenant_id)
        return False

    dashboard_url = settings.public_app_url.rstrip("/")
    subject = f"VoxQuery executive briefing — {briefing.date}"
    html_content = _render_html(briefing, dashboard_url)
    text_content = _format_plain_text(briefing, dashboard_url)

    try:
        if settings.briefing_email_provider == "resend":
            await _send_resend(
                settings=settings,
                recipient=recipient,
                subject=subject,
                html_content=html_content,
                text_content=text_content,
            )
        else:
            raise BriefingDeliveryError("Unsupported briefing email provider.")
        if pool:
            await _mark_delivery(pool, user_id, tenant_id, effective_delivery_date, status="sent")
    except Exception as exc:
        if pool:
            try:
                await _mark_delivery(pool, user_id, tenant_id, effective_delivery_date, status="failed", error=str(exc))
            except Exception:
                logger.exception("Could not persist briefing delivery failure")
        raise

    logger.info("Briefing email accepted by provider user_id=%s tenant_id=%s", user_id, tenant_id)
    return True
