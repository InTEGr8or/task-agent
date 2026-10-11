"""Classify task-agent worktrees whose branch is merged and whose task is closed.

A worktree is safe to remove when three local signals all agree:

1. Branch merged: ``issue/<slug>`` is an ancestor of the integration branch
   (--base, default uat). ``git cherry`` additionally detects content that
   landed via cherry-pick/rebase (patch-merged); those branches need ``-D``
   because ``git branch -d`` only trusts ancestry.
2. Task closed: the task-agent store encodes status as directory location, so
   the slug under ``completed/YYYY/MM/`` (or ``deleted/``) means closed, while
   ``active/``, ``pending/``, ``draft/`` mean the worktree may still be a
   runner staging area.
3. Nothing to lose: ``git status --porcelain`` in the worktree is empty. A
   worktree whose directory is gone (prunable registration) counts as clean;
   removal uses ``git worktree prune`` for those.

Run from any project repo registered in the task-agent registry.

Usage:
    python scripts/check_task_worktree_cleanup.py            # report only
    python scripts/check_task_worktree_cleanup.py --remove   # remove safe ones
    python scripts/check_task_worktree_cleanup.py --remove --allow-patch-merged

--base defaults to the current branch of the repo it runs in.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

REGISTRY_PATH = Path.home() / ".local/share/task-agent/registry.json"
OPEN_STATUSES = ("active", "pending", "draft")
CLOSED_STATUSES = ("completed", "deleted")


def run_git(
    args: list[str], cwd: Optional[Path] = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, cwd=cwd, check=False
    )


def moniker_from_remote(url: str) -> Optional[str]:
    tail = url.removesuffix(".git")
    tail = tail.rsplit(":", 1)[-1] if ":" in tail else tail
    parts = [p for p in tail.split("/") if p]
    if len(parts) >= 2:
        return f"{parts[-2]}/{parts[-1]}"
    return None


def resolve_store(repo: Path, override: Optional[str]) -> Optional[Path]:
    if override:
        return Path(override).expanduser()
    if not REGISTRY_PATH.is_file():
        return None
    try:
        registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    entries = registry.get("stores", {})
    for entry in entries.values():
        if str(repo) in entry.get("host_paths", []):
            return Path(entry["store_path"])
    remote = run_git(["remote", "get-url", "origin"], cwd=repo).stdout.strip()
    moniker = moniker_from_remote(remote)
    if moniker and moniker in entries:
        return Path(entries[moniker]["store_path"])
    return None


def task_status(store: Path, slug: str) -> str:
    for status in OPEN_STATUSES:
        if (store / status / slug).is_dir():
            return status
    if (store / "deleted" / slug).is_dir():
        return "deleted"
    for match in (store / "completed").glob(f"*/*/{slug}"):
        if match.is_dir():
            return "completed"
    return "not-found"


def merged_state(repo: Path, branch: str, base: str) -> str:
    if run_git(["merge-base", "--is-ancestor", branch, base], cwd=repo).returncode == 0:
        return "ancestor"
    cherry = run_git(["cherry", base, branch], cwd=repo)
    if cherry.returncode == 0:
        lines = [line for line in cherry.stdout.splitlines() if line.strip()]
        if lines and all(line.startswith("-") for line in lines):
            return "patch"
    return "no"


def dirty_count(worktree: Path) -> Optional[int]:
    if not worktree.is_dir():
        return None
    proc = run_git(["status", "--porcelain"], cwd=worktree)
    return len([line for line in proc.stdout.splitlines() if line.strip()])


def issue_worktrees(repo: Path) -> list[tuple[Path, str]]:
    proc = run_git(["worktree", "list", "--porcelain"], cwd=repo)
    pairs: list[tuple[Path, str]] = []
    worktree: Optional[Path] = None
    for line in proc.stdout.splitlines():
        if line.startswith("worktree "):
            worktree = Path(line.split(" ", 1)[1])
        elif line.startswith("branch refs/heads/issue/"):
            branch = line.split(" ", 1)[1][len("refs/heads/") :]
            if worktree is not None:
                pairs.append((worktree, branch))
    return pairs


@dataclass
class Row:
    slug: str
    worktree: Path
    branch: str
    merged: str
    status: str
    dirty: Optional[int]
    verdict: str


def classify(repo: Path, store: Optional[Path], base: str) -> list[Row]:
    rows: list[Row] = []
    for worktree, branch in issue_worktrees(repo):
        slug = branch[len("issue/") :]
        merged = merged_state(repo, branch, base)
        status = task_status(store, slug) if store else "unknown-store"
        dirty = dirty_count(worktree)
        if status not in CLOSED_STATUSES:
            verdict = f"KEEP (task {status})"
        elif merged == "no":
            verdict = "REVIEW (unmerged)"
        elif dirty:
            verdict = "REVIEW (dirty)"
        elif merged == "patch":
            verdict = "REMOVE (patch-merged, -D)"
        else:
            verdict = "REMOVE"
        rows.append(Row(slug, worktree, branch, merged, status, dirty, verdict))
    return rows


def remove_row(repo: Path, row: Row, force_branch: bool) -> bool:
    if row.worktree.is_dir():
        proc = run_git(["worktree", "remove", str(row.worktree)], cwd=repo)
    else:
        proc = run_git(["worktree", "prune"], cwd=repo)
    if proc.returncode != 0:
        print(f"  worktree remove FAILED: {row.worktree}")
        return False
    delete_flag = "-D" if force_branch else "-d"
    proc = run_git(["branch", delete_flag, row.branch], cwd=repo)
    if proc.returncode != 0:
        print(f"  branch {delete_flag} FAILED: {row.branch}: {proc.stderr.strip()}")
        return False
    print(f"  removed {row.branch} ({row.worktree.name})")
    return True


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", help="integration branch (default: current branch)")
    parser.add_argument("--store", help="task-agent store path override")
    parser.add_argument(
        "--remove",
        action="store_true",
        help="remove worktrees/branches verdicted REMOVE",
    )
    parser.add_argument(
        "--allow-patch-merged",
        action="store_true",
        help="also remove patch-merged branches (deleted with -D)",
    )
    args = parser.parse_args(argv)

    toplevel = run_git(["rev-parse", "--show-toplevel"]).stdout.strip()
    if not toplevel:
        print("not a git repository")
        return 1
    repo = Path(toplevel)
    store = resolve_store(repo, args.store)
    base = (
        args.base
        or run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo).stdout.strip()
    )
    if not base:
        print("could not determine integration branch; pass --base")
        return 1
    if store is None:
        print("warning: task-agent store not found; task status unavailable")
    else:
        print(f"store: {store}")

    rows = sorted(classify(repo, store, base), key=lambda r: (r.verdict, r.slug))
    for row in rows:
        if row.dirty is None:
            dirty = "missing"
        elif row.dirty:
            dirty = f"{row.dirty} changed"
        else:
            dirty = "clean"
        print(
            f"{row.verdict:<26} merged={row.merged:<8} "
            f"task={row.status:<10} {dirty:<12} {row.branch}"
        )

    removable = [r for r in rows if r.verdict == "REMOVE"]
    patchable = [r for r in rows if r.verdict == "REMOVE (patch-merged, -D)"]
    print(
        f"\n{len(removable)} removable, {len(patchable)} patch-merged, "
        f"{len(rows) - len(removable) - len(patchable)} to keep/review"
    )
    if patchable and not args.allow_patch_merged:
        print("patch-merged branches need --allow-patch-merged (or manual -D)")

    if args.remove:
        ok = True
        for row in removable:
            ok = remove_row(repo, row, force_branch=False) and ok
        if args.allow_patch_merged:
            for row in patchable:
                ok = remove_row(repo, row, force_branch=True) and ok
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
