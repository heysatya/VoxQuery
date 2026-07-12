from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.models.contracts import (
    ChartType,
    FeedbackRequest,
    ResultPayload,
    valid_visualizations_for_result,
)


def test_result_payload_infers_semantic_columns_and_preview_metadata():
    payload = ResultPayload(
        columns=["customer_segment", "total_net_revenue"],
        rows=[["Enterprise", 1240000], ["Consumer", 830000]],
        row_count=10,
    )

    assert payload.preview_row_count == 2
    assert payload.is_truncated is True
    assert payload.semantic_columns[0].role == "dimension"
    assert payload.semantic_columns[0].value_type == "string"
    assert payload.semantic_columns[1].role == "metric"
    assert payload.semantic_columns[1].value_type == "number"


def test_valid_visualizations_follow_result_shape():
    categorical_metric = ResultPayload(
        columns=["customer_segment", "total_net_revenue"],
        rows=[["Enterprise", 1240000]],
        row_count=1,
    )
    assert valid_visualizations_for_result(categorical_metric) == [
        ChartType.table,
        ChartType.stat,
        ChartType.bar,
    ]

    scalar = ResultPayload(columns=["total_net_revenue"], rows=[[1240000]], row_count=1)
    assert valid_visualizations_for_result(scalar) == [ChartType.table, ChartType.stat]


def test_feedback_contract_accepts_thumbs_up_and_down_only():
    session_id = uuid4()
    turn_id = uuid4()

    assert FeedbackRequest(session_id=session_id, turn_id=turn_id, rating=1).rating == 1
    assert FeedbackRequest(session_id=session_id, turn_id=turn_id, rating=-1).rating == -1

    with pytest.raises(ValidationError):
        FeedbackRequest(session_id=session_id, turn_id=turn_id, rating=0)
