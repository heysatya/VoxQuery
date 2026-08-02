"""
Morning Executive Briefing Service (PRD V2.1 Feature 1).

Generates real-time daily executive summaries, KPI trends, anomaly flags, and
proactive analytical questions for logon dashboards and email push notifications.
"""

from __future__ import annotations

import logging
import json
import math
import os
from asyncio import Lock
from datetime import date, datetime, timezone
from time import monotonic
from typing import Any

from app.config import Settings
from app.models.contracts import (
    BriefingAnomaly,
    BriefingKpi,
    ExecutiveBriefingResponse,
)
from app.services.anomaly_detector import detect_outliers
from app.warehouse.connector import WarehouseConnector
from app.warehouse.sql_policy import canonicalize_readonly_sql

logger = logging.getLogger("voxquery.services.briefing")

try:
    _BRIEFING_CACHE_TTL_SECONDS = max(
        30,
        int(os.getenv("VOXQUERY_BRIEFING_CACHE_TTL_SECONDS", "300")),
    )
except (TypeError, ValueError):
    _BRIEFING_CACHE_TTL_SECONDS = 300
_briefing_cache: dict[tuple[str, str, str, bool], tuple[float, ExecutiveBriefingResponse]] = {}
_briefing_cache_lock = Lock()


async def generate_morning_briefing(
    tenant_id: str,
    settings: Settings,
    user_name: str = "Executive",
    warehouse: WarehouseConnector | None = None,
    snowflake_role: str = "ANALYST_READONLY",
    redis_client: Any | None = None,
) -> ExecutiveBriefingResponse:
    """Return a short-lived tenant-scoped briefing snapshot.

    The home screen, drawer, and export paths can request the same briefing
    within seconds of one another. A bounded in-process cache prevents those
    requests from repeating the two warehouse queries while keeping the data
    fresh for the next briefing window.
    """
    cache_key = (tenant_id, user_name, snowflake_role, warehouse is not None)
    shared_cache_key = (
        f"briefing:{tenant_id}:{user_name}:{snowflake_role}:"
        f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}:"
        f"{'live' if warehouse is not None else 'unavailable'}"
    )

    if redis_client is not None:
        try:
            raw = await redis_client.get(shared_cache_key)
            if raw:
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8")
                shared_briefing = ExecutiveBriefingResponse.model_validate(json.loads(raw))
                _briefing_cache[cache_key] = (monotonic(), shared_briefing)
                return shared_briefing
        except Exception:
            logger.debug("Shared briefing cache read failed", exc_info=True)
    now = monotonic()
    cached = _briefing_cache.get(cache_key)
    if cached and now - cached[0] < _BRIEFING_CACHE_TTL_SECONDS:
        return cached[1]

    async with _briefing_cache_lock:
        now = monotonic()
        cached = _briefing_cache.get(cache_key)
        if cached and now - cached[0] < _BRIEFING_CACHE_TTL_SECONDS:
            return cached[1]

        briefing = await _generate_morning_briefing_uncached(
            tenant_id,
            settings,
            user_name=user_name,
            warehouse=warehouse,
            snowflake_role=snowflake_role,
        )
        _briefing_cache[cache_key] = (monotonic(), briefing)
        if redis_client is not None:
            try:
                await redis_client.setex(
                    shared_cache_key,
                    _BRIEFING_CACHE_TTL_SECONDS,
                    json.dumps(briefing.model_dump(mode="json")),
                )
            except Exception:
                logger.debug("Shared briefing cache write failed", exc_info=True)
        return briefing


