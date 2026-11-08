"""Module for discovering and extracting last-active agent session info."""

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional, Tuple

from multi_agent_registry import (
    AgentCLIInfo,
    DiscoveredChat,
    discover_agent_chats,
    get_agent_cli_registry,
)
from multi_agent_registry.discovery import get_chat_workspace
from taskagent.store_registry import project_host_root


@dataclass
class AgentLastUsedInfo:
    """Information on the last active session for an agent CLI in a repository."""

    agent_id: str
    agent_name: str
    description: str
    last_active: datetime
    last_user_comment: str
    log_path: Path


@dataclass
class AgentSessionInfo:
    """Information on an agent session across any workspace."""

    agent_id: str
    agent_name: str
    session_id: str
    cwd: Optional[Path]
    last_active: datetime
    title: str
    last_user_comment: str
    reopen_command: str
    log_path: Path


def _resolve_chat_workspace(chat: DiscoveredChat) -> Optional[Path]:
    """Resolve project directory for a chat, including Grok-specific formats."""
    ws = get_chat_workspace(chat)
    if ws is not None:
        return ws
    if chat.agent_id == "grok":
        try:
            data = json.loads(chat.path.read_text(encoding="utf-8", errors="replace"))
            if isinstance(data, dict):
                cwd = data.get("info", {}).get("cwd") or data.get("cwd")
                if cwd:
                    return Path(cwd)
        except Exception:
            pass
        if "%" in chat.path.parent.parent.name:
            import urllib.parse

            try:
                return Path(urllib.parse.unquote(chat.path.parent.parent.name))
            except Exception:
                pass
    return None


def _extract_text(node: Any) -> str:
    """Recursively extract string content from dicts, lists, or primitive strings."""
    if isinstance(node, str):
        return node
    elif isinstance(node, dict):
        if "text" in node and isinstance(node["text"], str):
            return node["text"]
        if "content" in node:
            return _extract_text(node["content"])
        if "message" in node:
            return _extract_text(node["message"])
    elif isinstance(node, list):
        parts = [_extract_text(item) for item in node]
        return " ".join(p for p in parts if p)
    return ""


def _is_user_role(role_val: Any) -> bool:
    if isinstance(role_val, str):
        r = role_val.lower()
        return r in (
            "user",
            "say",
            "user_input",
            "user_explicit",
            "human",
            "user_feedback",
        )
    return False


