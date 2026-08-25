"""Discovery module for scanning agent chat log files."""

from dataclasses import dataclass
import glob
from pathlib import Path
from typing import List, Optional

from taskagent.agent_registry import AgentCLIInfo, get_agent_cli_registry
from taskagent.store_registry import project_host_root


@dataclass
class DiscoveredChat:
    """Represents a discovered agent chat log file."""

    agent_id: str
    path: Path
    parser_type: str


def _expand_pattern(pattern: str, host_root: Path) -> List[Path]:
    """Expand a chat log pattern into a list of file paths.

    If pattern starts with '~' or '/', it is treated as a global path.
    Otherwise, it is treated as relative to the repo's host root.
    """
    if pattern.startswith("~"):
        expanded = str(Path(pattern).expanduser())
        matched = glob.glob(expanded, recursive=True)
    elif pattern.startswith("/"):
        matched = glob.glob(pattern, recursive=True)
    else:
        joined = str(host_root / pattern)
        matched = glob.glob(joined, recursive=True)

    results: List[Path] = []
    for match in matched:
        p = Path(match)
        if p.is_file():
            results.append(p)
    return results


def discover_agent_chats(
    agent_id: Optional[str] = None,
    project_dir: Optional[Path] = None,
) -> List[DiscoveredChat]:
    """Discover chat log files for registered agent CLIs.

    Args:
        agent_id: Optional agent ID to filter discovery (e.g. 'agy', 'claude').
            If None, scans all registered agents with configured chat log patterns.
        project_dir: Optional starting directory for repo-scoping relative patterns.
            Defaults to current working directory. Resolves worktrees via
            `project_host_root()`.

    Returns:
        List of `DiscoveredChat` instances sorted by file path.

    Raises:
        ValueError: If `agent_id` is provided but not found in the registry.
    """
    registry = get_agent_cli_registry()

    if agent_id is not None:
        if agent_id not in registry:
            raise ValueError(f"Unknown agent CLI: '{agent_id}'")
        agents_to_scan: List[AgentCLIInfo] = [registry[agent_id]]
    else:
        agents_to_scan = list(registry.values())

    if project_dir is None:
        project_dir = Path.cwd()

    host_root = project_host_root(project_dir)

    discovered: List[DiscoveredChat] = []
    seen_paths = set()

    for agent in agents_to_scan:
        if not agent.chat_log_patterns:
            continue

        for pattern in agent.chat_log_patterns:
            found_paths = _expand_pattern(pattern, host_root)
            for path in found_paths:
                resolved = path.resolve()
                if resolved not in seen_paths:
                    seen_paths.add(resolved)
                    discovered.append(
                        DiscoveredChat(
                            agent_id=agent.id,
                            path=path,
                            parser_type=agent.chat_parser_type,
                        )
                    )

    discovered.sort(key=lambda item: item.path)
    return discovered
