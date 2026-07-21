"""Day-sharded, ack-gated inbox messaging between task-agent stores.

Layout (under a store root)::

    .task-agent/inbox/
      unread/
        <id>.msg.md
      read/
        YYYY/MM/DD/<id>.msg.md   # shard chosen at ACK time

v1 assumes sender and target share a filesystem (same machine data root).
Real-time cross-machine delivery is out of scope.
"""

from __future__ import annotations

import os
import re
import secrets
import shutil
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

DEFAULT_RETENTION_DAYS = 7
INBOX_REL = Path(".task-agent") / "inbox"
MESSAGE_SUFFIX = ".msg.md"
KINDS = frozenset(
    {"task-created", "question", "update", "comment", "ack-request", "info"}
)

_FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n?(.*)\Z", re.DOTALL)
_DAY_DIR_RE = re.compile(r"^\d{4}/\d{2}/\d{2}$")


@dataclass
class InboxMessage:
    """Parsed inbox message."""

    id: str
    path: Path
    from_moniker: str = ""
    thread: Optional[str] = None
    kind: str = "info"
    created_at: str = ""
    body: str = ""
    status: str = "unread"  # unread | read
    meta: Dict[str, str] = field(default_factory=dict)

    def summary_line(self) -> str:
        thread = f" thread={self.thread}" if self.thread else ""
        kind = self.kind or "info"
        preview = " ".join(self.body.strip().split())[:80]
        return f"[{self.id}] {kind} from {self.from_moniker or '?'}{thread}: {preview}"


def inbox_root(store_path: Path) -> Path:
    return Path(store_path) / INBOX_REL


def unread_dir(store_path: Path) -> Path:
    return inbox_root(store_path) / "unread"


def read_dir(store_path: Path) -> Path:
    return inbox_root(store_path) / "read"


def ensure_inbox_dirs(store_path: Path) -> Path:
    root = inbox_root(store_path)
    (root / "unread").mkdir(parents=True, exist_ok=True)
    (root / "read").mkdir(parents=True, exist_ok=True)
    return root


def _new_message_id(when: Optional[datetime] = None) -> str:
    when = when or datetime.now(timezone.utc)
    stamp = when.strftime("%Y%m%dT%H%M%S")
    return f"{stamp}-{secrets.token_hex(3)}"


def _parse_frontmatter(text: str) -> tuple[Dict[str, str], str]:
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    meta: Dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        meta[key.strip()] = val.strip()
    return meta, m.group(2).lstrip("\n")


def _format_message_file(
    *,
    from_moniker: str,
    kind: str,
    created_at: str,
    thread: Optional[str],
    body: str,
    task_snapshot: Optional[Dict[str, Any]] = None,
) -> str:
    lines = [
        "---",
        f"from: {from_moniker}",
        f"kind: {kind}",
        f"created_at: {created_at}",
    ]
    if thread:
        lines.append(f"thread: {thread}")
    lines.append("---")
    lines.append("")
    if task_snapshot:
        lines.append("## Linked task snapshot")
        lines.append("")
        for key in ("slug", "title", "status", "completion_criteria"):
            if key in task_snapshot and task_snapshot[key] is not None:
                label = key.replace("_", " ").title()
                lines.append(f"- **{label}**: {task_snapshot[key]}")
        if task_snapshot.get("slug"):
            lines.append("")
            lines.append(f"_Live slug: `{task_snapshot['slug']}`_")
        lines.append("")
    body = body.rstrip() + "\n" if body else ""
    lines.append(body if body else "")
    return "\n".join(lines)


def parse_message_file(path: Path, status: str = "unread") -> InboxMessage:
    text = path.read_text(encoding="utf-8")
    meta, body = _parse_frontmatter(text)
    mid = path.name
    if mid.endswith(MESSAGE_SUFFIX):
        mid = mid[: -len(MESSAGE_SUFFIX)]
    return InboxMessage(
        id=mid,
        path=path,
        from_moniker=meta.get("from", ""),
        thread=meta.get("thread") or None,
        kind=meta.get("kind", "info"),
        created_at=meta.get("created_at", ""),
        body=body,
        status=status,
        meta=meta,
    )


def list_unread(
    store_path: Path,
    *,
    thread: Optional[str] = None,
) -> List[InboxMessage]:
    """List unread messages (display only — does not mutate)."""
    udir = unread_dir(store_path)
    if not udir.is_dir():
        return []
    msgs: List[InboxMessage] = []
    for path in sorted(udir.glob(f"*{MESSAGE_SUFFIX}")):
        try:
            msg = parse_message_file(path, status="unread")
        except OSError:
            continue
        if thread is not None and (msg.thread or "") != thread:
            continue
        msgs.append(msg)
    return msgs