def _parse_last_user_comment_and_timestamp(
    discovered: DiscoveredChat,
) -> Tuple[datetime, str]:
    """Extract timestamp and first 200 chars of last user comment from chat log file."""
    path = discovered.path
    file_mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    user_comment = ""

    if not path.is_file():
        return file_mtime, user_comment

    try:
        if discovered.parser_type == "jsonl":
            text_lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            for line in reversed(text_lines):
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    if isinstance(data, dict):
                        msg = data.get("message")
                        role = (
                            data.get("type")
                            or data.get("role")
                            or data.get("source")
                            or (msg.get("role") if isinstance(msg, dict) else None)
                        )
                        if _is_user_role(role):
                            raw_comment = _extract_text(msg if msg else data).strip()
                            if (
                                raw_comment
                                and not raw_comment.startswith("<local-command-")
                                and not raw_comment.startswith("<command-name>")
                            ):
                                user_comment = raw_comment
                                created_at = data.get("created_at") or data.get(
                                    "timestamp"
                                )
                                if created_at:
                                    try:
                                        file_mtime = datetime.fromisoformat(
                                            str(created_at).replace("Z", "+00:00")
                                        )
                                    except ValueError:
                                        pass
                                break
                except Exception:
                    continue

        elif discovered.parser_type == "json":
            raw_text = path.read_text(encoding="utf-8", errors="replace")
            data = json.loads(raw_text)
            if isinstance(data, dict):
                # Grok summary.json or session summary objects
                if (
                    "session_summary" in data
                    or "generated_title" in data
                    or "last_turn_summary" in data
                    or "title" in data
                ):
                    raw_comment = (
                        data.get("session_summary")
                        or data.get("generated_title")
                        or data.get("last_turn_summary")
                        or data.get("title")
                        or ""
                    )
                    if raw_comment:
                        user_comment = raw_comment
                    ts = (
                        data.get("last_active_at")
                        or data.get("updated_at")
                        or (
                            data.get("time", {}).get("updated")
                            if isinstance(data.get("time"), dict)
                            else None
                        )
                    )
                    if ts:
                        try:
                            if isinstance(ts, (int, float)):
                                file_mtime = datetime.fromtimestamp(
                                    ts / 1000 if ts > 1e11 else ts, tz=timezone.utc
                                )
                            else:
                                file_mtime = datetime.fromisoformat(
                                    str(ts).replace("Z", "+00:00")
                                )
                        except (ValueError, TypeError):
                            pass

            messages = []
            if isinstance(data, list):
                messages = data
            elif isinstance(data, dict):
                messages = (
                    data.get("messages")
                    or data.get("steps")
                    or data.get("history")
                    or []
                )

            if isinstance(messages, list):
                for msg in reversed(messages):
                    if isinstance(msg, dict):
                        role = (
                            msg.get("say")
                            or msg.get("role")
                            or msg.get("type")
                            or msg.get("source")
                        )
                        if _is_user_role(role):
                            raw_comment = _extract_text(msg).strip()
                            if raw_comment:
                                user_comment = raw_comment
                                break

        elif discovered.parser_type == "markdown":
            raw_text = path.read_text(encoding="utf-8", errors="replace")
            text_lines = raw_text.splitlines()
            user_blocks: List[str] = []
            current_block: List[str] = []
            in_user = False
            for line in text_lines:
                if line.startswith("#") or line.startswith("> "):
                    if in_user and current_block:
                        user_blocks.append("\n".join(current_block).strip())
                        current_block = []
                    in_user = "user" in line.lower() or "human" in line.lower()
                elif in_user:
                    current_block.append(line)
            if in_user and current_block:
                user_blocks.append("\n".join(current_block).strip())
            if user_blocks:
                user_comment = user_blocks[-1]

    except Exception:
        pass

    import re

    # Unwrap <USER_REQUEST> tag, keeping human prompt text
    user_comment = re.sub(r"</?USER_REQUEST>", "", user_comment)

    # Strip system context wrappers (e.g. <CONTEXT_SUMMARY>, <PLAN>, <ADDITIONAL_METADATA>)
    user_comment = re.sub(
        r"<(CONTEXT_SUMMARY|PLAN|ADDITIONAL_METADATA)>.*?</\1>",
        "",
        user_comment,
        flags=re.DOTALL,
    )
    user_comment = re.sub(
        r"</?(CONTEXT_SUMMARY|PLAN|ADDITIONAL_METADATA)>",
        "",
        user_comment,
    )
    user_comment = " ".join(user_comment.split())

    if len(user_comment) > 200:
        user_comment = user_comment[:197] + "..."

    return file_mtime, user_comment


