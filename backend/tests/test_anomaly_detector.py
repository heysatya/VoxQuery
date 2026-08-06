"""
Tests for Statistical Outlier Anomaly Detector Service (PRD Feature 6).
"""

from app.models.contracts import ResultPayload
from app.services.anomaly_detector import _format_dimension_label, check_turn_anomaly, detect_outliers


def test_detect_outliers():
    # standard values with one huge outlier
    values = [10.0, 12.0, 11.0, 9.0, 100.0, 11.0, 10.0]
    outliers = detect_outliers(values, threshold=1.5)

    assert 4 in outliers  # 100.0 is the 5th element (index 4)
    assert len(outliers) == 1


def test_format_dimension_label():
    assert _format_dimension_label("2023-11-01 00:00:00") == "Nov 01, 2023"
    assert _format_dimension_label("2023-11-01T00:00:00") == "Nov 01, 2023"
    assert _format_dimension_label("2023-11-01") == "Nov 01, 2023"
    assert _format_dimension_label("Electronics") == "Electronics"


def test_check_turn_anomaly_date_formatting():
    payload = ResultPayload(
        columns=["order_date", "order_count"],
        rows=[
            ["2023-10-29 00:00:00", 100],
            ["2023-10-30 00:00:00", 105],
            ["2023-10-31 00:00:00", 98],
            ["2023-11-01 00:00:00", 500],
        ],
        row_count=4,
    )
    anomaly = check_turn_anomaly(payload)
    assert anomaly is not None
    assert anomaly.title == "Unusual Order Count — Nov 01, 2023"
    assert "2023-11-01 00:00:00" not in anomaly.title
    assert anomaly.direction == "up"
    assert anomaly.magnitude_pct > 0
    assert anomaly.follow_up_query is not None
    assert "Nov 01, 2023" in anomaly.follow_up_query
    assert "Order Count" in anomaly.follow_up_query

