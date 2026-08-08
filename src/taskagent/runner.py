import os
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field
from transitions import Machine

from taskagent.manager import TaskAgent


class TaskCompletionResult(BaseModel):
    """Structured task completion schema with versioning and metric tracking."""

    schema_version: int = Field(default=1, description="Completion schema version")
    slug: str
    status: str = "completed"
    solution_explanation: str
    commit_hash: Optional[str] = None
    branch_name: Optional[str] = None
    files_changed: List[str] = Field(default_factory=list)

    # Usage & Cost Metrics
    agent_harness: Optional[str] = None
    model_name: Optional[str] = None
    provider: Optional[str] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    cost_usd: Optional[float] = None
    tokens_accuracy: Literal["measured", "estimated", "unknown"] = "unknown"
    duration_seconds: Optional[float] = None


class RunnerStateRecord(BaseModel):
    """Pydantic model representing the active runner state."""

    slug: str
    state: str = "init"
    worker_pid: Optional[int] = None
    worktree_path: Optional[str] = None
    agent_name: Optional[str] = None
    model_name: Optional[str] = None
    acquired_at: str
    expires_at: str


class TaskWorktreeRunner:
    """State machine runner orchestrating task execution inside .gwt/<slug> worktrees."""

    state: str
    start: Any
    finish: Any
    fail: Any
    flag_stuck: Any
    states = ["init", "running", "completed", "failed", "stuck"]

    transitions_def: List[Dict[str, Any]] = [
        {
            "trigger": "start",
            "source": "init",
            "dest": "running",
            "after": "_on_start",
        },
        {
            "trigger": "finish",
            "source": "running",
            "dest": "completed",
            "after": "_on_finish",
        },
        {
            "trigger": "fail",
            "source": "running",
            "dest": "failed",
            "after": "_on_fail",
        },
        {
            "trigger": "flag_stuck",
            "source": "running",
            "dest": "stuck",
            "after": "_on_stuck",
        },
        {
            "trigger": "reset",
            "source": ["failed", "stuck", "completed"],
            "dest": "init",
        },
    ]

    def __init__(
        self,
        manager: TaskAgent,
        slug: str,
        agent_name: Optional[str] = None,
        model_name: Optional[str] = None,
        ttl_seconds: int = 3600,
    ):
        self.manager = manager
        self.slug = manager.resolve_issue_slug(slug) or slug
        self.agent_name = agent_name
        self.model_name = model_name
        self.ttl_seconds = ttl_seconds
        self.worker_process: Optional[subprocess.Popen] = None
        self.worktree_path: Optional[Path] = None
        self.completion_result: Optional[TaskCompletionResult] = None
        self.error_message: Optional[str] = None
        self.start_time: Optional[float] = None

        self.machine = Machine(
            model=self,
            states=TaskWorktreeRunner.states,
            transitions=TaskWorktreeRunner.transitions_def,
            initial="init",
        )

    def _on_start(self):
        """Callback executed on entering 'running' state."""
        self.start_time = time.time()
        start_info = self.manager.start_issue(
            self.slug,
            agent_name=self.agent_name,
            model=self.model_name,
            ttl_seconds=self.ttl_seconds,
        )
        if start_info.get("worktree"):
            self.worktree_path = Path(start_info["worktree"])
        self.worker_process = None

    def heartbeat(self) -> Dict[str, Any]:
        """Renew TTL lease lock and verify worker process health."""
        if self.state != "running":
            raise RuntimeError(f"Cannot send heartbeat while in state '{self.state}'")

        worker_id = (
            f"{self.agent_name or 'agent'}:{self.model_name or 'default'}:"
            f"pid-{self.worker_process.pid if self.worker_process else os.getpid()}"
        )
        lease = self.manager.acquire_lease(
            self.slug,
            ttl_seconds=self.ttl_seconds,
            worker_id=worker_id,
            force=True,
        )
        return lease

    def _on_finish(self, completion: TaskCompletionResult, should_commit: bool = True):
        """Callback executed on entering 'completed' state."""
        self.completion_result = completion

        if self.start_time and not completion.duration_seconds:
            completion.duration_seconds = round(time.time() - self.start_time, 2)

        self.manager.complete_issue(
            slug=self.slug,
            solution_explanation=completion.solution_explanation,
            commit_message=f"task: complete {self.slug}",
            should_commit=should_commit,
        )
        self.manager.release_lease(self.slug)

    def _on_fail(self, error_message: str):
        """Callback executed on entering 'failed' state."""
        self.error_message = error_message
        self.manager.release_lease(self.slug)

    def _on_stuck(self, reason: str):
        """Callback executed on entering 'stuck' state."""
        self.error_message = reason
        self.manager.release_lease(self.slug)

    def get_state_record(self) -> RunnerStateRecord:
        """Return the active Pydantic state record."""
        now_dt = datetime.now(timezone.utc)
        exp_dt = now_dt + timedelta(seconds=self.ttl_seconds)

        return RunnerStateRecord(
            slug=self.slug,
            state=self.state,
            worker_pid=(self.worker_process.pid if self.worker_process else None),
            worktree_path=str(self.worktree_path) if self.worktree_path else None,
            agent_name=self.agent_name,
            model_name=self.model_name,
            acquired_at=now_dt.isoformat(),
            expires_at=exp_dt.isoformat(),
        )
