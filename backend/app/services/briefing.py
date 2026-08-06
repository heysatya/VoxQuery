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


def _format_internal_date(value: Any) -> str | None:
    """Best-effort 'Mon DD, YYYY' formatting of a warehouse date/timestamp cell.

    Used ONLY to build BriefingAnomaly.follow_up_query (the hidden prompt sent
    to the pipeline when a flag is clicked) — never for title/description,
    which are deliberately date-free. A follow-up query needs a concrete week
    to anchor a real, aggregated answer; without one, the pipeline has been
    observed generating an unaggregated join that fans out into duplicate
    rows instead of a useful answer (see the 2551-row/"duplicate source
    records" symptom this fixes).
    """
    if value is None:
        return None
    if hasattr(value, "strftime"):
        return value.strftime("%b %d, %Y")
    if isinstance(value, str):
        cleaned = value.split("T")[0].split(" ")[0]
        try:
            return datetime.strptime(cleaned, "%Y-%m-%d").strftime("%b %d, %Y")
        except ValueError:
            return cleaned
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
            from app.services.briefing_compiler import get_or_compile_tenant_briefing_sql

            compiled_queries = await get_or_compile_tenant_briefing_sql(
                tenant_id=tenant_id,
                warehouse=warehouse,
                snowflake_role=snowflake_role,
            )

            # Query 1: Core KPIs
            kpi_sql = compiled_queries["kpi_sql"]
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

            # Query 2: Weekly multi-metric trend series across core business pillars
            trend_sql = compiled_queries["trend_sql"]
            trend_payload, _ = await warehouse.execute_readonly(
                trend_sql, snowflake_role=snowflake_role, tenant_id=tenant_id
            )

            # Query 3 (Best-effort): Category driver breakdown for dimensional attribution
            category_drivers: dict[Any, str] = {}
            try:
                cat_sql = compiled_queries["cat_sql"]
                cat_payload, _ = await warehouse.execute_readonly(
                    cat_sql, snowflake_role=snowflake_role, tenant_id=tenant_id
                )
                if cat_payload and cat_payload.rows:
                    for c_row in cat_payload.rows:
                        if len(c_row) >= 2 and c_row[0] is not None and c_row[1]:
                            w_key = str(c_row[0])
                            if w_key not in category_drivers:
                                category_drivers[w_key] = str(c_row[1]).replace("_", " ").title()
            except Exception as cat_exc:
                logger.debug("Category driver query omitted/unavailable: %s", cat_exc)

            if trend_payload and trend_payload.rows and len(trend_payload.rows) >= 3:
                valid_rows = [r for r in trend_payload.rows if len(r) > 1 and r[1] is not None]

                # ── Week-over-week KPI deltas ───────────────────────────────
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

                # ── Multi-Pillar Anomaly Engine (NMS Deduplication) ─────────
                # Evaluates 4 distinct operational pillars:
                #   Pillar 0: Revenue (Financial / Topline)
                #   Pillar 1: Orders (Transaction Volume)
                #   Pillar 2: Customers (Active Accounts)
                #   Pillar 3: Freight Ratio (Logistics & Unit Economics)
                #
                # Enforces Non-Maximum Suppression (NMS): selects at most ONE
                # top anomaly per pillar, taking top 3 distinct pillars overall.
                # This guarantees the executive briefing never surfaces 3
                # repetitive revenue flags.

                pillar_definitions = [
                    {
                        "key": "revenue",
                        "col_idx": 1,
                        "name": "Revenue",
                        "is_ratio": False,
                    },
                    {
                        "key": "customers",
                        "col_idx": 3,
                        "name": "Active Accounts",
                        "is_ratio": False,
                    },
                    {
                        "key": "orders",
                        "col_idx": 2,
                        "name": "Order Volume",
                        "is_ratio": False,
                    },
                    {
                        "key": "fulfillment",
                        "col_idx": 4,
                        "name": "Freight Ratio",
                        "is_ratio": True,
                    },
                ]

                candidates_by_pillar: dict[str, list[dict[str, Any]]] = {
                    p["key"]: [] for p in pillar_definitions
                }

                for pillar in pillar_definitions:
                    pkey = pillar["key"]
                    cidx = pillar["col_idx"]
                    is_ratio = pillar["is_ratio"]

                    # Extract time series values for this pillar
                    p_values: list[float] = []
                    p_rows: list[Any] = []
                    for r in valid_rows:
                        if len(r) > cidx and r[cidx] is not None:
                            if is_ratio:
                                rev_val = float(r[1]) if len(r) > 1 and r[1] else 0.0
                                frt_val = float(r[cidx])
                                ratio_val = (frt_val / rev_val * 100) if rev_val > 0 else 0.0
                                p_values.append(ratio_val)
                            else:
                                p_values.append(float(r[cidx]))
                            p_rows.append(r)

                    for i, val in enumerate(p_values):
                        window = p_values[max(0, i - 12) : i]
                        if len(window) < 3:
                            window = [v for j, v in enumerate(p_values) if j != i]

                        if not window:
                            continue

                        baseline_mean = sum(window) / len(window)
                        variance = sum((x - baseline_mean) ** 2 for x in window) / len(window)
                        std_dev = math.sqrt(variance)

                        if std_dev > 0:
                            z_score = abs(val - baseline_mean) / std_dev
                        elif val != baseline_mean and baseline_mean != 0:
                            z_score = abs(val - baseline_mean) / (abs(baseline_mean) * 0.05)
                        else:
                            z_score = 0.0

                        if z_score > 2.0:
                                row_week = p_rows[i][0] if i < len(p_rows) else None
                                if _extract_year(row_week) in _EXCLUDED_ANOMALY_YEARS:
                                    continue
                                abs_dev = abs(val - baseline_mean)
                                pct_diff = (
                                    ((val - baseline_mean) / baseline_mean * 100)
                                    if baseline_mean != 0
                                    else 0.0
                                )
                                candidates_by_pillar[pkey].append(
                                    {
                                        "pillar": pkey,
                                        "pillar_name": pillar["name"],
                                        "idx": i,
                                        "row": p_rows[i],
                                        "val": val,
                                        "abs_dev": abs_dev,
                                        "baseline_mean": baseline_mean,
                                        "pct_diff": pct_diff,
                                        "z_score": z_score,
                                    }
                                )

                # Select top 1 anomaly per pillar (NMS)
                selected_per_pillar: list[dict[str, Any]] = []
                for pkey, items in candidates_by_pillar.items():
                    if items:
                        # Sort by z_score within each pillar to get the pillar's best signal
                        items.sort(key=lambda c: c["z_score"], reverse=True)
                        selected_per_pillar.append(items[0])

                # Sort across pillars by significance and pick top 3 distinct pillars
                selected_per_pillar.sort(key=lambda c: c["z_score"], reverse=True)
                top_pillars = selected_per_pillar[:3]

                for item in top_pillars:
                    pkey = item["pillar"]
                    week_val = item["val"]
                    baseline_val = item["baseline_mean"]
                    pct_diff = item["pct_diff"]
                    is_surge = week_val > baseline_val
                    severity = "critical" if abs(pct_diff) >= 40 else "warning"

                    row_week = item["row"][0] if item.get("row") else None
                    w_key = str(row_week) if row_week else ""
                    driver_cat = category_drivers.get(w_key)

                    # Build date-free UI title and description (User Requirement 1).
                    # Historical calendar dates (e.g. "Oct 2023") are NEVER displayed in UI text.
                    if pkey == "revenue":
                        if driver_cat:
                            title = f"Revenue {'Surge' if is_surge else 'Shortfall'} in {driver_cat}"
                        else:
                            title = f"Topline Revenue {'Surge' if is_surge else 'Shortfall'}"
                        description = (
                            f"${week_val:,.0f} in revenue, {abs(pct_diff):.0f}% "
                            f"{'above' if is_surge else 'below'} trailing baseline "
                            f"(${baseline_val:,.0f})."
                            + (f" Driven by strong demand in {driver_cat}." if driver_cat else "")
                        )
                        # Build safe, aggregated follow-up query with TOP 5 limits (User Requirement 2)
                        formatted_date = _format_internal_date(row_week)
                        p_phrase = f"the week of {formatted_date}" if formatted_date else "that period"
                        follow_up_query = (
                            f"What drove the {abs(pct_diff):.0f}% revenue {'surge' if is_surge else 'shortfall'} in {p_phrase}? "
                            f"Show me the top 5 product categories by total revenue with weekly totals."
                        )

                    elif pkey == "customers":
                        title = f"Active Account {'Surge' if is_surge else 'Volume Drop'}"
                        description = (
                            f"{int(week_val):,} active accounts, {abs(pct_diff):.0f}% "
                            f"{'above' if is_surge else 'below'} trailing baseline "
                            f"({int(baseline_val):,}). Flagged for business review."
                        )
                        formatted_date = _format_internal_date(row_week)
                        p_phrase = f"the week of {formatted_date}" if formatted_date else "that period"
                        follow_up_query = (
                            f"What caused the {abs(pct_diff):.0f}% change in active customer accounts in {p_phrase}? "
                            f"Show me weekly active account volume for the top 5 customer states."
                        )

                    elif pkey == "orders":
                        title = f"Transaction Volume {'Surge' if is_surge else 'Contraction'}"
                        description = (
                            f"{int(week_val):,} total orders, {abs(pct_diff):.0f}% "
                            f"{'above' if is_surge else 'below'} trailing average "
                            f"({int(baseline_val):,} orders)."
                        )
                        formatted_date = _format_internal_date(row_week)
                        p_phrase = f"the week of {formatted_date}" if formatted_date else "that period"
                        follow_up_query = (
                            f"What drove the {abs(pct_diff):.0f}% shift in order volume in {p_phrase}? "
                            f"Show me weekly order counts for the top 5 payment types."
                        )

                    else:  # fulfillment
                        title = f"Freight Cost Ratio {'Spike' if is_surge else 'Drop'}"
                        description = (
                            f"Freight costs reached {week_val:.1f}% of revenue, {abs(pct_diff):.0f}% "
                            f"{'above' if is_surge else 'below'} typical ratio "
                            f"({baseline_val:.1f}%)."
                        )
                        formatted_date = _format_internal_date(row_week)
                        p_phrase = f"the week of {formatted_date}" if formatted_date else "that period"
                        follow_up_query = (
                            f"What drove the {abs(pct_diff):.0f}% shift in freight cost ratio in {p_phrase}? "
                            f"Show me weekly freight cost and order totals for the top 5 shipping regions."
                        )

                    anomalies.append(
                        BriefingAnomaly(
                            severity=severity,
                            title=title,
                            description=description,
                            direction="up" if is_surge else "down",
                            magnitude_pct=round(abs(pct_diff), 1),
                            follow_up_query=follow_up_query,
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
