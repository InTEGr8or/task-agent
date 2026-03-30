from datetime import datetime, timezone
from taskagent.models.metric import SubtaskMetric
import pytest
from pydantic import ValidationError


def test_subtask_metric_creation():
    start = datetime.now(timezone.utc)
    metric = SubtaskMetric(
        start_time=start, model="gemini-2.0-flash", provider="google", cost=0.005
    )
    assert metric.start_time == start
    assert metric.model == "gemini-2.0-flash"
    assert metric.provider == "google"
    assert metric.cost == 0.005
    assert metric.end_time is None


def test_subtask_metric_frozen():
    metric = SubtaskMetric(
        start_time=datetime.now(timezone.utc), model="test", provider="test"
    )
    with pytest.raises(ValidationError):
        # In Pydantic v2, frozen=True causes a ValidationError or similar on assignment
        # Actually it's often a ValidationError or AttributeError depending on config
        metric.model = "new-model"


def test_subtask_metric_invalid_types():
    with pytest.raises(ValidationError):
        SubtaskMetric(start_time="not-a-datetime", model=123, provider="test")