def get_last_active_agents(
    project_dir: Optional[Path] = None,
    limit: int = 5,
) -> List[AgentLastUsedInfo]:
    """Find and rank most recently active AI agent CLIs in a project repository."""
    if project_dir is None:
        project_dir = Path.cwd()

    host_root = project_host_root(project_dir)
    discovered_chats = discover_agent_chats(project_dir=host_root)

    # Ensure Grok chats are discovered even if registered patterns are empty in multi-agent-registry
    if not any(c.agent_id == "grok" for c in discovered_chats):
        import glob

        for pat in (
            "~/.grok/sessions/**/summary.json",
            "/mnt/c/Users/*/.grok/sessions/**/summary.json",
        ):
            for p_str in glob.glob(str(Path(pat).expanduser()), recursive=True):
                discovered_chats.append(
                    DiscoveredChat(
                        agent_id="grok", path=Path(p_str), parser_type="json"
                    )
                )

    registry = get_agent_cli_registry()

    agent_chats_map: dict[str, List[DiscoveredChat]] = {}
    for chat in discovered_chats:
        is_global_log = str(chat.path).startswith(str(Path.home())) and not str(
            chat.path
        ).startswith(str(host_root))
        ws = _resolve_chat_workspace(chat)
        if is_global_log:
            if ws is None:
                continue
            try:
                chat_host = project_host_root(ws)
                if chat_host != host_root and str(chat_host) != str(host_root):
                    continue
            except Exception:
                continue
        elif ws is not None:
            try:
                chat_host = project_host_root(ws)
                if chat_host != host_root and str(chat_host) != str(host_root):
                    continue
            except Exception:
                pass
        agent_chats_map.setdefault(chat.agent_id, []).append(chat)

    results: List[AgentLastUsedInfo] = []

    for agent_id, chats in agent_chats_map.items():
        agent_info: Optional[AgentCLIInfo] = registry.get(agent_id)
        name = agent_info.name if agent_info else agent_id.capitalize()
        description = agent_info.description if agent_info else ""

        newest_mtime: Optional[datetime] = None
        newest_comment: str = ""
        newest_path: Optional[Path] = None

        for chat in chats:
            mtime, comment = _parse_last_user_comment_and_timestamp(chat)
            if newest_mtime is None or mtime > newest_mtime:
                newest_mtime = mtime
                newest_comment = comment
                newest_path = chat.path

        if newest_mtime is not None and newest_path is not None:
            results.append(
                AgentLastUsedInfo(
                    agent_id=agent_id,
                    agent_name=name,
                    description=description,
                    last_active=newest_mtime,
                    last_user_comment=newest_comment,
                    log_path=newest_path,
                )
            )

    results.sort(key=lambda item: item.last_active, reverse=True)
    return results[:limit]


