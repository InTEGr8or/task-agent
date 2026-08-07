"""Tests for performance monitoring logging module."""

import pytest
from unittest.mock import MagicMock

from taskagent.perf import (
    PerfLogger,
    is_perf_logging_enabled,
    set_perf_logging_enabled,
    perf_timer,
    perf_trace,
    notify_perf_logging_if_enabled,
    ENV_VAR_PERF_LOG,
)
from taskagent.cli import cmd_perf


def test_perf_logging_toggle(monkeypatch):
    monkeypatch.delenv(ENV_VAR_PERF_LOG, raising=False)
    assert not is_perf_logging_enabled()

    set_perf_logging_enabled(True)
    assert is_perf_logging_enabled()

    set_perf_logging_enabled(False)
    assert not is_perf_logging_enabled()


def test_perf_logger_log_metric(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_VAR_PERF_LOG, "1")
    logger = PerfLogger(issues_root=tmp_path)
    logger.log_metric("test_op", 12.34, details={"count": 5})

    metrics = logger.get_recent_metrics()
    assert len(metrics) == 1
    assert metrics[0]["operation"] == "test_op"
    assert metrics[0]["duration_ms"] == 12.34
    assert metrics[0]["details"] == {"count": 5}


def test_perf_timer_context_manager(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_VAR_PERF_LOG, "1")
    logger = PerfLogger(issues_root=tmp_path)

    with perf_timer("timer_op", issues_root=tmp_path):
        _ = sum(range(1000))

    metrics = logger.get_recent_metrics()
    assert len(metrics) == 1
    assert metrics[0]["operation"] == "timer_op"
    assert metrics[0]["duration_ms"] >= 0


def test_perf_trace_decorator(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_VAR_PERF_LOG, "1")

    @perf_trace("decorated_op")
    def sample_func():
        return 42

    result = sample_func()
    assert result == 42


def test_notify_perf_logging_banner(tmp_path, monkeypatch):
    mock_console = MagicMock()

    monkeypatch.setenv(ENV_VAR_PERF_LOG, "0")
    notify_perf_logging_if_enabled(mock_console, tmp_path)
    mock_console.print.assert_not_called()

    monkeypatch.setenv(ENV_VAR_PERF_LOG, "1")
    notify_perf_logging_if_enabled(mock_console, tmp_path)
    mock_console.print.assert_called_once()
    assert (
        "Performance monitoring logging is ACTIVE" in mock_console.print.call_args[0][0]
    )


@pytest.fixture
def manager(tmp_path):
    from taskagent.manager import TaskAgent

    return TaskAgent(config_dir=str(tmp_path / "docs" / "tasks"))


def test_cmd_perf(manager, monkeypatch):
    mock_console = MagicMock()
    cmd_perf(mock_console, manager, action="status")
    mock_console.print.assert_called()

    cmd_perf(mock_console, manager, action="on")
    assert is_perf_logging_enabled()

    cmd_perf(mock_console, manager, action="off")
    assert not is_perf_logging_enabled()
