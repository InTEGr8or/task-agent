import hashlib
import json
import os
import re
import subprocess
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


class AuditLog:
    """Structured event log for task agent lifecycle.

    Writes one JSON object per line (JSONL) to daily files under
    ``{issues_root}/.task-agent/logs/YYYY-MM-DD.jsonl``.

    Files older than *retention_days* (default 30, configurable via
    ``TA_LOG_RETENTION_DAYS``) are pruned automatically on each write.
    """

    def __init__(self, issues_root: Path):
        self.log_dir = issues_root / ".task-agent" / "logs"
        self.retention_days = int(os.environ.get("TA_LOG_RETENTION_DAYS", "30"))

    def log(
        self,
        event: str,
        slug: str = "",
        user: str = "",
        detail: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Append a single event to today's log file."""
        self.log_dir.mkdir(parents=True, exist_ok=True)
        today = date.today().isoformat()
        path = self.log_dir / f"{today}.jsonl"

        record: Dict[str, Any] = {
            "t": datetime.now(timezone.utc).isoformat(),
            "e": event,
            "slug": slug,
            "user": user,
        }
        if detail:
            record["detail"] = detail

        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, sort_keys=True) + "\n")

        self._prune()

    def query(
        self,
        slug: Optional[str] = None,
        event: Optional[str] = None,
        since: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Read all log files, filter, return sorted by timestamp."""
        if not self.log_dir.is_dir():
            return []

        results: List[Dict[str, Any]] = []
        for path in sorted(self.log_dir.glob("*.jsonl")):
            if since and path.stem < since:
                continue
            for line in path.read_text(encoding="utf-8").strip().splitlines():
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if slug and rec.get("slug") != slug:
                    continue
                if event and rec.get("e") != event:
                    continue
                results.append(rec)

        results.sort(key=lambda r: r.get("t", ""))
        return results

    def get_active_agents(self) -> List[Dict[str, Any]]:
        """Return agents that have been created but not yet destroyed.

        Returns a dict per active slug with the latest known state.
        """
        entries = self.query()
        state: Dict[str, Dict[str, Any]] = {}

        for rec in entries:
            slug = rec.get("slug", "")
            if not slug:
                continue
            ev = rec.get("e", "")
            if ev == "agent.created":
                state[slug] = {
                    "slug": slug,
                    "user": rec.get("user", ""),
                    "detail": rec.get("detail", {}),
                }
            elif ev == "agent.destroyed":
                state.pop(slug, None)

        return list(state.values())

    def _prune(self) -> None:
        """Remove log files older than retention_days."""
        if not self.log_dir.is_dir():
            return
        cutoff = date.today()
        for path in list(self.log_dir.glob("*.jsonl")):
            try:
                file_date = date.fromisoformat(path.stem)
            except ValueError:
                continue
            if (cutoff - file_date).days > self.retention_days:
                path.unlink(missing_ok=True)


def check_user_exists(user: str) -> bool:
    """Check if a system user exists via ``getent passwd``."""
    result = subprocess.run(
        ["getent", "passwd", user],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def check_sudoers_exists(slug: str) -> bool:
    """Check if a task agent sudoers drop-in exists.

    We scan ``/etc/sudoers.d/`` for files matching ``ta-*`` that contain
    the slug-derived hash.  This avoids needing to know the exact filename.
    """
    sudoers_dir = Path("/etc/sudoers.d")
    if not sudoers_dir.is_dir():
        return False
    clean = re.sub(r"[^a-zA-Z0-9]", "", slug)[:15]
    h = hashlib.sha256(slug.encode()).hexdigest()[:8]
    pattern = f"ta-{clean}-{h}"
    # Try exact match first
    exact = sudoers_dir / pattern
    if exact.exists():
        return True
    # Fallback: scan for any file containing the slug
    for p in sudoers_dir.iterdir():
        if p.name.startswith("ta-") and p.name.endswith(f"-{h}"):
            return True
    return False


def check_worktree_exists(slug: str, root: Path) -> bool:
    """Check if the worktree exists and is a git worktree."""
    wt = root / ".gwt" / slug
    return wt.is_dir()


def agent_status_report(issues_root: Path, repo_root: Path) -> List[Dict[str, Any]]:
    """Build a cross-referenced status report for all known task agents.

    Each entry includes the audit-log state plus live-system checks.
    """
    log = AuditLog(issues_root)
    active = log.get_active_agents()

    results: List[Dict[str, Any]] = []
    for agent in active:
        slug = agent["slug"]
        user = agent["user"]
        results.append(
            {
                "slug": slug,
                "user": user,
                "user_exists": check_user_exists(user),
                "sudoers_exists": check_sudoers_exists(slug),
                "worktree_exists": check_worktree_exists(slug, repo_root),
                "template": agent.get("detail", {}).get("template", ""),
                "worktree": agent.get("detail", {}).get("worktree", ""),
            }
        )

    return results
