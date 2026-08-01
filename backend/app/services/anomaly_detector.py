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


def check_turn_anomaly(result_payload: Any) -> Any:
    """
    Lightweight check against metric values returned by current turn query.
    If no value clears the z-score threshold (or insufficient rows), returns None.
    """
    from app.models.contracts import BriefingAnomaly
    if not result_payload or not getattr(result_payload, "rows", None) or len(result_payload.rows) < 3:
        return None

    num_col_idx = None
    for idx, col in enumerate(result_payload.columns):
        for row in result_payload.rows:
            if idx < len(row) and isinstance(row[idx], (int, float)) and not isinstance(row[idx], bool):
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
            label_val = str(row[dim_idx]) if dim_idx < len(row) and row[dim_idx] is not None else "Segment"
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

    return BriefingAnomaly(
        severity="warning" if abs(pct_diff) > 20 else "info",
        title=f"Variance in {label}",
        description=f"{metric_name} ({val:,.2f}) is {abs(pct_diff)}% {direction} average.",
    )

