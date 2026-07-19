"""Machine-level task store data root, monikers, registry, and migration.

Phases:
  1. Data root, moniker, registry (read-only inspect)
  2. ``migrate_store`` — move legacy in-host stores into the data root
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

REGISTRY_VERSION = 1
STORE_META_REL = Path(".task-agent") / "store.json"

# Files/dirs that indicate a real station store (not an empty placeholder).
_STORE_MARKERS = (
    Path(".task-agent") / "mission.usv",
    Path("mission.usv"),
    Path("pending"),
    Path("active"),
    Path("draft"),
    Path("completed"),
)


def get_data_root() -> Path:
    """Return the machine-level task-agent data root.

    Resolution order:
    1. ``TA_DATA_ROOT`` environment variable
    2. ``$XDG_DATA_HOME/task-agent`` when XDG_DATA_HOME is set
    3. ``~/.local/share/task-agent``
    """
    override = os.environ.get("TA_DATA_ROOT")
    if override:
        return Path(override).expanduser().resolve()

    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return (Path(xdg).expanduser() / "task-agent").resolve()

    return (Path.home() / ".local" / "share" / "task-agent").resolve()


def get_stores_dir(data_root: Optional[Path] = None) -> Path:
    """Return the directory that holds per-project store folders."""
    root = data_root if data_root is not None else get_data_root()
    return root / "stores"


def moniker_from_remote(url: str) -> str:
    """Derive a stable moniker from a git remote URL.

    Examples:
        git@github.com:bizkite-co/stations.git -> bizkite-co/stations
        https://github.com/InTEGr8or/task-agent.git -> InTEGr8or/task-agent
        ssh://git@gitlab.com/group/sub/repo.git -> group/sub/repo
    """
    if not url or not url.strip():
        raise ValueError("Empty remote URL")

    raw = url.strip()

    # scp-like: git@host:path/to/repo.git
    if "://" not in raw and re.match(r"^[^/\s]+@[^:\s]+:.+", raw):
        path = raw.split(":", 1)[1]
    else:
        # Normalize git@host:path already handled; support ssh:// and https://
        parsed = urlparse(raw if "://" in raw else f"ssh://{raw}")
        path = parsed.path or ""
        # urlparse("ssh://git@host/owner/repo") puts host correctly
        if not path and "@" in raw and ":" in raw:
            path = raw.rsplit(":", 1)[-1]

    path = path.lstrip("/")
    if path.endswith(".git"):
        path = path[: -len(".git")]
    path = path.strip("/")

    if not path:
        raise ValueError(f"Could not parse moniker from remote URL: {url!r}")

    return path


def moniker_to_dir_name(moniker: str) -> str:
    """Map a moniker to a single filesystem directory name under stores/."""
    name = moniker.strip().strip("/")
    # Collapse path separators and unsafe characters
    name = re.sub(r"[/\\]+", "_", name)
    name = re.sub(r"[^\w.\-@+]+", "_", name, flags=re.UNICODE)
    name = re.sub(r"_+", "_", name).strip("._")
    if not name:
        raise ValueError(f"Moniker produced empty directory name: {moniker!r}")
    return name


def moniker_from_path(path: Path) -> str:
    """Derive a moniker for a non-repo (or remote-less) host path.

    Uses a path-stable form so the same folder re-registers consistently.
    """
    resolved = path.expanduser().resolve()
    # Stable across processes (do not use built-in hash(); it is salted per process)
    digest = hashlib.sha256(str(resolved).encode("utf-8")).hexdigest()[:8]
    safe_name = re.sub(r"[^\w.\-]+", "-", resolved.name, flags=re.UNICODE).strip("-")
    if not safe_name:
        safe_name = "folder"
    return f"local/{safe_name}-{digest}"


def store_path_for_moniker(moniker: str, data_root: Optional[Path] = None) -> Path:
    """Return the canonical store directory for a moniker under the data root."""
    return get_stores_dir(data_root) / moniker_to_dir_name(moniker)


def git_remote_url(repo_path: Path, remote: str = "origin") -> Optional[str]:
    """Return the URL for ``remote`` if ``repo_path`` is inside a git worktree."""
    try:
        res = subprocess.run(
            ["git", "-C", str(repo_path), "remote", "get-url", remote],
            capture_output=True,
            text=True,
            check=True,
            shell=(os.name == "nt"),
        )
        url = res.stdout.strip()
        return url or None
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def git_toplevel(path: Path) -> Optional[Path]:
    """Return the git toplevel for ``path``, or None if not in a repository."""
    try:
        res = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
            shell=(os.name == "nt"),
        )
        return Path(res.stdout.strip())
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def resolve_moniker_for_host(host_path: Path) -> tuple[str, Optional[str]]:
    """Resolve (moniker, origin_url_or_none) for a host project path.

    Prefers origin remote; falls back to path-derived moniker.
    """
    host = host_path.expanduser().resolve()
    top = git_toplevel(host) or host
    origin = git_remote_url(top)
    if origin:
        try:
            return moniker_from_remote(origin), origin
        except ValueError:
            pass
    return moniker_from_path(top), origin


def detect_legacy_store(host_path: Path) -> Optional[Path]:
    """Locate a legacy in-host task store if present.

    Checks, in order:
    - ``{host}/.task-agent/tasks`` (current eject target)
    - ``{host}/docs/tasks`` when it is a real directory (not only a broken link)
    """
    host = host_path.expanduser().resolve()
    candidates = [
        host / ".task-agent" / "tasks",
        host / "docs" / "tasks",
        host / "docks" / "tasks",
    ]
    for cand in candidates:
        if cand.is_dir() and not cand.is_symlink():
            return cand.resolve()
        if cand.is_symlink():
            try:
                target = cand.resolve()
                if target.is_dir():
                    return target
            except OSError:
                continue
    return None


def is_nested_git_repo(path: Path) -> bool:
    """True if ``path`` is the root of its own git repository (not the host)."""
    top = git_toplevel(path)
    if top is None:
        return False
    try:
        return top.resolve() == path.expanduser().resolve()
    except OSError:
        return False


def read_store_meta(store_path: Path) -> Optional[Dict[str, Any]]:
    """Read ``.task-agent/store.json`` from a store, if present."""
    meta_path = store_path / STORE_META_REL
    if not meta_path.is_file():
        return None
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def write_store_meta(
    store_path: Path,
    moniker: str,
    remote: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Path:
    """Write store identity metadata inside the store (source for registry rebuild)."""
    meta_path = store_path / STORE_META_REL
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    payload: Dict[str, Any] = {
        "version": REGISTRY_VERSION,
        "moniker": moniker,
    }
    if remote:
        payload["remote"] = remote
    if extra:
        payload.update(extra)
    # Atomic replace
    tmp = meta_path.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    tmp.replace(meta_path)
    return meta_path


@dataclass
class StoreEntry:
    """One registered project → store binding."""

    moniker: str
    store_path: str
    host_paths: List[str] = field(default_factory=list)
    remote: Optional[str] = None
    registered_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        # Drop Nones for cleaner JSON
        return {k: v for k, v in data.items() if v is not None}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StoreEntry":
        return cls(
            moniker=data["moniker"],
            store_path=data["store_path"],
            host_paths=list(data.get("host_paths") or []),
            remote=data.get("remote"),
            registered_at=data.get("registered_at"),
        )


class MachineRegistry:
    """Machine registry of moniker → store root.

    The registry file is a rebuildable *index* over ``stores/`` metadata plus
    optional log-grade ``host_paths`` that may not be discoverable by scan alone.
    Writes use atomic replace.
    """

    def __init__(self, data_root: Optional[Path] = None):
        self.data_root = (
            data_root.expanduser().resolve()
            if data_root is not None
            else get_data_root()
        )
        self.registry_path = self.data_root / "registry.json"
        self.stores_dir = get_stores_dir(self.data_root)

    def ensure_layout(self) -> None:
        """Create data root and stores/ if missing (does not create a store)."""
        self.stores_dir.mkdir(parents=True, exist_ok=True)

    def load(self) -> Dict[str, StoreEntry]:
        """Load moniker → StoreEntry map. Missing file → empty."""
        if not self.registry_path.is_file():
            return {}
        try:
            raw = json.loads(self.registry_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        stores = raw.get("stores") or {}
        result: Dict[str, StoreEntry] = {}
        for moniker, entry in stores.items():
            if not isinstance(entry, dict):
                continue
            # moniker key wins if body omits it
            body = {**entry, "moniker": entry.get("moniker") or moniker}
            try:
                result[body["moniker"]] = StoreEntry.from_dict(body)
            except KeyError:
                continue
        return result

    def save(self, entries: Dict[str, StoreEntry]) -> None:
        """Atomically write the full registry."""
        self.ensure_layout()
        payload = {
            "version": REGISTRY_VERSION,
            "stores": {
                moniker: entry.to_dict()
                for moniker, entry in sorted(entries.items(), key=lambda kv: kv[0])
            },
        }
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.registry_path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        tmp.replace(self.registry_path)

    def get(self, moniker: str) -> Optional[StoreEntry]:
        return self.load().get(moniker)

    def find_by_host_path(self, host_path: Path) -> Optional[StoreEntry]:
        """Find an entry whose host_paths contains this path (or a parent)."""
        resolved = host_path.expanduser().resolve()
        best: Optional[StoreEntry] = None
        best_len = -1
        for entry in self.load().values():
            for hp in entry.host_paths:
                try:
                    p = Path(hp).expanduser().resolve()
                except OSError:
                    continue
                if resolved == p or resolved.is_relative_to(p):
                    if len(str(p)) > best_len:
                        best = entry
                        best_len = len(str(p))
        return best

    def upsert(self, entry: StoreEntry) -> StoreEntry:
        """Insert or update an entry by moniker; merges host_paths."""
        entries = self.load()
        existing = entries.get(entry.moniker)
        if existing:
            hosts = list(dict.fromkeys([*existing.host_paths, *entry.host_paths]))
            merged = StoreEntry(
                moniker=entry.moniker,
                store_path=entry.store_path or existing.store_path,
                host_paths=hosts,
                remote=entry.remote if entry.remote is not None else existing.remote,
                registered_at=existing.registered_at or entry.registered_at,
            )
            entries[entry.moniker] = merged
            result = merged
        else:
            if not entry.registered_at:
                entry.registered_at = datetime.now(timezone.utc).isoformat()
            entries[entry.moniker] = entry
            result = entry
        self.save(entries)
        return result

    def list_entries(self) -> List[StoreEntry]:
        return [self.load()[k] for k in sorted(self.load())]

    def rebuild_from_stores(self) -> Dict[str, StoreEntry]:
        """Rebuild index fields by scanning ``stores/``.

        Preserves existing ``host_paths`` and ``registered_at`` when moniker
        already known (log-grade fields). Drops monikers whose store dirs are
        gone unless they only had host_paths — actually gone stores are removed
        from the index (rebuildable index discipline).
        """
        previous = self.load()
        rebuilt: Dict[str, StoreEntry] = {}

        if self.stores_dir.is_dir():
            for child in sorted(self.stores_dir.iterdir()):
                if not child.is_dir():
                    continue
                meta = read_store_meta(child)
                moniker: Optional[str] = None
                remote: Optional[str] = None
                if meta and meta.get("moniker"):
                    moniker = str(meta["moniker"])
                    remote = meta.get("remote")
                else:
                    # Fallback: nested git origin, else directory name as moniker
                    remote = git_remote_url(child)
                    if remote:
                        try:
                            moniker = moniker_from_remote(remote)
                        except ValueError:
                            moniker = child.name
                    else:
                        moniker = child.name.replace("_", "/", 1)

                assert moniker is not None
                prev = previous.get(moniker)
                rebuilt[moniker] = StoreEntry(
                    moniker=moniker,
                    store_path=str(child.resolve()),
                    host_paths=list(prev.host_paths) if prev else [],
                    remote=remote or (prev.remote if prev else None),
                    registered_at=prev.registered_at if prev else None,
                )

        self.save(rebuilt)
        return rebuilt


def _list_git_remotes(repo_path: Path) -> Dict[str, str]:
    """Return ``{remote_name: url}`` for fetch URLs (empty if not a repo)."""
    try:
        res = subprocess.run(
            ["git", "-C", str(repo_path), "remote", "-v"],
            capture_output=True,
            text=True,
            check=True,
            shell=(os.name == "nt"),
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return {}
    remotes: Dict[str, str] = {}
    for line in res.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[-1] == "(fetch)":
            remotes[parts[0]] = parts[1]
    return remotes


def _path_is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def looks_like_store(path: Path) -> bool:
    """True if ``path`` has station/mission markers."""
    if not path.is_dir():
        return False
    for rel in _STORE_MARKERS:
        if (path / rel).exists():
            return True
    return False


def verify_store(
    store_path: Path, *, remotes_expected: Optional[Dict[str, str]] = None
) -> List[str]:
    """Return a list of verification errors (empty = ok)."""
    errors: List[str] = []
    if not store_path.is_dir():
        return [f"Store path is not a directory: {store_path}"]
    if not looks_like_store(store_path):
        errors.append(
            f"Store lacks mission/station markers under {store_path} "
            f"(expected mission.usv or pending/active/draft/completed)"
        )
    if remotes_expected is not None:
        actual = _list_git_remotes(store_path)
        for name, url in remotes_expected.items():
            if actual.get(name) != url:
                errors.append(
                    f"Remote {name!r} mismatch: expected {url!r}, got {actual.get(name)!r}"
                )
    return errors


def _update_env_var(env_path: Path, key: str, value: str) -> None:
    """Set key=value in a .env file (create or replace)."""
    if not env_path.exists():
        env_path.write_text(f"{key}={value}\n", encoding="utf-8")
        return
    lines = env_path.read_text(encoding="utf-8").splitlines()
    found = False
    for i, line in enumerate(lines):
        if line.strip().startswith(f"{key}="):
            lines[i] = f"{key}={value}"
            found = True
            break
    if not found:
        lines.append(f"{key}={value}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _replace_with_symlink(link_path: Path, target: Path) -> None:
    """Make ``link_path`` an absolute symlink to ``target`` (replace existing)."""
    target_abs = str(target.resolve())
    if link_path.is_symlink() or link_path.is_file():
        link_path.unlink()
    elif link_path.is_dir():
        # Only remove empty dirs; callers must have moved contents already
        try:
            link_path.rmdir()
        except OSError as e:
            raise RuntimeError(
                f"Cannot replace non-empty directory with symlink: {link_path}"
            ) from e
    link_path.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(target_abs, str(link_path))


def _count_entries(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for _ in path.rglob("*"))


@dataclass
class MigrationPlan:
    """Describes a migrate operation before/without applying it."""

    host_path: str
    moniker: str
    source: Optional[str]
    destination: str
    kind: Optional[str]  # nested_git | host_tree | already_migrated | none
    remotes_before: Dict[str, str] = field(default_factory=dict)
    subject_origin: Optional[str] = (
        None  # host code remote (identity), not always store remote
    )
    already_migrated: bool = False
    steps: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def write_host_store_config(host_path: Path, moniker: str) -> Path:
    """Write/update ``.ta-config.json`` with ``store_moniker`` for rename-resilient binding.

    This is the greppable host-side pointer: moniker identity survives path moves
    and outlives a GitHub rename until ``ta store rebind`` is run.
    """
    host = host_path.expanduser().resolve()
    path = host / ".ta-config.json"
    data: Dict[str, Any] = {}
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                data = raw
        except (OSError, json.JSONDecodeError):
            data = {}
    data["store_moniker"] = moniker
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


@dataclass
class MigrationResult:
    plan: MigrationPlan
    dry_run: bool
    success: bool
    message: str
    applied_steps: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plan": self.plan.to_dict(),
            "dry_run": self.dry_run,
            "success": self.success,
            "message": self.message,
            "applied_steps": self.applied_steps,
        }


def plan_migrate(host_path: Path, data_root: Optional[Path] = None) -> MigrationPlan:
    """Build a migration plan for the host project (no side effects)."""
    host = host_path.expanduser().resolve()
    top = git_toplevel(host) or host
    moniker, subject_origin = resolve_moniker_for_host(top)
    root = data_root if data_root is not None else get_data_root()
    dest = store_path_for_moniker(moniker, root)
    steps: List[str] = []
    warnings: List[str] = []
    errors: List[str] = []
    if subject_origin:
        steps.append(f"Subject host origin (identity): {subject_origin}")

    # Prefer the physical eject location as the source to move.
    eject_path = top / ".task-agent" / "tasks"
    source: Optional[Path] = None
    kind: Optional[str] = None

    if eject_path.is_symlink():
        try:
            target = eject_path.resolve()
        except OSError:
            target = None
        if target is not None and target.resolve() == dest.resolve() and dest.is_dir():
            return MigrationPlan(
                host_path=str(top),
                moniker=moniker,
                source=str(eject_path),
                destination=str(dest),
                kind="already_migrated",
                already_migrated=True,
                subject_origin=subject_origin,
                steps=["No-op: .task-agent/tasks already symlinks to canonical store"],
            )
        if target is not None and target.is_dir() and looks_like_store(target):
            # Symlink points elsewhere (old custom eject) — migrate that target
            source = target
    elif eject_path.is_dir() and looks_like_store(eject_path):
        source = eject_path.resolve()

    if source is None:
        # Fall back to docs/tasks only if it is a real directory (not symlink)
        docs = top / "docs" / "tasks"
        if docs.is_dir() and not docs.is_symlink() and looks_like_store(docs):
            source = docs.resolve()
            warnings.append(
                "Source is docs/tasks (in-tree); prefer eject layout for new projects"
            )

    if source is None:
        # Maybe already only at canonical
        if dest.is_dir() and looks_like_store(dest):
            return MigrationPlan(
                host_path=str(top),
                moniker=moniker,
                source=None,
                destination=str(dest),
                kind="already_migrated",
                already_migrated=True,
                subject_origin=subject_origin,
                steps=[
                    "No-op: canonical store already exists; no in-host source to move"
                ],
                warnings=["Consider repairing host symlinks with another migrate run"],
            )
        return MigrationPlan(
            host_path=str(top),
            moniker=moniker,
            source=None,
            destination=str(dest),
            kind="none",
            subject_origin=subject_origin,
            errors=[
                "No legacy task store found under host (.task-agent/tasks or docs/tasks)"
            ],
        )

    # If source is already the destination, done
    if source.resolve() == dest.resolve():
        return MigrationPlan(
            host_path=str(top),
            moniker=moniker,
            source=str(source),
            destination=str(dest),
            kind="already_migrated",
            already_migrated=True,
            steps=["No-op: source is already the canonical store path"],
        )

    nested = is_nested_git_repo(source)
    kind = "nested_git" if nested else "host_tree"
    # Always inspect remotes on the source path (may walk to host for host_tree)
    raw_remotes = _list_git_remotes(source)
    if nested:
        remotes_before = raw_remotes
        if remotes_before:
            steps.append(f"Preserve nested store remotes: {remotes_before}")
        else:
            warnings.append("Nested git store has no remotes configured")
    else:
        # host_tree: remotes belong to the host worktree, not a dedicated tasks repo
        remotes_before = {}
        if raw_remotes:
            warnings.append(
                f"Source is host_tree (no nested .git). Visible remotes {raw_remotes} "
                "belong to the subject host repo and will NOT be copied as store remotes. "
                "After migrate: `ta store remote suggest` / `ta store remote set <url>`."
            )
        steps.append("git init store without inventing a remote (host_tree)")

    # Destination conflicts
    if dest.exists():
        if dest.is_dir() and looks_like_store(dest):
            # Same moniker store already present — only repair pointers if content matches
            errors.append(
                f"Destination already exists and looks like a store: {dest}. "
                "Refusing to overwrite. Remove or rename it, or fix host pointers manually."
            )
        elif dest.is_dir() and any(dest.iterdir()):
            errors.append(f"Destination exists and is non-empty: {dest}")
        elif dest.is_file() or dest.is_symlink():
            errors.append(
                f"Destination path exists and is not a free directory: {dest}"
            )

    if not looks_like_store(source):
        errors.append(f"Source does not look like a task store: {source}")

    steps.append(f"Create parent directory {dest.parent}")
    if nested:
        steps.append(
            f"Move nested git store {source} → {dest} (preserve .git and remotes)"
        )
        if remotes_before:
            steps.append(f"Verify remotes after move: {remotes_before}")
    else:
        steps.append(f"Move host_tree store {source} → {dest}")
        steps.append("Create initial commit of station tree")

    steps.append("Write .task-agent/store.json moniker metadata (+ subject_origin)")
    steps.append(f"Write host .ta-config.json store_moniker={moniker}")
    steps.append("Register moniker in machine registry.json")
    steps.append(f"Point {eject_path} symlink → {dest}")
    steps.append(f"Point docs/tasks (and docks/tasks if present) → {dest}")
    steps.append("Update .env TA_EJECT_TASKS / TA_EJECTED_TASKS_PATH to destination")
    steps.append("Verify store markers (and remotes if nested_git)")

    if _path_is_under(dest, top):
        warnings.append(
            "Destination is under the host tree; prefer TA_DATA_ROOT outside the repo"
        )

    return MigrationPlan(
        host_path=str(top),
        moniker=moniker,
        source=str(source),
        destination=str(dest),
        kind=kind,
        remotes_before=remotes_before,
        subject_origin=subject_origin,
        already_migrated=False,
        steps=steps,
        warnings=warnings,
        errors=errors,
    )


def _git_init_and_commit(store_path: Path, message: str) -> None:
    subprocess.run(
        ["git", "-C", str(store_path), "init"],
        check=True,
        capture_output=True,
        shell=(os.name == "nt"),
    )
    subprocess.run(
        ["git", "-C", str(store_path), "add", "-A"],
        check=True,
        capture_output=True,
        shell=(os.name == "nt"),
    )
    # Allow empty? No — store should have files
    env = os.environ.copy()
    # Avoid depending on user identity in tests
    env.setdefault("GIT_AUTHOR_NAME", "task-agent")
    env.setdefault("GIT_AUTHOR_EMAIL", "task-agent@localhost")
    env.setdefault("GIT_COMMITTER_NAME", env["GIT_AUTHOR_NAME"])
    env.setdefault("GIT_COMMITTER_EMAIL", env["GIT_AUTHOR_EMAIL"])
    subprocess.run(
        ["git", "-C", str(store_path), "commit", "-m", message],
        check=True,
        capture_output=True,
        text=True,
        env=env,
        shell=(os.name == "nt"),
    )


def _move_store_tree(source: Path, dest: Path) -> None:
    """Move source directory to dest (same-filesystem rename when possible)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        raise RuntimeError(f"Destination already exists: {dest}")
    shutil.move(str(source), str(dest))


