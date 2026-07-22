"""
Statistical Outlier Anomaly Detector Service (PRD Feature 6).

Implements Z-score statistics to highlight anomalies and extreme trend variations.
"""

from __future__ import annotations

import logging
import math

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
