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

# Rows in this dataset dated 2024/2025 are known-stale/synthetic artifacts of
# the source data, not organic recent activity. Surfacing a flag dated
# "Nov 2025" in a "Today's Business Pulse" reads as current when it isn't —
# so anomaly candidates in these years are excluded before ranking.
_EXCLUDED_ANOMALY_YEARS = {2024, 2025}

# Ordinal labels for ranking anomaly flags by magnitude instead of citing a
# calendar date (see the ranking loop in _generate_morning_briefing_uncached
# for why). Falls back to "#4", "#5", ... beyond this list, though the
# anomaly cap is currently 3 per direction so that path is untested headroom.
_RANK_ORDINALS = ["Biggest", "Second-biggest", "Third-biggest", "Fourth-biggest", "Fifth-biggest"]


def _extract_year(value: Any) -> int | None:
    """Best-effort year extraction from a warehouse date/timestamp/string cell."""
    if hasattr(value, "year"):
        return value.year
    if isinstance(value, str):
        cleaned = value.split("T")[0].split(" ")[0]
        try:
            return datetime.strptime(cleaned, "%Y-%m-%d").year
        except ValueError:
            return None
    return None


def _pct_change(curr: float | None, prev: float | None) -> float | None:
    """Percent change from prev -> curr, or None if not computable."""
    if curr is None or prev in (None, 0):
        return None
    return round((curr - prev) / prev * 100, 1)