def _update_host_pointers(host: Path, dest: Path) -> List[str]:
    """Leave eject/docs symlinks and .env pointing at the centralized store."""
    applied: List[str] = []
    dest_abs = dest.resolve()

    eject = host / ".task-agent" / "tasks"
    # After move, eject may be gone (if it was the source) or a stale symlink
    if eject.exists() or eject.is_symlink():
        if eject.is_symlink():
            eject.unlink()
        elif eject.is_dir():
            # Should be empty after move of contents... if source was eject itself,
            # shutil.move removed it. If residual empty dir, replace.
            if any(eject.iterdir()):
                raise RuntimeError(
                    f"Legacy path still has contents after move: {eject}"
                )
            eject.rmdir()
    _replace_with_symlink(eject, dest_abs)
    applied.append(f"symlink {eject} → {dest_abs}")

    for rel in (Path("docs") / "tasks", Path("docks") / "tasks"):
        link = host / rel
        if link.exists() or link.is_symlink():
            if link.is_symlink():
                link.unlink()
            elif link.is_dir():
                # Only re-point if empty (content should have been source already)
                if any(link.iterdir()):
                    # Leave alone if still has content (unexpected)
                    applied.append(f"skipped non-empty {link}")
                    continue
                link.rmdir()
            else:
                link.unlink()
            _replace_with_symlink(link, dest_abs)
            applied.append(f"symlink {link} → {dest_abs}")
        elif (host / rel.parent).is_dir():
            # docs/ exists but tasks missing — create heal symlink
            _replace_with_symlink(link, dest_abs)
            applied.append(f"symlink {link} → {dest_abs}")

    env_path = host / ".env"
    _update_env_var(env_path, "TA_EJECT_TASKS", "true")
    _update_env_var(env_path, "TA_EJECTED_TASKS_PATH", str(dest_abs))
    _update_env_var(env_path, "TA_EJECTED_ISSUES_PATH", str(dest_abs))
    applied.append(f"update {env_path} eject paths → {dest_abs}")

    return applied


