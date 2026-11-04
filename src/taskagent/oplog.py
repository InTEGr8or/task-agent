"""Append-only per-writer operation log for a task store.

See ``docs/adr/0001-sync-task-stores-with-an-operation-log.md``.

Writers append JSON files under ``.task-agent/ops/<writer-id>/``. Sync is the
union of those files. Station directories and ``mission.usv`` stay a projection.
``reduce_ops`` is the in-memory projection used until ``ta sync`` materializes
the tree from the log.
"""

from __future__ import annotations

import json
import os
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

OPS_REL = Path(".task-agent") / "ops"
OP_SUFFIX = ".op.json"
SCHEMA_VERSION = 1

VERBS = frozenset({"create", "move", "edges", "rename", "lease", "release"})


class OpLogError(ValueError):
    """Invalid op log read or write."""


@dataclass
class Op:
    """One store operation."""

    verb: str
    slug: str
    writer: str
    id: str
    at: str
    payload: Dict[str, Any] = field(default_factory=dict)
    v: int = SCHEMA_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return {
            "v": self.v,
            "id": self.id,
            "writer": self.writer,
            "at": self.at,
            "verb": self.verb,
            "slug": self.slug,
            "payload": self.payload,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Op":
        try:
            verb = str(data["verb"])
            slug = str(data["slug"])
            writer = str(data["writer"])
            op_id = str(data["id"])
            at = str(data["at"])
        except KeyError as exc:
            raise OpLogError(f"Op is missing {exc.args[0]}") from exc
        payload = data.get("payload") or {}
        if not isinstance(payload, dict):
            raise OpLogError("Op payload must be an object")
        return cls(
            verb=verb,
            slug=slug,
            writer=writer,
            id=op_id,
            at=at,
            payload=dict(payload),
            v=int(data.get("v") or SCHEMA_VERSION),
        )


@dataclass
class ProjectedTask:
    """Task state folded out of the op log. Not the on-disk station tree."""

    slug: str
    name: str
    station: str
    blocked_by: List[str] = field(default_factory=list)
    subtask_of: Optional[str] = None
    lease_worker: Optional[str] = None


def ops_root(store: Path) -> Path:
    return Path(store) / OPS_REL


def get_writer_id(data_root: Optional[Path] = None) -> str:
    """Stable id for this machine.

    ``TA_WRITER_ID`` wins. Under pytest, return ``pytest`` so the suite does
    not create a writer file in the real data root. Otherwise persist a uuid
    at ``<data-root>/writer-id``.
    """
    override = os.environ.get("TA_WRITER_ID", "").strip()
    if override:
        return _safe_writer(override)
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return "pytest"

    if data_root is None:
        from taskagent.store_registry import get_data_root

        root = get_data_root()
    else:
        root = Path(data_root)
    root.mkdir(parents=True, exist_ok=True)
    path = root / "writer-id"
    if path.is_file():
        existing = path.read_text(encoding="utf-8").strip()
        if existing:
            return _safe_writer(existing)
    writer = str(uuid.uuid4())
    path.write_text(writer + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return writer


def _safe_writer(writer: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in writer)
    cleaned = cleaned.strip("._") or "writer"
    if cleaned in {".", ".."}:
        raise OpLogError(f"Unsafe writer id: {writer!r}")
    return cleaned


def _new_op_id(when: datetime) -> str:
    stamp = when.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    return f"{stamp}-{secrets.token_hex(3)}"


def append_op(
    store: Path,
    *,
    verb: str,
    slug: str,
    payload: Optional[Mapping[str, Any]] = None,
    writer: Optional[str] = None,
    op_id: Optional[str] = None,
    at: Optional[datetime] = None,
) -> Op:
    """Append one op for this writer. Refuses to overwrite an existing file."""
    if verb not in VERBS:
        raise OpLogError(f"Unknown op verb: {verb!r}")
    slug = slug.strip()
    if not slug:
        raise OpLogError("Op slug is empty")

    when = at or datetime.now(timezone.utc)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    op = Op(
        verb=verb,
        slug=slug,
        writer=_safe_writer(writer) if writer else get_writer_id(),
        id=op_id or _new_op_id(when),
        at=when.astimezone(timezone.utc).isoformat(),
        payload=dict(payload or {}),
    )
    directory = ops_root(store) / op.writer
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{op.id}{OP_SUFFIX}"
    if path.exists():
        raise OpLogError(f"Op already exists: {path}")
    path.write_text(
        json.dumps(op.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return op


def list_ops(store: Path) -> List[Op]:
    """Read every op in the store, sorted by ``(at, id)``."""
    root = ops_root(store)
    if not root.is_dir():
        return []
    found: List[Op] = []
    for path in sorted(root.glob(f"*/*{OP_SUFFIX}")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise OpLogError(f"Corrupt op {path}: {exc}") from exc
        if not isinstance(data, dict):
            raise OpLogError(f"Corrupt op {path}: expected an object")
        found.append(Op.from_dict(data))
    found.sort(key=lambda op: (op.at, op.id))
    return found


def reduce_ops(ops: Iterable[Op]) -> Dict[str, ProjectedTask]:
    """Fold ops into task records.

    First ``create`` wins. Later ``move`` wins. ``edges`` replaces named
    fields. Unknown extra payload keys are ignored.
    """
    ordered = sorted(ops, key=lambda op: (op.at, op.id))
    state: Dict[str, ProjectedTask] = {}
    for op in ordered:
        _apply(state, op)
    return state


def _apply(state: Dict[str, ProjectedTask], op: Op) -> None:
    payload = op.payload
    if op.verb == "create":
        if op.slug in state:
            return
        blocked = payload.get("blocked_by") or []
        if not isinstance(blocked, list):
            blocked = []
        sub = payload.get("subtask_of")
        state[op.slug] = ProjectedTask(
            slug=op.slug,
            name=str(payload.get("name") or op.slug),
            station=str(payload.get("station") or "pending"),
            blocked_by=[str(item) for item in blocked],
            subtask_of=str(sub) if sub else None,
        )
        return

    if op.verb == "move":
        task = state.get(op.slug)
        station = str(payload.get("station") or "")
        if not station:
            raise OpLogError(f"move op {op.id} is missing station")
        if task is None:
            task = ProjectedTask(slug=op.slug, name=op.slug, station=station)
            state[op.slug] = task
        else:
            task.station = station
        return

    if op.verb == "edges":
        task = state.get(op.slug)
        if task is None:
            task = ProjectedTask(slug=op.slug, name=op.slug, station="pending")
            state[op.slug] = task
        if "blocked_by" in payload:
            raw = payload.get("blocked_by") or []
            task.blocked_by = (
                [str(item) for item in raw] if isinstance(raw, list) else []
            )
        if "subtask_of" in payload:
            sub = payload.get("subtask_of")
            task.subtask_of = str(sub) if sub else None
        if "name" in payload and payload.get("name"):
            task.name = str(payload["name"])
        return

    if op.verb == "rename":
        new_slug = str(payload.get("new_slug") or "").strip()
        if not new_slug:
            raise OpLogError(f"rename op {op.id} is missing new_slug")
        task = state.pop(op.slug, None)
        if task is None:
            task = ProjectedTask(slug=new_slug, name=new_slug, station="pending")
        task.slug = new_slug
        if payload.get("name"):
            task.name = str(payload["name"])
        state[new_slug] = task
        return

    if op.verb == "lease":
        task = state.get(op.slug)
        if task is None:
            task = ProjectedTask(slug=op.slug, name=op.slug, station="active")
            state[op.slug] = task
        worker = payload.get("worker_id")
        task.lease_worker = str(worker) if worker else None
        return

    if op.verb == "release":
        task = state.get(op.slug)
        if task is not None:
            task.lease_worker = None
        return

    raise OpLogError(f"Unknown op verb: {op.verb!r}")
