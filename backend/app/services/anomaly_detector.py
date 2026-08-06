"""
Statistical Outlier Anomaly Detector Service (PRD Feature 6).

Implements Z-score statistics to highlight anomalies and extreme trend variations.
"""

from __future__ import annotations

import logging
import math
from typing import Any

logger = logging.getLogger("voxquery.services.anomaly")


def detect_outliers(
    values: list[float],
    threshold: float = 1.5,
) -> list[int]:
    """
    Returns the indexes of values that qualify as statistical anomalies.
    """
    if len(values) < 3:
        return []

    mean = sum(values) / len(values)
    variance = sum((x - mean) ** 2 for x in values) / len(values)
    std_dev = math.sqrt(variance)

    if std_dev == 0:
        return []

    outliers = []
    for idx, x in enumerate(values):
        z_score = abs(x - mean) / std_dev
        if z_score > threshold:
            outliers.append(idx)

    return outliers


def _format_dimension_label(raw: str) -> str:
    """
    Format a raw warehouse dimension value for display in the UI.

    Bare DB timestamp strings like "2023-11-01 00:00:00" look broken in a banner title;
    reformat them to "Nov 01, 2023". Non-date values (segment names, product categories, etc.)
    pass through unchanged.
    """
    import datetime

    cleaned = str(raw).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.datetime.strptime(cleaned, fmt)
            return dt.strftime("%b %d, %Y")
        except ValueError:
            continue
    return cleaned


def check_turn_anomaly(result_payload: Any) -> Any:
    """
    Lightweight check against metric values returned by current turn query.
    If no value clears the z-score threshold (or insufficient rows), returns None.
    """
    from app.models.contracts import BriefingAnomaly

    if (
        not result_payload
        or not getattr(result_payload, "rows", None)
        or len(result_payload.rows) < 3
    ):
        return None

    num_col_idx = None
    for idx, col in enumerate(result_payload.columns):
        for row in result_payload.rows:
            if (
                idx < len(row)
                and isinstance(row[idx], (int, float))
                and not isinstance(row[idx], bool)
            ):
                num_col_idx = idx
                break
        if num_col_idx is not None:
            break

    if num_col_idx is None:
        return None

    values = []
    labels = []
    dim_idx = 0 if num_col_idx != 0 else 1
    for row in result_payload.rows:
        if num_col_idx < len(row) and isinstance(row[num_col_idx], (int, float)):
            values.append(float(row[num_col_idx]))
            label_val = (
                str(row[dim_idx]) if dim_idx < len(row) and row[dim_idx] is not None else "Segment"
            )
            labels.append(label_val)

    outliers = detect_outliers(values, threshold=1.5)
    if not outliers:
        return None

    top_idx = outliers[-1]
    val = values[top_idx]
    label = labels[top_idx]
    mean = sum(values) / len(values)
    pct_diff = round(((val - mean) / mean) * 100, 1) if mean != 0 else 0.0

    direction = "above" if val > mean else "below"
    metric_name = result_payload.columns[num_col_idx].replace("_", " ").title()

    display_label = _format_dimension_label(label)

    follow_up_query = (
        f"Show me a breakdown of {metric_name} around {display_label} "
        f"({abs(pct_diff):.1f}% {direction} average). "
        "What drove this variance? Break it down by product category."
    )

    return BriefingAnomaly(
        severity="warning" if abs(pct_diff) > 20 else "info",
        title=f"Unusual {metric_name} — {display_label}",
        description=f"{metric_name} ({val:,.2f}) is {abs(pct_diff)}% {direction} average.",
        direction="up" if val > mean else "down",
        magnitude_pct=round(abs(pct_diff), 1),
        follow_up_query=follow_up_query,
    )