def migrate_store(
    host_path: Path,
    *,
    dry_run: bool = False,
    data_root: Optional[Path] = None,
) -> MigrationResult:
    """Migrate a host project's legacy task store into the machine data root.

    Safe defaults:
    - Refuses to overwrite an existing destination store
    - Verifies markers (and nested remotes) before considering success
    - Does **not** invent a git remote for host_tree stores
    - Leaves host symlinks + .env so pre-Phase-3 discovery still works

    Args:
        host_path: Project root (or any path inside it).
        dry_run: If True, only return the plan; no filesystem changes.
        data_root: Override machine data root (tests).
    """
    plan = plan_migrate(host_path, data_root=data_root)

    if plan.errors:
        return MigrationResult(
            plan=plan,
            dry_run=dry_run,
            success=False,
            message="; ".join(plan.errors),
        )

    if plan.already_migrated:
        # Still repair pointers if needed (non-dry-run)
        if dry_run:
            return MigrationResult(
                plan=plan,
                dry_run=True,
                success=True,
                message="Already migrated (dry-run)",
            )
        host = Path(plan.host_path)
        dest = Path(plan.destination)
        applied: List[str] = []
        if dest.is_dir() and looks_like_store(dest):
            applied.extend(_update_host_pointers(host, dest))
            write_host_store_config(host, plan.moniker)
            applied.append(f"wrote {host / '.ta-config.json'} store_moniker")
            # Ensure subject_origin is recorded if missing
            meta = read_store_meta(dest) or {}
            if plan.subject_origin and not meta.get("subject_origin"):
                write_store_meta(
                    dest,
                    moniker=plan.moniker,
                    remote=meta.get("remote") or git_remote_url(dest),
                    extra={**meta, "subject_origin": plan.subject_origin},
                )
                applied.append("recorded subject_origin in store.json")
            reg = MachineRegistry(data_root)
            reg.upsert(
                StoreEntry(
                    moniker=plan.moniker,
                    store_path=str(dest.resolve()),
                    host_paths=[str(host.resolve())],
                    remote=git_remote_url(dest),
                )
            )
            applied.append("registry upsert")
        return MigrationResult(
            plan=plan,
            dry_run=False,
            success=True,
            message="Already migrated; host pointers refreshed",
            applied_steps=applied,
        )

    if plan.kind == "none" or not plan.source:
        return MigrationResult(
            plan=plan,
            dry_run=dry_run,
            success=False,
            message=plan.errors[0] if plan.errors else "Nothing to migrate",
        )

    if dry_run:
        return MigrationResult(
            plan=plan,
            dry_run=True,
            success=True,
            message="Dry-run OK — no changes applied",
            applied_steps=list(plan.steps),
        )

    source = Path(plan.source)
    dest = Path(plan.destination)
    host = Path(plan.host_path)
    applied = []

    # Snapshot for rollback
    source_count = _count_entries(source)
    remotes_expected = dict(plan.remotes_before) if plan.kind == "nested_git" else None

    try:
        # If source is behind a symlink at eject path pointing outside,
        # we move the real directory; eject path becomes a dangling link then.
        eject = host / ".task-agent" / "tasks"
        source_was_eject_dir = (
            eject.exists()
            and not eject.is_symlink()
            and eject.resolve() == source.resolve()
        )

        _move_store_tree(source, dest)
        applied.append(f"moved {source} → {dest}")

        if plan.kind == "host_tree":
            _git_init_and_commit(
                dest,
                "chore: initial task store commit after centralization migrate",
            )
            applied.append("git init + initial commit (no remote)")

        write_store_meta(
            dest,
            moniker=plan.moniker,
            remote=(plan.remotes_before.get("origin") if plan.remotes_before else None),
            extra={
                "migrated_from": str(source),
                "migrated_at": datetime.now(timezone.utc).isoformat(),
                "kind": plan.kind,
                "subject_origin": plan.subject_origin,
                "remotes_before": plan.remotes_before or None,
            },
        )
        applied.append("wrote store.json")
        write_host_store_config(host, plan.moniker)
        applied.append(f"wrote {host / '.ta-config.json'} store_moniker")

        verify_errors = verify_store(dest, remotes_expected=remotes_expected)
        if source_count and _count_entries(dest) < max(1, source_count // 2):
            # Heuristic: catastrophic loss
            verify_errors.append(
                f"Entry count drop suspicious: source had ~{source_count}, "
                f"dest has {_count_entries(dest)}"
            )
        if verify_errors:
            raise RuntimeError("Verification failed: " + "; ".join(verify_errors))
        applied.append("verified store")

        # Host pointers (eject may be gone if it was the moved directory)
        if source_was_eject_dir and not eject.exists():
            pass  # recreate in _update_host_pointers
        applied.extend(_update_host_pointers(host, dest))

        reg = MachineRegistry(data_root)
        reg.ensure_layout()
        reg.upsert(
            StoreEntry(
                moniker=plan.moniker,
                store_path=str(dest.resolve()),
                host_paths=[str(host.resolve())],
                remote=git_remote_url(dest) if plan.kind == "nested_git" else None,
            )
        )
        applied.append(f"registry upsert {plan.moniker}")

    except Exception as e:
        # Best-effort rollback if dest exists and source is gone
        if dest.exists() and not source.exists():
            try:
                # Move back only if source parent still exists
                if source.parent.is_dir():
                    shutil.move(str(dest), str(source))
                    applied.append(f"rollback: moved {dest} → {source}")
            except Exception as rb:
                return MigrationResult(
                    plan=plan,
                    dry_run=False,
                    success=False,
                    message=(
                        f"Migration failed: {e}. Rollback also failed: {rb}. "
                        f"Manual recovery may be needed. Applied: {applied}"
                    ),
                    applied_steps=applied,
                )
        return MigrationResult(
            plan=plan,
            dry_run=False,
            success=False,
            message=f"Migration failed: {e}",
            applied_steps=applied,
        )

    return MigrationResult(
        plan=plan,
        dry_run=False,
        success=True,
        message=f"Migrated {plan.moniker} → {dest}",
        applied_steps=applied,
    )


def inspect_host(host_path: Path, data_root: Optional[Path] = None) -> Dict[str, Any]:
    """Read-only inspection of how a host path maps to moniker / store / legacy.

    Safe: does not create directories, registry entries, or move data.
    """
    host = host_path.expanduser().resolve()
    top = git_toplevel(host) or host
    moniker, origin = resolve_moniker_for_host(top)
    root = data_root if data_root is not None else get_data_root()
    registry = MachineRegistry(root)
    entry = registry.get(moniker) or registry.find_by_host_path(top)
    canonical = store_path_for_moniker(moniker, root)
    legacy = detect_legacy_store(top)

    legacy_kind: Optional[str] = None
    legacy_remote: Optional[str] = None
    if legacy is not None:
        if legacy.resolve() == canonical.resolve():
            # Post-migrate: host path resolves into the data-root store
            legacy_kind = "centralized"
            legacy_remote = (
                git_remote_url(legacy) if is_nested_git_repo(legacy) else None
            )
        elif is_nested_git_repo(legacy):
            legacy_kind = "nested_git"
            legacy_remote = git_remote_url(legacy)
        else:
            legacy_kind = "host_tree"
            legacy_remote = None

    pointers_ok = False
    eject = top / ".task-agent" / "tasks"
    if eject.is_symlink():
        try:
            pointers_ok = eject.resolve() == canonical.resolve()
        except OSError:
            pointers_ok = False

    migrated = bool(
        canonical.is_dir()
        and looks_like_store(canonical)
        and (
            (entry and Path(entry.store_path).resolve() == canonical.resolve())
            or pointers_ok
        )
    )

    store_remotes: Dict[str, str] = {}
    subject_origin_meta = None
    if canonical.is_dir():
        store_remotes = _list_git_remotes(canonical)
        meta = read_store_meta(canonical) or {}
        subject_origin_meta = meta.get("subject_origin")

    return {
        "host_path": str(top),
        "moniker": moniker,
        "origin": origin,
        "subject_origin_recorded": subject_origin_meta,
        "data_root": str(root),
        "canonical_store_path": str(canonical),
        "canonical_store_exists": canonical.is_dir(),
        "store_remotes": store_remotes,
        "registry_entry": entry.to_dict() if entry else None,
        "legacy_store_path": str(legacy) if legacy else None,
        "legacy_kind": legacy_kind,
        "legacy_remote": legacy_remote,
        "migrated": migrated,
        "pointers_ok": pointers_ok,
    }


# ---------------------------------------------------------------------------
# Store remotes (Phase 4) — core speaks git URLs only; providers suggest
# ---------------------------------------------------------------------------


def default_remote_providers():
    """Built-in TasksRemoteProvider instances."""
    from taskagent.plugins.github import GitHubTasksRemoteProvider

    return [GitHubTasksRemoteProvider()]


def suggest_store_remotes(
    host_path: Path,
    *,
    moniker: Optional[str] = None,
    origin_url: Optional[str] = None,
) -> List[Any]:
    """Collect remote suggestions from all registered providers.

    Returns a list of ``RemoteSuggestion`` (typed loosely to avoid import cycles
    at module load in constrained environments).
    """
    host = host_path.expanduser().resolve()
    top = git_toplevel(host) or host
    if moniker is None or origin_url is None:
        derived_moniker, derived_origin = resolve_moniker_for_host(top)
        moniker = moniker or derived_moniker
        origin_url = origin_url if origin_url is not None else derived_origin

    if not origin_url:
        return []

    suggestions: List[Any] = []
    for provider in default_remote_providers():
        try:
            suggestions.extend(provider.suggest_remote(origin_url, moniker))
        except Exception:
            continue
    return suggestions


class RepoNotFoundError(LookupError):
    """No registered store matched the query fragment."""


class AmbiguousRepoMatchError(LookupError):
    """Multiple stores matched the query equally well."""

    def __init__(self, query: str, candidates: List["ResolvedStore"]):
        self.query = query
        self.candidates = candidates
        monikers = ", ".join(c.moniker for c in candidates)
        super().__init__(f"Ambiguous repo query {query!r}: {monikers}")


@dataclass
class ResolvedStore:
    """A registry/store hit from fuzzy moniker or host-path matching."""

    moniker: str
    store_path: Path
    host_paths: List[str] = field(default_factory=list)
    remote: Optional[str] = None
    score: int = 0
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "moniker": self.moniker,
            "store_path": str(self.store_path),
            "host_paths": list(self.host_paths),
            "remote": self.remote,
            "score": self.score,
            "reason": self.reason,
        }


