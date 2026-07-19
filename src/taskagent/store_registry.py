"""Machine-level task store data root, monikers, and registry.

Phase 1 of centralizing task-agent stores outside host repos.

This module is intentionally side-effect free with respect to host project
trees: it never moves ``.task-agent/tasks`` or rewrites discovery defaults.
Migration lives in a later phase.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

REGISTRY_VERSION = 1
STORE_META_REL = Path(".task-agent") / "store.json"


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
        if is_nested_git_repo(legacy):
            legacy_kind = "nested_git"
            legacy_remote = git_remote_url(legacy)
        else:
            legacy_kind = "host_tree"
            legacy_remote = git_remote_url(legacy)

    return {
        "host_path": str(top),
        "moniker": moniker,
        "origin": origin,
        "data_root": str(root),
        "canonical_store_path": str(canonical),
        "canonical_store_exists": canonical.is_dir(),
        "registry_entry": entry.to_dict() if entry else None,
        "legacy_store_path": str(legacy) if legacy else None,
        "legacy_kind": legacy_kind,
        "legacy_remote": legacy_remote,
        "migrated": bool(
            entry
            and Path(entry.store_path).resolve() == canonical.resolve()
            and canonical.is_dir()
        ),
    }
