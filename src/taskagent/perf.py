"""Performance monitoring logging module for Task Agent."""

from contextlib import contextmanager
from datetime import datetime
import json
import os
from pathlib import Path
import time
from typing import Any, Callable, Dict, List, Optional


ENV_VAR_PERF_LOG = "TA_PERF_LOG"


def is_perf_logging_enabled() -> bool:
    """Check if performance monitoring logging is enabled via environment variable."""
    val = os.environ.get(ENV_VAR_PERF_LOG, "").strip().lower()
    return val in ("1", "true", "yes", "on", "enabled")


def set_perf_logging_enabled(enabled: bool) -> None:
    """Set the environment variable for performance monitoring logging."""
    os.environ[ENV_VAR_PERF_LOG] = "1" if enabled else "0"


class PerfLogger:
    """Structured performance monitoring logger for operations and timing metrics."""

    def __init__(self, issues_root: Optional[Path] = None):
        if issues_root is None:
            issues_root = Path.cwd()
        self.issues_root = Path(issues_root)
        self.log_dir = self.issues_root / ".task-agent" / "logs"

    def log_metric(
        self,
        operation: str,
        duration_ms: float,
        details: Optional[Dict[str, Any]] = None,
        success: bool = True,
    ) -> None:
        """Record a performance metric event to the daily jsonl log."""
        if not is_perf_logging_enabled():
            return

        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            now = datetime.now()
            today = now.strftime("%Y-%m-%d")
            log_file = self.log_dir / f"perf-{today}.jsonl"

            entry = {
                "timestamp": now.isoformat(),
                "operation": operation,
                "duration_ms": round(duration_ms, 2),
                "success": success,
                "details": details or {},
            }

            with log_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception:
            pass

    def get_recent_metrics(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Retrieve recent performance metrics from log files."""
        if not self.log_dir.is_dir():
            return []

        entries = []
        for path in sorted(self.log_dir.glob("perf-*.jsonl"), reverse=True):
            try:
                with path.open("r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            entries.append(json.loads(line))
            except Exception:
                continue

        entries.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return entries[:limit]


_DEFAULT_LOGGER: Optional[PerfLogger] = None


def get_perf_logger(issues_root: Optional[Path] = None) -> PerfLogger:
    """Get or instantiate a PerfLogger singleton/instance."""
    global _DEFAULT_LOGGER
    if issues_root is not None:
        return PerfLogger(issues_root)
    if _DEFAULT_LOGGER is None:
        _DEFAULT_LOGGER = PerfLogger()
    return _DEFAULT_LOGGER


@contextmanager
def perf_timer(
    operation: str,
    details: Optional[Dict[str, Any]] = None,
    issues_root: Optional[Path] = None,
):
    """Context manager to measure and log operation duration."""
    start_time = time.perf_counter()
    success = True
    try:
        yield
    except Exception:
        success = False
        raise
    finally:
        elapsed_ms = (time.perf_counter() - start_time) * 1000.0
        if is_perf_logging_enabled():
            logger = get_perf_logger(issues_root)
            logger.log_metric(operation, elapsed_ms, details=details, success=success)


def perf_trace(operation: Optional[str] = None):
    """Decorator to trace function performance timing."""

    def decorator(func: Callable):
        op_name = operation or func.__qualname__

        def wrapper(*args, **kwargs):
            start = time.perf_counter()
            success = True
            try:
                return func(*args, **kwargs)
            except Exception:
                success = False
                raise
            finally:
                elapsed_ms = (time.perf_counter() - start) * 1000.0
                if is_perf_logging_enabled():
                    logger = get_perf_logger()
                    logger.log_metric(op_name, elapsed_ms, success=success)

        return wrapper

    return decorator


def notify_perf_logging_if_enabled(
    console: Any, issues_root: Optional[Path] = None
) -> None:
    """Print notification banner if performance monitoring logging is active."""
    if is_perf_logging_enabled():
        logger = get_perf_logger(issues_root)
        console.print(
            f"[dim cyan]⚡ Performance monitoring logging is ACTIVE (TA_PERF_LOG=1). Logs: {logger.log_dir}[/dim cyan]"
        )