def _score_repo_query(
    query: str, moniker: str, host_paths: List[str]
) -> tuple[int, str]:
    """Return (score, reason) for how well ``query`` matches this store.

    Higher is better. Zero means no match.
    """
    q = query.strip().lower()
    if not q:
        return 0, ""

    m = moniker.lower()
    basename = m.rsplit("/", 1)[-1]

    if m == q:
        return 100, "exact moniker"
    if basename == q:
        return 95, "exact moniker basename"
    if m.startswith(q) or basename.startswith(q):
        return 85, "moniker prefix"
    if q in m:
        return 75, "moniker substring"

    for hp in host_paths:
        try:
            p = Path(hp)
            name = p.name.lower()
            full = str(p).lower()
        except Exception:
            continue
        if name == q:
            return 65, f"host basename {p.name}"
        if q in name or q in full:
            return 55, f"host path {hp}"

    return 0, ""


def _effective_store_path(entry: StoreEntry) -> Optional[Path]:
    """Resolve a usable store directory for a registry entry (data-root or legacy)."""
    path = Path(entry.store_path).expanduser()
    try:
        if path.is_dir() and looks_like_store(path):
            return path.resolve()
    except OSError:
        pass

    for hp in entry.host_paths:
        try:
            host = Path(hp).expanduser()
            legacy = detect_legacy_store(host)
            if legacy is not None and looks_like_store(legacy):
                return legacy.resolve()
        except OSError:
            continue
    return None