def unread_count(store_path: Path, *, thread: Optional[str] = None) -> int:
    return len(list_unread(store_path, thread=thread))


def format_unread_banner(
    store_path: Path,
    *,
    thread: Optional[str] = None,
    moniker: Optional[str] = None,
) -> Optional[str]:
    """Return a one-line banner if unread messages exist; never mutates state."""
    msgs = list_unread(store_path, thread=thread)
    if not msgs:
        return None
    label = moniker or Path(store_path).name
    if len(msgs) == 1:
        return (
            f"📬 Inbox ({label}): 1 unread — "
            f"{msgs[0].summary_line()}  [ta inbox list / ta inbox ack <id>]"
        )
    kinds: Dict[str, int] = {}
    for m in msgs:
        kinds[m.kind] = kinds.get(m.kind, 0) + 1
    kind_bits = ", ".join(f"{k}×{n}" for k, n in sorted(kinds.items()))
    return (
        f"📬 Inbox ({label}): {len(msgs)} unread ({kind_bits})  "
        f"[ta inbox list / ta inbox ack <id>]"
    )


def send_message(
    target_store: Path,
    *,
    from_moniker: str,
    body: str = "",
    kind: str = "info",
    thread: Optional[str] = None,
    task_snapshot: Optional[Dict[str, Any]] = None,
    message_id: Optional[str] = None,
    created_at: Optional[datetime] = None,
) -> InboxMessage:
    """Write a message into ``target_store``'s ``inbox/unread/``.

    Does not scan any other store's inbox. Target path must already be resolved
    (e.g. via store_registry moniker resolution).
    """
    if kind not in KINDS:
        raise ValueError(f"Invalid kind {kind!r}; expected one of {sorted(KINDS)}")
    if not from_moniker or not str(from_moniker).strip():
        raise ValueError("from_moniker is required")

    ensure_inbox_dirs(target_store)
    when = created_at or datetime.now(timezone.utc)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    mid = message_id or _new_message_id(when)
    # Sanitize id for filesystem
    mid = re.sub(r"[^A-Za-z0-9._-]", "-", mid)
    if not mid:
        raise ValueError("message id empty after sanitize")

    path = unread_dir(target_store) / f"{mid}{MESSAGE_SUFFIX}"
    if path.exists():
        raise FileExistsError(f"Message already exists: {path.name}")

    content = _format_message_file(
        from_moniker=from_moniker.strip(),
        kind=kind,
        created_at=when.isoformat(),
        thread=thread.strip() if thread else None,
        body=body or "",
        task_snapshot=task_snapshot,
    )
    path.write_text(content, encoding="utf-8")
    return parse_message_file(path, status="unread")


def find_unread_message(store_path: Path, message_id: str) -> Optional[Path]:
    """Resolve an unread message path by id (with or without suffix)."""
    mid = message_id.strip()
    if mid.endswith(MESSAGE_SUFFIX):
        mid = mid[: -len(MESSAGE_SUFFIX)]
    # Allow unique prefix match
    udir = unread_dir(store_path)
    if not udir.is_dir():
        return None
    exact = udir / f"{mid}{MESSAGE_SUFFIX}"
    if exact.is_file():
        return exact
    matches = [
        p
        for p in udir.glob(f"*{MESSAGE_SUFFIX}")
        if p.name.startswith(mid) or p.stem.startswith(mid)
    ]
    if len(matches) == 1:
        return matches[0]
    return None


def ack_message(
    store_path: Path,
    message_id: str,
    *,
    ack_day: Optional[date] = None,
) -> InboxMessage:
    """Move an unread message into ``read/YYYY/MM/DD/`` (shard = ack day)."""
    src = find_unread_message(store_path, message_id)
    if src is None:
        raise FileNotFoundError(f"Unread message not found: {message_id!r}")

    day = ack_day or date.today()
    dest_dir = (
        read_dir(store_path) / f"{day.year:04d}" / f"{day.month:02d}" / f"{day.day:02d}"
    )
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name
    if dest.exists():
        # Extremely unlikely same id acked twice into same day
        raise FileExistsError(f"Ack target already exists: {dest}")
    shutil.move(str(src), str(dest))
    return parse_message_file(dest, status="read")


