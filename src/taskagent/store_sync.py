"""Sync a task store with its git remote.

Fast-forward when one side contains the other. When histories diverge, merge
the remote and replay the op log onto the tree so a ``mission.usv`` conflict
does not drop either writer's tasks.

Rebuilding the station tree from the log alone is intentionally not what this
does. Stores that predate the log have years of edits with no op files.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from taskagent.manager import TaskAgent
from taskagent.models.issue import Issue
from taskagent.oplog import Op, list_ops

_OPEN_STATIONS = frozenset({"pending", "draft", "active"})
_INDEX_CONFLICTS = frozenset(
    {
        ".task-agent/mission.usv",
        ".task-agent/datapackage.json",
        "mission.usv",
        "datapackage.json",
    }
)


class StoreSyncError(RuntimeError):
    """Sync could not finish without losing station files."""


def _git(
    store: Path,
    *args: str,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(store), *args],
        capture_output=True,
        text=True,
        check=check,
        shell=(os.name == "nt"),
    )


def _stdout(store: Path, *args: str) -> str:
    result = _git(store, *args, check=False)
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "").strip()
        raise StoreSyncError(err or f"git {' '.join(args)} failed")
    return (result.stdout or "").strip()


def _station_of(issues_root: Path, issue_file: Path) -> str:
    rel = issue_file.resolve().relative_to(issues_root.resolve())
    return rel.parts[0]


def _task_container(issue_file: Path) -> Path:
    return issue_file.parent if issue_file.name == "README.md" else issue_file


def _dest_for(issues_root: Path, station: str, slug: str) -> Path:
    if station == "completed":
        from datetime import datetime

        now = datetime.now()
        return issues_root / "completed" / str(now.year) / f"{now.month:02d}" / slug
    return issues_root / station / slug


def _upsert_mission(
    manager: TaskAgent,
    *,
    slug: str,
    name: str,
    present: bool,
    blocked_by: Optional[List[str]] = None,
    subtask_of: Optional[str] = None,
    set_blocked: bool = False,
    set_subtask: bool = False,
) -> None:
    issues = manager.load_mission()
    kept = [issue for issue in issues if issue.slug != slug]
    if not present:
        if len(kept) != len(issues):
            manager.save_mission(kept)
        return
    current = next((issue for issue in issues if issue.slug == slug), None)
    if current is None:
        current = Issue(
            name=name or slug,
            slug=slug,
            blocked_by=list(blocked_by or []),
            subtask_of=subtask_of,
        )
    else:
        if name:
            current.name = name
        if set_blocked and blocked_by is not None:
            current.blocked_by = list(blocked_by)
        if set_subtask:
            current.subtask_of = subtask_of
    kept.append(current)
    manager.save_mission(kept)


def apply_op(manager: TaskAgent, op: Op) -> str:
    """Apply one op to the station tree. Return ``applied`` or ``noop``."""
    root = manager.issues_root
    payload = op.payload

    if op.verb == "create":
        station = str(payload.get("station") or "pending")
        if station not in _OPEN_STATIONS | {"completed", "deleted"}:
            station = "pending"
        name = str(payload.get("name") or op.slug)
        existing = manager.find_issue_file(op.slug, include_completed=True)
        if existing is None:
            body = payload.get("body")
            if not isinstance(body, str) or not body.strip():
                body = f"---\ncreated_at: {op.at}\n---\n\n# {name}\n"
            if not body.endswith("\n"):
                body += "\n"
            dest = _dest_for(root, station, op.slug)
            dest.mkdir(parents=True, exist_ok=True)
            (dest / "README.md").write_text(body, encoding="utf-8")
        if station in _OPEN_STATIONS:
            issues = manager.load_mission()
            if not any(issue.slug == op.slug for issue in issues):
                blocked = payload.get("blocked_by") or []
                create_blocked = (
                    [str(item) for item in blocked] if isinstance(blocked, list) else []
                )
                sub = payload.get("subtask_of")
                _upsert_mission(
                    manager,
                    slug=op.slug,
                    name=name,
                    present=True,
                    blocked_by=create_blocked,
                    subtask_of=str(sub) if sub else None,
                    set_blocked=True,
                    set_subtask=True,
                )
                return "applied"
        return "noop" if existing is not None else "applied"

    if op.verb == "move":
        station = str(payload.get("station") or "")
        if not station:
            raise StoreSyncError(f"move op {op.id} is missing station")
        existing = manager.find_issue_file(op.slug, include_completed=True)
        if existing is None:
            return "noop"
        if _station_of(root, existing) == station:
            return "noop"
        source = _task_container(existing)
        dest = _dest_for(root, station, source.name)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            return "noop"
        import shutil

        shutil.move(str(source), str(dest))
        _upsert_mission(
            manager,
            slug=op.slug,
            name=op.slug,
            present=station in _OPEN_STATIONS,
        )
        return "applied"

    if op.verb == "edges":
        existing = manager.find_issue_file(op.slug, include_completed=True)
        if existing is None:
            return "noop"
        content = existing.read_text(encoding="utf-8")
        blocked_by: Optional[List[str]]
        if "blocked_by" in payload:
            blocked = payload.get("blocked_by") or []
            blocked_by = (
                [str(item) for item in blocked] if isinstance(blocked, list) else []
            )
        else:
            blocked_by = None
        if "subtask_of" in payload:
            sub = payload.get("subtask_of")
            subtask: Optional[str] = str(sub) if sub else ""
            mission_sub = str(sub) if sub else None
        else:
            subtask = None
            mission_sub = None
        content = TaskAgent._write_frontmatter_edges(
            content,
            blocked_by=blocked_by,
            subtask_of=subtask,
        )
        name = str(payload.get("name") or "")
        if name:
            lines = content.splitlines(keepends=True)
            replaced = False
            for index, line in enumerate(lines):
                if line.startswith("# "):
                    lines[index] = f"# {name}\n"
                    replaced = True
                    break
            if not replaced:
                lines.append(f"\n# {name}\n")
            content = "".join(lines)
        manager._set_writable(existing, True)
        existing.write_text(content, encoding="utf-8")
        station = _station_of(root, existing)
        _upsert_mission(
            manager,
            slug=op.slug,
            name=name,
            present=station in _OPEN_STATIONS,
            blocked_by=blocked_by,
            subtask_of=mission_sub,
            set_blocked="blocked_by" in payload,
            set_subtask="subtask_of" in payload,
        )
        return "applied"

    if op.verb == "rename":
        new_slug = str(payload.get("new_slug") or "").strip()
        if not new_slug:
            raise StoreSyncError(f"rename op {op.id} is missing new_slug")
        existing = manager.find_issue_file(op.slug, include_completed=True)
        if existing is None:
            return "noop"
        source = _task_container(existing)
        dest = source.with_name(new_slug)
        if dest.exists():
            return "noop"
        import shutil

        shutil.move(str(source), str(dest))
        issues = manager.load_mission()
        for issue in issues:
            if issue.slug == op.slug:
                issue.slug = new_slug
                if payload.get("name"):
                    issue.name = str(payload["name"])
            issue.blocked_by = [
                new_slug if item == op.slug else item for item in issue.blocked_by
            ]
            if issue.subtask_of == op.slug:
                issue.subtask_of = new_slug
        manager.save_mission(issues)
        return "applied"

    if op.verb == "lease":
        existing = manager.find_issue_file(op.slug, include_completed=True)
        if existing is None:
            return "noop"
        import json

        folder = existing.parent if existing.name == "README.md" else existing.parent
        lease_path = folder / "lease.json"
        worker = str(payload.get("worker_id") or "")
        data = {"slug": op.slug, "worker_id": worker, "status": "active"}
        if payload.get("expires_at"):
            data["expires_at"] = str(payload["expires_at"])
        manager._set_writable(folder, True)
        lease_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        return "applied"

    if op.verb == "release":
        existing = manager.find_issue_file(op.slug, include_completed=True)
        if existing is None:
            return "noop"
        folder = existing.parent if existing.name == "README.md" else existing.parent
        lease_path = folder / "lease.json"
        if not lease_path.exists():
            return "noop"
        manager._set_writable(lease_path, True)
        lease_path.unlink()
        return "applied"

    return "noop"


def apply_ops(store: Path, ops: Optional[Sequence[Op]] = None) -> List[str]:
    """Replay ops onto ``store``. Missing ops are read from the store log."""
    manager = TaskAgent(config_dir=str(store))
    chosen = list(ops) if ops is not None else list_ops(store)
    return [apply_op(manager, op) for op in chosen]


def _require_clean(store: Path) -> None:
    dirty = _stdout(store, "status", "--porcelain")
    if dirty:
        raise StoreSyncError(
            "Store has uncommitted changes. Commit or stash them before ta store sync.\n"
            + dirty
        )


def _remote_ref(store: Path, remote: str = "origin") -> str:
    branch = _stdout(store, "rev-parse", "--abbrev-ref", "HEAD")
    if branch == "HEAD":
        branch = "main"
    for candidate in (f"{remote}/{branch}", f"{remote}/main", f"{remote}/master"):
        exists = _git(store, "rev-parse", "--verify", "--quiet", candidate, check=False)
        if exists.returncode == 0:
            return candidate
    raise StoreSyncError(f"No {remote} branch to sync (tried {branch}, main, master)")


def _ahead_behind(store: Path, remote_ref: str) -> tuple[int, int]:
    """Return ``(behind, ahead)`` relative to ``remote_ref``."""
    raw = _stdout(store, "rev-list", "--left-right", "--count", f"{remote_ref}...HEAD")
    left, right = raw.split()
    return int(left), int(right)


def _commit_all(store: Path, message: str) -> bool:
    _git(store, "add", "-A", check=False)
    staged = _git(store, "diff", "--cached", "--quiet", check=False)
    if staged.returncode == 0:
        return False
    _git(store, "commit", "--no-verify", "-m", message)
    return True


def sync_store(
    store: Path,
    *,
    remote: str = "origin",
    push: bool = True,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Fetch ``remote``, integrate it, materialize the op log, and push."""
    store = Path(store).resolve()
    if not (store / ".git").exists():
        raise StoreSyncError(f"Not a git store: {store}")

    remotes = _stdout(store, "remote")
    if remote not in remotes.split():
        return {
            "ok": True,
            "mode": "no_remote",
            "store": str(store),
            "detail": f"No git remote named {remote}",
        }

    _require_clean(store)
    if not dry_run:
        fetched = _git(store, "fetch", remote, "--prune", check=False)
        if fetched.returncode != 0:
            err = (fetched.stderr or fetched.stdout or "").strip()
            raise StoreSyncError(f"git fetch failed: {err}")
    else:
        _git(store, "fetch", remote, "--prune", check=False)

    remote_ref = _remote_ref(store, remote)
    behind, ahead = _ahead_behind(store, remote_ref)
    report: Dict[str, Any] = {
        "ok": True,
        "store": str(store),
        "remote_ref": remote_ref,
        "behind": behind,
        "ahead": ahead,
    }

    if behind == 0 and ahead == 0:
        report["mode"] = "in_sync"
        return report

    if dry_run:
        if behind == 0:
            report["mode"] = "would_push"
        elif ahead == 0:
            report["mode"] = "would_fast_forward"
        else:
            report["mode"] = "would_merge"
        return report

    manager = TaskAgent(config_dir=str(store))
    if manager.mission_path.exists():
        manager._set_writable(manager.mission_path, True)

    if behind == 0 and ahead > 0:
        report["mode"] = "ahead"
        if push:
            _push(store, remote)
            report["mode"] = "pushed"
        return report

    if ahead == 0 and behind > 0:
        merged = _git(store, "merge", "--ff-only", remote_ref, check=False)
        if merged.returncode != 0:
            err = (merged.stderr or merged.stdout or "").strip()
            raise StoreSyncError(f"fast-forward failed: {err}")
        report["mode"] = "fast_forward"
    else:
        _merge_diverged(store, remote_ref)
        report["mode"] = "merged"

    results = apply_ops(store)
    report["materialized"] = results.count("applied")
    if _commit_all(store, "task: materialize op log"):
        report["materialize_commit"] = True
    if push:
        _push(store, remote)
        report["pushed"] = True
    return report


def _push(store: Path, remote: str) -> None:
    pushed = _git(store, "push", "-u", remote, "HEAD", check=False)
    if pushed.returncode != 0:
        err = (pushed.stderr or pushed.stdout or "").strip()
        raise StoreSyncError(f"git push failed: {err}")


def _merge_diverged(store: Path, remote_ref: str) -> None:
    merged = _git(store, "merge", "--no-commit", "--no-ff", remote_ref, check=False)
    if merged.returncode == 0:
        _commit_all(store, "task: sync op log")
        return

    conflicts = _stdout(store, "diff", "--name-only", "--diff-filter=U")
    paths = [line.strip() for line in conflicts.splitlines() if line.strip()]
    unexpected = [path for path in paths if path not in _INDEX_CONFLICTS]
    if unexpected:
        _git(store, "merge", "--abort", check=False)
        raise StoreSyncError(
            "Sync merge conflicted outside the mission index: " + ", ".join(unexpected)
        )
    for path in paths:
        _git(store, "checkout", "--ours", "--", path, check=False)
        _git(store, "add", "--", path, check=False)
    _commit_all(store, "task: sync op log")