def fuzzy_match_repos(
    query: str, data_root: Optional[Path] = None
) -> List[ResolvedStore]:
    """Rank registered stores by moniker/host-path fuzzy match (zoxide-style).

    Returns matches sorted by score descending (score > 0 only).
    """
    reg = MachineRegistry(data_root)
    hits: List[ResolvedStore] = []
    for entry in reg.list_entries():
        score, reason = _score_repo_query(query, entry.moniker, entry.host_paths)
        if score <= 0:
            continue
        store_path = _effective_store_path(entry)
        if store_path is None:
            continue
        hits.append(
            ResolvedStore(
                moniker=entry.moniker,
                store_path=store_path,
                host_paths=list(entry.host_paths),
                remote=entry.remote,
                score=score,
                reason=reason,
            )
        )
    hits.sort(key=lambda h: (-h.score, h.moniker))
    return hits


def resolve_repo_query(query: str, data_root: Optional[Path] = None) -> ResolvedStore:
    """Resolve a zoxide-like fragment to exactly one registered store.

    Raises:
        RepoNotFoundError: no matches
        AmbiguousRepoMatchError: multiple top-scoring matches
    """
    q = (query or "").strip()
    if not q:
        raise RepoNotFoundError("Empty repo query")

    hits = fuzzy_match_repos(q, data_root=data_root)
    if not hits:
        raise RepoNotFoundError(f"No registered store matches {q!r}")

    best = hits[0].score
    top = [h for h in hits if h.score == best]
    if len(top) > 1:
        raise AmbiguousRepoMatchError(q, top)
    return top[0]