def _iter_day_dirs(read_root: Path) -> List[Path]:
    """Return day directories as Paths relative to read_root in YYYY/MM/DD form."""
    if not read_root.is_dir():
        return []
    days: List[Path] = []
    for year in sorted(read_root.iterdir()):
        if not year.is_dir() or not year.name.isdigit() or len(year.name) != 4:
            continue
        for month in sorted(year.iterdir()):
            if not month.is_dir() or not re.fullmatch(r"\d{2}", month.name):
                continue
            for day in sorted(month.iterdir()):
                if not day.is_dir() or not re.fullmatch(r"\d{2}", day.name):
                    continue
                rel = Path(year.name) / month.name / day.name
                if _DAY_DIR_RE.match(rel.as_posix()):
                    days.append(day)
    return days


def gc_inbox(
    store_path: Path,
    *,
    retention_days: int = DEFAULT_RETENTION_DAYS,
    today: Optional[date] = None,
    dry_run: bool = False,
) -> List[str]:
    """Delete ``read/YYYY/MM/DD`` dirs older than retention using names only.

    Never opens message files or stats mtimes. Never touches ``unread/``.
    Returns list of deleted (or would-delete) day directory paths as strings.
    """
    if retention_days < 0:
        raise ValueError("retention_days must be >= 0")

    today = today or date.today()
    # Keep days where day_dir >= cutoff (inclusive). Delete strictly older.
    # retention_days=7 with today=2026-07-21 keeps 2026-07-14 .. 2026-07-21
    cutoff = today - timedelta(days=retention_days)
    cutoff_key = f"{cutoff.year:04d}/{cutoff.month:02d}/{cutoff.day:02d}"

    read_root = read_dir(store_path)
    deleted: List[str] = []
    for day_path in _iter_day_dirs(read_root):
        # day_path is .../read/YYYY/MM/DD
        try:
            rel = day_path.relative_to(read_root).as_posix()
        except ValueError:
            continue
        if rel >= cutoff_key:
            continue
        deleted.append(str(day_path))
        if not dry_run:
            shutil.rmtree(day_path, ignore_errors=False)
            # Prune empty month/year dirs
            month = day_path.parent
            year = month.parent
            try:
                if month.is_dir() and not any(month.iterdir()):
                    month.rmdir()
                if year.is_dir() and not any(year.iterdir()):
                    year.rmdir()
            except OSError:
                pass
    return deleted


def moniker_for_store(store_path: Path) -> Optional[str]:
    """Best-effort moniker from store.json."""
    try:
        from taskagent.store_registry import read_store_meta

        meta = read_store_meta(store_path)
        if meta and meta.get("moniker"):
            return str(meta["moniker"])
    except Exception:
        pass
    return None


def resolve_sender_moniker(
    store_path: Optional[Path] = None,
    host_path: Optional[Path] = None,
) -> str:
    """Resolve a from= moniker for the current context."""
    if store_path is not None:
        m = moniker_for_store(store_path)
        if m:
            return m
    if host_path is not None:
        try:
            from taskagent.store_registry import resolve_moniker_for_host

            m, _ = resolve_moniker_for_host(host_path)
            if m:
                return m
        except Exception:
            pass
    env = os.environ.get("TA_STORE_MONIKER")
    if env:
        return env
    if store_path is not None:
        return Path(store_path).name
    return "unknown"


def snapshot_from_issue(issue: Any) -> Dict[str, Any]:
    """Build a task snapshot dict from an Issue-like object."""
    return {
        "slug": getattr(issue, "slug", None),
        "title": getattr(issue, "name", None) or getattr(issue, "title", None),
        "status": getattr(issue, "status", None),
        "completion_criteria": getattr(issue, "completion_criteria", None),
    }


def send_to_repo(
    repo_query: str,
    *,
    from_moniker: str,
    body: str = "",
    kind: str = "info",
    thread: Optional[str] = None,
    task_snapshot: Optional[Dict[str, Any]] = None,
) -> tuple[InboxMessage, Any]:
    """Resolve ``repo_query`` via registry and deliver a message.

    Returns ``(message, ResolvedStore)``.
    """
    from taskagent.store_registry import resolve_repo_query

    resolved = resolve_repo_query(repo_query)
    msg = send_message(
        resolved.store_path,
        from_moniker=from_moniker,
        body=body,
        kind=kind,
        thread=thread,
        task_snapshot=task_snapshot,
    )
    return msg, resolved