def get_global_recent_sessions(
    limit: int = 10,
    agent_id: Optional[str] = None,
) -> List[AgentSessionInfo]:
    """Find and rank most recently active AI agent sessions across all repositories/workspaces."""
    import glob
    import sqlite3
    import urllib.parse

    registry = get_agent_cli_registry()
    sessions: List[AgentSessionInfo] = []
    seen: set[Tuple[str, str]] = set()

    # 1. Grok sessions
    if agent_id in (None, "grok"):
        grok_info = registry.get("grok")
        grok_name = grok_info.name if grok_info else "Grok Build"
        grok_patterns = [
            "~/.grok/sessions/**/summary.json",
            "/mnt/c/Users/*/.grok/sessions/**/summary.json",
        ]
        for pat in grok_patterns:
            for p_str in glob.glob(str(Path(pat).expanduser()), recursive=True):
                p = Path(p_str)
                try:
                    data = json.loads(p.read_text(encoding="utf-8", errors="replace"))
                except Exception:
                    data = {}
                sid = data.get("info", {}).get("id") or p.parent.name
                if ("grok", sid) in seen:
                    continue
                seen.add(("grok", sid))

                cwd_str = data.get("info", {}).get("cwd")
                if not cwd_str and "%" in p.parent.parent.name:
                    cwd_str = urllib.parse.unquote(p.parent.parent.name)
                cwd = Path(cwd_str) if cwd_str else None

                ts_str = data.get("last_active_at") or data.get("updated_at")
                dt: Optional[datetime] = None
                if ts_str:
                    try:
                        dt = datetime.fromisoformat(str(ts_str).replace("Z", "+00:00"))
                    except ValueError:
                        pass
                if dt is None:
                    dt = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)

                title = data.get("session_summary") or data.get("generated_title") or ""
                comment = data.get("last_turn_summary") or title

                reopen = (
                    f'cd "{cwd}" && grok --resume {sid}'
                    if cwd
                    else f"grok --resume {sid}"
                )
                sessions.append(
                    AgentSessionInfo(
                        agent_id="grok",
                        agent_name=grok_name,
                        session_id=sid,
                        cwd=cwd,
                        last_active=dt,
                        title=title,
                        last_user_comment=comment,
                        reopen_command=reopen,
                        log_path=p,
                    )
                )

    # 2. OpenCode DB sessions
    if agent_id in (None, "opencode"):
        oc_db = Path("~/.local/share/opencode/opencode.db").expanduser()
        if oc_db.exists():
            try:
                conn = sqlite3.connect(oc_db)
                c = conn.cursor()
                rows = c.execute(
                    "SELECT id, directory, title, time_updated FROM session WHERE time_updated IS NOT NULL"
                ).fetchall()
                oc_info = registry.get("opencode")
                oc_name = oc_info.name if oc_info else "OpenCode"
                for r in rows:
                    sid, directory, title, time_updated = r[0], r[1], r[2], r[3]
                    if ("opencode", sid) in seen:
                        continue
                    seen.add(("opencode", sid))
                    cwd = Path(directory) if directory else None
                    dt = datetime.fromtimestamp(time_updated / 1000, tz=timezone.utc)
                    reopen = f'cd "{cwd}" && opencode' if cwd else "opencode"
                    sessions.append(
                        AgentSessionInfo(
                            agent_id="opencode",
                            agent_name=oc_name,
                            session_id=sid,
                            cwd=cwd,
                            last_active=dt,
                            title=title or "",
                            last_user_comment=title or "",
                            reopen_command=reopen,
                            log_path=oc_db,
                        )
                    )
            except Exception:
                pass

    # 3. Discovered chats from multi-agent-registry (AGY, Claude Code, Aider, etc.)
    try:
        discovered_chats = discover_agent_chats(agent_id=agent_id)
    except Exception:
        discovered_chats = []

    for chat in discovered_chats:
        aid = chat.agent_id
        if aid in ("grok",):
            continue
        info = registry.get(aid)
        aname = info.name if info else aid.capitalize()

        if aid == "agy":
            parts = chat.path.parts
            if ".system_generated" in parts:
                idx = parts.index(".system_generated")
                sid = parts[idx - 1] if idx > 0 else chat.path.parent.name
            else:
                sid = chat.path.parent.name
            if (aid, sid) in seen:
                continue
            seen.add((aid, sid))
            cwd = _resolve_chat_workspace(chat)
            dt, comment = _parse_last_user_comment_and_timestamp(chat)
            reopen = (
                f'cd "{cwd}" && agy --resume {sid}' if cwd else f"agy --resume {sid}"
            )
        elif aid == "claude":
            sid = chat.path.stem
            if (aid, sid) in seen:
                continue
            seen.add((aid, sid))
            cwd = _resolve_chat_workspace(chat)
            dt, comment = _parse_last_user_comment_and_timestamp(chat)
            reopen = (
                f'cd "{cwd}" && claude --resume {sid}'
                if cwd
                else f"claude --resume {sid}"
            )
        elif aid == "opencode":
            sid = chat.path.stem
            if (aid, sid) in seen:
                continue
            seen.add((aid, sid))
            cwd = _resolve_chat_workspace(chat)
            dt, comment = _parse_last_user_comment_and_timestamp(chat)
            reopen = f'cd "{cwd}" && opencode' if cwd else "opencode"
        else:
            sid = chat.path.stem
            if (aid, sid) in seen:
                continue
            seen.add((aid, sid))
            cwd = _resolve_chat_workspace(chat) or chat.path.parent
            dt, comment = _parse_last_user_comment_and_timestamp(chat)
            bin_name = info.binary if info else aid
            reopen = f'cd "{cwd}" && {bin_name}' if cwd else bin_name

        sessions.append(
            AgentSessionInfo(
                agent_id=aid,
                agent_name=aname,
                session_id=sid,
                cwd=cwd,
                last_active=dt,
                title=comment[:80] if comment else "",
                last_user_comment=comment,
                reopen_command=reopen,
                log_path=chat.path,
            )
        )

    sessions.sort(key=lambda item: item.last_active, reverse=True)
    return sessions[:limit]