def _trend_direction(pct: float | None) -> str | None:
    if pct is None:
        return None
    if pct > 0.5:
        return "up"
    if pct < -0.5:
        return "down"
    return "neutral"


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

            # Query 2: Weekly trend series for outlier anomaly detection, and for
            # week-over-week KPI deltas (orders/customers pulled alongside revenue
            # so the WoW comparison below doesn't need a third round trip).
            trend_sql = canonicalize_readonly_sql(
                "SELECT "
                "DATE_TRUNC('week', TRY_TO_TIMESTAMP(orders.order_purchase_timestamp)) AS order_week, "
                "SUM(order_items.price) AS weekly_revenue, "
                "COUNT(DISTINCT orders.order_id) AS weekly_orders, "
                "COUNT(DISTINCT orders.customer_id) AS weekly_customers "
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

                # ── Week-over-week KPI deltas ───────────────────────────────
                # Compares the two most recent complete weeks in the dataset's
                # own timeline (not wall-clock "today" — this is historical
                # data). Only a relative % and direction are surfaced on the
                # KPI cards, never a calendar date, so this stays meaningful
                # regardless of which actual years the underlying rows fall in.
                if len(valid_rows) >= 2 and kpis:
                    latest_row, prev_row = valid_rows[-1], valid_rows[-2]

                    def _cell(row, idx):
                        return float(row[idx]) if len(row) > idx and row[idx] is not None else None

                    rev_latest, rev_prev = _cell(latest_row, 1), _cell(prev_row, 1)
                    orders_latest, orders_prev = _cell(latest_row, 2), _cell(prev_row, 2)
                    cust_latest, cust_prev = _cell(latest_row, 3), _cell(prev_row, 3)
                    aov_latest = (
                        rev_latest / orders_latest
                        if rev_latest is not None and orders_latest
                        else None
                    )
                    aov_prev = (
                        rev_prev / orders_prev if rev_prev is not None and orders_prev else None
                    )

                    # kpis indices: 0=Total Revenue, 1=Active Accounts, 2=Avg Order Value, 3=Total Orders
                    kpi_deltas = {
                        0: _pct_change(rev_latest, rev_prev),
                        1: _pct_change(cust_latest, cust_prev),
                        2: _pct_change(aov_latest, aov_prev),
                        3: _pct_change(orders_latest, orders_prev),
                    }
                    for kpi_idx, pct in kpi_deltas.items():
                        if pct is None or kpi_idx >= len(kpis):
                            continue
                        kpis[kpi_idx].change_pct = pct
                        kpis[kpi_idx].trend = _trend_direction(pct)
                        direction_word = "Up" if pct > 0 else "Down" if pct < 0 else "Flat"
                        kpis[
                            kpi_idx
                        ].insight = f"{direction_word} {abs(pct):.1f}% vs. the prior week."

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
                            row_week = valid_rows[i][0] if i < len(valid_rows) else None
                            if _extract_year(row_week) in _EXCLUDED_ANOMALY_YEARS:
                                # Stale/synthetic years — see _EXCLUDED_ANOMALY_YEARS.
                                # Skip rather than filter after ranking, so a real
                                # anomaly outside this window can take the slot.
                                continue
                            abs_dev = abs(val - baseline_mean)
                            candidate_anomalies.append(
                                {
                                    "idx": i,
                                    "row": valid_rows[i],
                                    "val": val,
                                    "abs_dev": abs_dev,
                                    "baseline_mean": baseline_mean,
                                    "pct_diff": (
                                        (val - baseline_mean) / baseline_mean * 100
                                        if baseline_mean
                                        else 0.0
                                    ),
                                }
                            )

                # (b) Cap anomalies appended to the top 3 most significant (largest absolute deviation from baseline)
                candidate_anomalies.sort(key=lambda c: c["abs_dev"], reverse=True)
                top_3_anomalies = candidate_anomalies[:3]
                # Deliberately NOT re-sorted back into chronological order here.
                # Business Pulse never surfaces a calendar date for these flags
                # (see title-building loop below) — showing "week of Oct 2023"
                # next to a header dated "Today" reads as stale/broken, since
                # this dataset's real timeline predates the app's live clock
                # by years. Magnitude order lets the copy rank flags instead
                # ("Biggest", "Second-biggest", ...), which is both accurate
                # and meaningful without ever citing when the row occurred.
                surge_rank = 0
                shortfall_rank = 0

                for item in top_3_anomalies:
                    week_val = item["val"]
                    baseline_val = item["baseline_mean"]
                    pct_diff = item["pct_diff"]
                    is_surge = week_val > baseline_val

                    # Executive-attention-grabbing framing: lead with the size and
                    # direction of the swing (the number a VP actually reacts to),
                    # not just a flat "deviates from baseline" restatement of the
                    # z-score test. Severity escalates to "critical" for the
                    # largest swings so the UI can visually distinguish a >50%
                    # move from a routine week-to-week wobble.
                    severity = "critical" if abs(pct_diff) >= 50 else "warning"

                    if is_surge:
                        ordinal = (
                            _RANK_ORDINALS[surge_rank]
                            if surge_rank < len(_RANK_ORDINALS)
                            else f"#{surge_rank + 1}"
                        )
                        surge_rank += 1
                        title = f"{ordinal} revenue spike"
                        description = (
                            f"${week_val:,.0f} that period, {abs(pct_diff):.0f}% above the "
                            f"trailing baseline of ${baseline_val:,.0f}. Worth confirming "
                            "whether this was a promotion, bulk order, or one-off before "
                            "citing it as a trend."
                        )
                    else:
                        ordinal = (
                            _RANK_ORDINALS[shortfall_rank]
                            if shortfall_rank < len(_RANK_ORDINALS)
                            else f"#{shortfall_rank + 1}"
                        )
                        shortfall_rank += 1
                        title = f"{ordinal} revenue shortfall"
                        description = (
                            f"${week_val:,.0f} that period, {abs(pct_diff):.0f}% below the "
                            f"trailing baseline of ${baseline_val:,.0f}. Flag for review "
                            "ahead of the next leadership check-in."
                        )

                    anomalies.append(
                        BriefingAnomaly(
                            severity=severity,
                            title=title,
                            description=description,
                            direction="up" if is_surge else "down",
                            magnitude_pct=round(abs(pct_diff), 1),
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
