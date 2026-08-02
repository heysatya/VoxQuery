"""
Tests for Statistical Outlier Anomaly Detector Service (PRD Feature 6).
"""

from app.services.anomaly_detector import detect_outliers


def test_detect_outliers():
    # standard values with one huge outlier
    values = [10.0, 12.0, 11.0, 9.0, 100.0, 11.0, 10.0]
    outliers = detect_outliers(values, threshold=1.5)

    assert 4 in outliers  # 100.0 is the 5th element (index 4)
    assert len(outliers) == 1