async def _generate_morning_briefing_uncached(
    tenant_id: str,
    settings: Settings,
    user_name: str = "Executive",
    warehouse: WarehouseConnector | None = None,
    snowflake_role: str = "ANALYST_READONLY",
) -> ExecutiveBriefingResponse:
    """
    Generate an executive briefing report for the given tenant using real warehouse queries.
    """
    today_str = datetime.now(timezone.utc).strftime("%A, %B %d, %Y")

    kpis: list[BriefingKpi] = []
    anomalies: list[BriefingAnomaly] = []
    is_live = False

    if warehouse is not None:
        try:
            # Query 1: Core KPIs
            kpi_sql = canonicalize_readonly_sql(
                "SELECT "
                "SUM(order_items.price * (1 - order_items.discount_rate) + order_items.freight_value) AS total_revenue, "
                "AVG(order_items.price) AS avg_order_value, "
                "COUNT(DISTINCT orders.order_id) AS total_orders, "
                "COUNT(DISTINCT orders.customer_id) AS active_customers "
                "FROM order_items "
                "JOIN orders ON order_items.order_id = orders.order_id"
            ).sql
            result_payload, _ = await warehouse.execute_readonly(
                kpi_sql, snowflake_role=snowflake_role, tenant_id=tenant_id
            )
            if result_payload and result_payload.rows and len(result_payload.rows) > 0:
                is_live = True
                row = result_payload.rows[0]
                tot_rev = float(row[0]) if row[0] is not None else None
                aov = float(row[1]) if row[1] is not None else None
                orders_cnt = int(row[2]) if row[2] is not None else None
                customers_cnt = int(row[3]) if row[3] is not None else None

                rev_formatted = (
                    f"${tot_rev / 1e6:.1f}M"
                    if tot_rev is not None and tot_rev >= 1e6
                    else (f"${tot_rev:,.2f}" if tot_rev is not None else "No data")
                )
                kpis = [
                    BriefingKpi(
                        label="Total Revenue (YTD)",
                        value=rev_formatted,
                        change_pct=None,
                        trend=None,
                        insight=f"Tenant {tenant_id[:8]} revenue target performance.",
                    ),
                    BriefingKpi(
                        label="Active Accounts",
                        value=f"{customers_cnt:,}" if customers_cnt is not None else "No data",
                        change_pct=None,
                        trend=None,
                        insight="Active account count recorded across tenant workspace.",
                    ),
                    BriefingKpi(
                        label="Avg Order Value",
                        value=f"${aov:.2f}" if aov is not None else "No data",
                        change_pct=None,
                        trend=None,
                        insight="Average order value across recent transactions.",
                    ),
                    BriefingKpi(
                        label="Total Orders",
                        value=f"{orders_cnt:,}" if orders_cnt is not None else "No data",
                        change_pct=None,
                        trend=None,
                        insight="Total completed transaction volume.",
                    ),
                ]

            # Query 2: Weekly trend series for outlier anomaly detection
            trend_sql = canonicalize_readonly_sql(
                "SELECT "
                "DATE_TRUNC('week', TRY_TO_TIMESTAMP(orders.order_purchase_timestamp)) AS order_week, "
                "SUM(order_items.price) AS weekly_revenue "
                "FROM order_items "
                "JOIN orders ON order_items.order_id = orders.order_id "
                "GROUP BY 1 ORDER BY 1"
            ).sql
            trend_payload, _ = await warehouse.execute_readonly(
                trend_sql, snowflake_role=snowflake_role, tenant_id=tenant_id
            )
            if trend_payload and trend_payload.rows and len(trend_payload.rows) >= 3:
                valid_rows = [r for r in trend_payload.rows if len(r) > 1 and r[1] is not None]
                weekly_values = [float(r[1]) for r in valid_rows]

                candidate_anomalies = []
                for i, val in enumerate(weekly_values):
                    # Trailing window of most recent 8-12 weeks relative to point i (up to 12 weeks)
                    window = weekly_values[max(0, i - 12) : i]
                    if len(window) < 3:
                        window = [v for j, v in enumerate(weekly_values) if j != i]

                    if not window:
                        continue

                    baseline_mean = sum(window) / len(window)
                    variance = sum((x - baseline_mean) ** 2 for x in window) / len(window)
                    std_dev = math.sqrt(variance)

                    if std_dev > 0:
                        z_score = abs(val - baseline_mean) / std_dev
                        if z_score > 2.5:  # (a) Raised threshold to 2.5
                            abs_dev = abs(val - baseline_mean)
                            candidate_anomalies.append(
                                {
                                    "idx": i,
                                    "row": valid_rows[i],
                                    "val": val,
                                    "abs_dev": abs_dev,
                                }
                            )

                # (b) Cap anomalies appended to the top 3 most significant (largest absolute deviation from baseline)
                candidate_anomalies.sort(key=lambda c: c["abs_dev"], reverse=True)
                top_3_anomalies = candidate_anomalies[:3]
                top_3_anomalies.sort(key=lambda c: c["idx"])

                for item in top_3_anomalies:
                    row_week = item["row"][0]
                    # (d) Format actual order_week date from row[0]
                    if hasattr(row_week, "strftime"):
                        formatted_date = row_week.strftime("%b %d, %Y")
                    elif isinstance(row_week, str):
                        cleaned = row_week.split("T")[0].split(" ")[0]
                        try:
                            dt = datetime.strptime(cleaned, "%Y-%m-%d")
                            formatted_date = dt.strftime("%b %d, %Y")
                        except ValueError:
                            formatted_date = cleaned
                    else:
                        formatted_date = (
                            str(row_week) if row_week is not None else f"Week {item['idx'] + 1}"
                        )

                    week_val = item["val"]
                    anomalies.append(
                        BriefingAnomaly(
                            severity="warning",
                            title=f"Revenue Variance ({formatted_date})",
                            description=f"Weekly revenue of ${week_val:,.2f} deviates significantly from baseline average.",
                        )
                    )
        except Exception as e:
            logger.warning(
                "Could not execute real warehouse briefing query for tenant %s: %s", tenant_id, e
            )

    if not kpis:
        return ExecutiveBriefingResponse(
            date=today_str,
            greeting="Business pulse unavailable",
            kpis=[],
            summary_narrative="Connect a live workspace to generate a briefing from your business data.",
            anomalies=[],
            proactive_insights=[],
            is_live=False,
            data_source="unavailable",
        )

    proactive_insights = []
    rev_val = kpis[0].value
    acc_val = kpis[1].value if len(kpis) > 1 else "the available account data"
    summary_narrative = (
        f"Good morning, {user_name}. Revenue stands at {rev_val}, "
        f"with account activity at {acc_val}."
    )
    summary_narrative += (
        f" {len(anomalies)} item{'s' if len(anomalies) != 1 else ''} require attention."
        if anomalies
        else " No anomalies were detected in the available metrics."
    )

    return ExecutiveBriefingResponse(
        date=today_str,
        greeting=f"Executive Briefing - {today_str}",
        kpis=kpis,
        summary_narrative=summary_narrative,
        anomalies=anomalies,
        proactive_insights=proactive_insights,
        is_live=is_live,
        data_source="live" if is_live else "unavailable",
    )
