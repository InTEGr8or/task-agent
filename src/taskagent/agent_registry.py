"""Agent CLI Detection Registry for Task Agent.

Provides a unified registry of popular agent CLIs, detection logic, global/project
MCP configuration paths, and plugin installation helpers.
"""

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import shutil
from typing import Dict, List, Optional


@dataclass
class AgentCLIInfo:
    id: str
    name: str
    binary: str
    description: str
    config_paths: List[Path] = field(default_factory=list)
    mcp_support: bool = True
    mcp_command_example: str = ""
    plugin_support: bool = False
    plugin_path: Optional[Path] = None


def get_agent_cli_registry() -> Dict[str, AgentCLIInfo]:
    home = Path.home()
    return {
        "claude": AgentCLIInfo(
            id="claude",
            name="Claude Code",
            binary="claude",
            description="Anthropic's agentic coding CLI tool",
            config_paths=[home / ".claude.json", home / ".claude" / "config.json"],
            mcp_support=True,
            mcp_command_example="ta init-mcp --claude",
            plugin_support=True,
            plugin_path=home / ".claude" / "plugins",
        ),
        "agy": AgentCLIInfo(
            id="agy",
            name="Antigravity CLI",
            binary="agy",
            description="Google DeepMind Antigravity CLI",
            config_paths=[home / ".gemini" / "antigravity-cli" / "mcp_config.json"],
            mcp_support=True,
            mcp_command_example="ta init-mcp --agy",
            plugin_support=True,
            plugin_path=home / ".gemini" / "antigravity-cli" / "plugins",
        ),
        "opencode": AgentCLIInfo(
            id="opencode",
            name="OpenCode",
            binary="opencode",
            description="Open-source agentic coding workspace and TUI",
            config_paths=[home / ".config" / "opencode" / "opencode.json"],
            mcp_support=True,
            mcp_command_example="ta init-mcp --opencode",
            plugin_support=True,
            plugin_path=home / ".config" / "opencode" / "plugins",
        ),
        "copilot": AgentCLIInfo(
            id="copilot",
            name="GitHub Copilot CLI",
            binary="copilot",
            description="GitHub Copilot CLI agent",
            config_paths=[home / ".config" / "github-copilot" / "config.json"],
            mcp_support=True,
            mcp_command_example="ta init-mcp --copilot",
            plugin_support=True,
            plugin_path=home / ".config" / "github-copilot" / "plugins",
        ),
        "grok": AgentCLIInfo(
            id="grok",
            name="Grok Build",
            binary="grok",
            description="xAI Grok coding assistant CLI",
            config_paths=[home / ".config" / "grok" / "config.json"],
            mcp_support=True,
            mcp_command_example="ta init-mcp --agent grok",
            plugin_support=True,
        ),
        "cursor": AgentCLIInfo(
            id="cursor",
            name="Cursor CLI",
            binary="cursor",
            description="Cursor AI editor CLI interface",
            config_paths=[
                home / ".cursor" / "mcp.json",
                home / ".config" / "Cursor" / "mcp.json",
            ],
            mcp_support=True,
            mcp_command_example="ta init-mcp --print",
            plugin_support=True,
        ),
        "windsurf": AgentCLIInfo(
            id="windsurf",
            name="Windsurf",
            binary="windsurf",
            description="Codeium Windsurf AI IDE CLI",
            config_paths=[home / ".codeium" / "windsurf" / "mcp_config.json"],
            mcp_support=True,
            mcp_command_example="ta init-mcp --print",
            plugin_support=True,
        ),
        "aider": AgentCLIInfo(
            id="aider",
            name="Aider",
            binary="aider",
            description="AI pair programming in your terminal",
            config_paths=[home / ".aider.conf.yml"],
            mcp_support=False,
            plugin_support=False,
        ),
        "codex": AgentCLIInfo(
            id="codex",
            name="Codex CLI / ADK Worker",
            binary="codex",
            description="OpenAI Codex CLI harness",
            config_paths=[home / ".codex" / "config.json"],
            mcp_support=True,
            plugin_support=False,
        ),
        "continue": AgentCLIInfo(
            id="continue",
            name="Continue",
            binary="continue",
            description="Open-source AI code assistant",
            config_paths=[home / ".continue" / "config.json"],
            mcp_support=True,
            plugin_support=True,
        ),
        "cline": AgentCLIInfo(
            id="cline",
            name="Cline",
            binary="cline",
            description="Autonomous coding agent extension & CLI",
            config_paths=[home / ".cline" / "mcp_settings.json"],
            mcp_support=True,
            plugin_support=True,
        ),
        "roo": AgentCLIInfo(
            id="roo",
            name="Roo Code",
            binary="roo",
            description="Roo Code AI coding assistant",
            config_paths=[home / ".roo" / "mcp_settings.json"],
            mcp_support=True,
            plugin_support=True,
        ),
        "goose": AgentCLIInfo(
            id="goose",
            name="Goose",
            binary="goose",
            description="Block's open-source AI agent framework",
            config_paths=[home / ".config" / "goose" / "config.yaml"],
            mcp_support=True,
            plugin_support=False,
        ),
        "sgpt": AgentCLIInfo(
            id="sgpt",
            name="ShellGPT",
            binary="sgpt",
            description="Command-line productivity tool powered by AI",
            config_paths=[home / ".config" / "shell_gpt" / ".sgptrc"],
            mcp_support=False,
            plugin_support=False,
        ),
        "interpreter": AgentCLIInfo(
            id="interpreter",
            name="Open Interpreter",
            binary="interpreter",
            description="Natural language interface to computer capabilities",
            config_paths=[home / ".config" / "open-interpreter" / "config.yaml"],
            mcp_support=False,
            plugin_support=False,
        ),
    }


def inspect_agent_cli(agent_id: str) -> dict:
    """Inspect local installation and MCP registration status for an agent CLI."""
    registry = get_agent_cli_registry()
    if agent_id not in registry:
        raise ValueError(f"Unknown agent CLI: '{agent_id}'")

    info = registry[agent_id]
    installed = shutil.which(info.binary) is not None
    mcp_registered = False

    for config_path in info.config_paths:
        if config_path.is_file():
            try:
                content = config_path.read_text(encoding="utf-8")
                if "task_agent" in content or "task-agent" in content:
                    mcp_registered = True
                    break
            except Exception:
                pass

    plugin_installed = False
    if info.plugin_path and info.plugin_path.exists():
        try:
            if any("task-agent" in p.name for p in info.plugin_path.iterdir()):
                plugin_installed = True
        except Exception:
            pass

    return {
        "id": info.id,
        "name": info.name,
        "binary": info.binary,
        "description": info.description,
        "installed": installed,
        "mcp_support": info.mcp_support,
        "mcp_registered": mcp_registered,
        "plugin_support": info.plugin_support,
        "plugin_installed": plugin_installed,
        "mcp_command_example": info.mcp_command_example,
    }


def inspect_all_agent_clis() -> List[dict]:
    """Inspect local installation status for all registered agent CLIs."""
    registry = get_agent_cli_registry()
    return [inspect_agent_cli(agent_id) for agent_id in registry]
