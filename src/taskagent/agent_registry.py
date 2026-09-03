"""Agent CLI Detection Registry for Task Agent.

Re-exports core agent definitions from the standalone `multi_agent_registry` package
while maintaining task-agent specific user plugin configuration helpers.
"""

import json
from pathlib import Path
from typing import List, Optional

from multi_agent_registry import (
    AgentCLIInfo,
    DiscoveredChat,
    discover_agent_chats,
    get_agent_cli_registry,
    inspect_agent_cli,
    inspect_all_agent_clis,
)

__all__ = [
    "AgentCLIInfo",
    "DiscoveredChat",
    "get_agent_cli_registry",
    "inspect_agent_cli",
    "inspect_all_agent_clis",
    "discover_agent_chats",
    "get_disabled_agent_plugins",
    "set_agent_plugin_enabled",
    "is_agent_plugin_enabled",
]


def get_disabled_agent_plugins() -> List[str]:
    """Load list of explicitly disabled agent plugins from task-agent user config."""
    config_file = Path.home() / ".config" / "task-agent" / "config.json"
    if config_file.is_file():
        try:
            data = json.loads(config_file.read_text(encoding="utf-8"))
            disabled = data.get("plugins", {}).get("disabled_agents", [])
            if isinstance(disabled, list):
                return [str(item) for item in disabled]
        except Exception:
            pass
    return []


def set_agent_plugin_enabled(agent_id: str, enabled: bool) -> None:
    """Enable or disable a specific agent plugin in task-agent user config."""
    config_dir = Path.home() / ".config" / "task-agent"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_file = config_dir / "config.json"

    data: dict = {}
    if config_file.is_file():
        try:
            data = json.loads(config_file.read_text(encoding="utf-8"))
        except Exception:
            data = {}

    plugins_cfg = data.setdefault("plugins", {})
    disabled = plugins_cfg.setdefault("disabled_agents", [])

    if enabled and agent_id in disabled:
        disabled.remove(agent_id)
    elif not enabled and agent_id not in disabled:
        disabled.append(agent_id)

    config_file.write_text(json.dumps(data, indent=2), encoding="utf-8")


def is_agent_plugin_enabled(
    agent_id: str, disabled_list: Optional[List[str]] = None
) -> bool:
    """Check if an agent plugin is enabled (enabled by default unless explicitly disabled)."""
    if disabled_list is None:
        disabled_list = get_disabled_agent_plugins()
    return agent_id not in disabled_list