def manager_for_repo_query(
    query: str, data_root: Optional[Path] = None
) -> tuple[Any, ResolvedStore]:
    """Return ``(TaskAgent, ResolvedStore)`` for a moniker/host fragment."""
    from taskagent.manager import TaskAgent

    resolved = resolve_repo_query(query, data_root=data_root)
    return TaskAgent(config_dir=str(resolved.store_path)), resolved


def rebind_store_moniker(
    host_path: Path,
    new_moniker: Optional[str] = None,
    data_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """Rebind a host project to a (possibly new) moniker after a repo rename.

    Resolution of the *current* store prefers:
    1. ``.ta-config.json`` / pyproject ``store_moniker``
    2. Registry by host path
    3. Moniker derived from current origin

    Then updates store.json, renames the data-root directory if needed,
    rewrites the host pointer, and updates the registry.

    Args:
        host_path: Subject project path.
        new_moniker: Explicit moniker; default = moniker from current host origin.
        data_root: Optional data root override.
    """
    host = host_path.expanduser().resolve()
    top = git_toplevel(host) or host
    root = data_root if data_root is not None else get_data_root()
    reg = MachineRegistry(root)

    # Find existing binding
    derived, subject_origin = resolve_moniker_for_host(top)
    target_moniker = (new_moniker or derived).strip()
    if not target_moniker:
        raise ValueError("Cannot derive moniker; pass new_moniker explicitly")

    entry = reg.find_by_host_path(top) or reg.get(derived)
    # Also try ta-config moniker
    config_moniker = None
    cfg = top / ".ta-config.json"
    if cfg.is_file():
        try:
            raw = json.loads(cfg.read_text(encoding="utf-8"))
            config_moniker = raw.get("store_moniker") or raw.get("moniker")
        except (OSError, json.JSONDecodeError):
            pass
    if entry is None and config_moniker:
        entry = reg.get(str(config_moniker))

    if entry is None:
        # Fall back to canonical path for derived moniker
        cand = store_path_for_moniker(derived, root)
        if not (cand.is_dir() and looks_like_store(cand)):
            raise FileNotFoundError(
                f"No registered store for host {top}; run ta store migrate first"
            )
        old_moniker = derived
        old_path = cand
    else:
        old_moniker = entry.moniker
        old_path = Path(entry.store_path).resolve()

    new_path = store_path_for_moniker(target_moniker, root)
    moved = False
    if old_path.resolve() != new_path.resolve():
        if new_path.exists():
            raise FileExistsError(
                f"Destination store already exists: {new_path}. "
                "Remove or choose a different moniker."
            )
        new_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(old_path), str(new_path))
        moved = True
    else:
        new_path = old_path

    meta = read_store_meta(new_path) or {}
    write_store_meta(
        new_path,
        moniker=target_moniker,
        remote=meta.get("remote") or git_remote_url(new_path),
        extra={
            **{
                k: v
                for k, v in meta.items()
                if k not in ("moniker", "remote", "version")
            },
            "subject_origin": subject_origin or meta.get("subject_origin"),
            "previous_moniker": old_moniker
            if old_moniker != target_moniker
            else meta.get("previous_moniker"),
            "rebound_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    write_host_store_config(top, target_moniker)
    _update_host_pointers(top, new_path)

    # Registry: drop old moniker key if renamed
    entries = reg.load()
    if old_moniker in entries and old_moniker != target_moniker:
        old_entry = entries.pop(old_moniker)
        hosts = list(dict.fromkeys([*old_entry.host_paths, str(top)]))
        entries[target_moniker] = StoreEntry(
            moniker=target_moniker,
            store_path=str(new_path.resolve()),
            host_paths=hosts,
            remote=old_entry.remote or git_remote_url(new_path),
            registered_at=old_entry.registered_at,
        )
        reg.save(entries)
    else:
        reg.upsert(
            StoreEntry(
                moniker=target_moniker,
                store_path=str(new_path.resolve()),
                host_paths=[str(top)],
                remote=git_remote_url(new_path),
            )
        )

    return {
        "old_moniker": old_moniker,
        "new_moniker": target_moniker,
        "store_path": str(new_path.resolve()),
        "moved": moved,
        "subject_origin": subject_origin,
        "host_config": str(top / ".ta-config.json"),
    }


def set_store_remote(
    store_path: Path,
    url: str,
    *,
    remote_name: str = "origin",
    moniker: Optional[str] = None,
    data_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """Set (or add) a git remote on a task store and update metadata/registry.

    Does not create the remote repository on a host; only configures local git.
    """
    store = store_path.expanduser().resolve()
    if not store.is_dir() or not looks_like_store(store):
        raise ValueError(f"Not a task store: {store}")

    url = url.strip()
    if not url:
        raise ValueError("Empty remote URL")

    # Ensure git repo
    if not (store / ".git").exists() and not is_nested_git_repo(store):
        _git_init_and_commit(
            store,
            "chore: initialize task store git before setting remote",
        )

    existing = _list_git_remotes(store)
    if remote_name in existing:
        subprocess.run(
            ["git", "-C", str(store), "remote", "set-url", remote_name, url],
            check=True,
            capture_output=True,
            shell=(os.name == "nt"),
        )
        action = "set-url"
    else:
        subprocess.run(
            ["git", "-C", str(store), "remote", "add", remote_name, url],
            check=True,
            capture_output=True,
            shell=(os.name == "nt"),
        )
        action = "add"

    # Resolve moniker for metadata
    meta = read_store_meta(store) or {}
    use_moniker = moniker or meta.get("moniker")
    if not use_moniker:
        try:
            use_moniker = moniker_from_remote(url)
        except ValueError:
            use_moniker = store.name.replace("_", "/", 1)

    write_store_meta(
        store,
        moniker=str(use_moniker),
        remote=url if remote_name == "origin" else meta.get("remote"),
        extra={
            "remote_name": remote_name,
            **(
                {"remotes": {**(meta.get("remotes") or {}), remote_name: url}}
                if True
                else {}
            ),
        },
    )

    reg = MachineRegistry(data_root)
    reg.upsert(
        StoreEntry(
            moniker=str(use_moniker),
            store_path=str(store),
            host_paths=[],
            remote=url if remote_name == "origin" else None,
        )
    )

    return {
        "action": action,
        "remote_name": remote_name,
        "url": url,
        "store_path": str(store),
        "moniker": use_moniker,
        "remotes": _list_git_remotes(store),
    }
