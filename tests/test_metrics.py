from datetime import datetime, timedelta, timezone

from taskagent.models.metric import SubtaskMetric, TokensAccuracy
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
    assert metric.tokens_accuracy == TokensAccuracy.unknown.value
    assert metric.input_tokens is None
    assert metric.agent_harness is None


def test_subtask_metric_cost_fields():
    start = datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)
    end = start + timedelta(hours=1, minutes=5)
    metric = SubtaskMetric(
        start_time=start,
        end_time=end,
        model="claude-opus-4",
        model_version="20250514",
        provider="anthropic",
        agent_harness="claude-code",
        input_tokens=120_000,
        output_tokens=8_500,
        tokens_accuracy=TokensAccuracy.estimated,
        duration_seconds=3900,
        cost=1.25,
        notes="two retries after tool error",
    )
    assert metric.total_tokens() == 128_500
    assert metric.effective_duration_seconds() == 3900
    assert metric.agent_harness == "claude-code"
    assert metric.tokens_accuracy == TokensAccuracy.estimated.value

    meta = metric.to_meta_dict()
    assert meta["model"] == "claude-opus-4"
    assert meta["model_version"] == "20250514"
    assert meta["input_tokens"] == 120_000
    assert meta["output_tokens"] == 8_500
    assert meta["total_tokens"] == 128_500
    assert meta["tokens_accuracy"] == "estimated"
    assert meta["agent_harness"] == "claude-code"
    assert meta["cost_usd"] == 1.25
    assert meta["duration_seconds"] == 3900

    md = metric.to_markdown()
    assert "## Agent Metrics" in md
    assert "claude-opus-4" in md
    assert "claude-code" in md
    assert "estimated" in md
    assert "two retries" in md


def test_effective_duration_from_timestamps():
    start = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 1, 1, 0, 10, tzinfo=timezone.utc)
    metric = SubtaskMetric(start_time=start, end_time=end, model="m", provider="p")
    assert metric.effective_duration_seconds() == 600.0


def test_from_completion_args_none_when_empty():
    assert SubtaskMetric.from_completion_args() is None
    assert SubtaskMetric.from_completion_args(tokens_accuracy="unknown") is None


def test_from_completion_args_partial():
    metric = SubtaskMetric.from_completion_args(
        model="grok-4",
        provider="xai",
        agent_harness="grok",
        input_tokens=10_000,
        output_tokens=2_000,
        tokens_accuracy="measured",
        duration_seconds=120,
        cost_usd=0.02,
        now=datetime(2026, 7, 21, 15, 0, tzinfo=timezone.utc),
    )
    assert metric is not None
    assert metric.model == "grok-4"
    assert metric.provider == "xai"
    assert metric.agent_harness == "grok"
    assert metric.input_tokens == 10_000
    assert metric.output_tokens == 2_000
    assert metric.tokens_accuracy == "measured"
    assert metric.duration_seconds == 120
    assert metric.cost == 0.02
    # start derived from duration
    assert metric.end_time is not None
    assert abs((metric.end_time - metric.start_time).total_seconds() - 120) < 0.01


def test_from_completion_args_invalid_accuracy():
    with pytest.raises(ValueError, match="tokens_accuracy"):
        SubtaskMetric.from_completion_args(model="m", tokens_accuracy="roughly")


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
