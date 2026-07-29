from pathlib import Path
from unittest.mock import patch, MagicMock
from rich.console import Console


def test_antigravity_plugin_structure():
    plugin_dir = Path(__file__).parent.parent / "plugins" / "antigravity"
    assert plugin_dir.is_dir()
    assert (plugin_dir / ".gemini-plugin" / "plugin.json").is_file()
    assert (plugin_dir / ".mcp.json").is_file()
    assert (plugin_dir / "hooks" / "hooks.json").is_file()
    assert (plugin_dir / "hooks" / "session_start.sh").is_file()
    assert (plugin_dir / "rules" / "task_agent.md").is_file()
    assert (plugin_dir / "scripts" / "statusline.sh").is_file()
    assert (plugin_dir / "skills" / "next-task" / "SKILL.md").is_file()
    assert (plugin_dir / "skills" / "complete-task" / "SKILL.md").is_file()


def test_cmd_init_plugin_agy(tmp_path, monkeypatch):
    from taskagent.cli import cmd_init_plugin

    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
    monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)

    console = Console(force_terminal=False)
    cmd_init_plugin(console, agy=True)

    plugin_dir = (
        fake_home / ".gemini" / "antigravity-cli" / "plugins" / "task-agent"
    )
    assert plugin_dir.is_dir()
    assert (plugin_dir / ".gemini-plugin" / "plugin.json").is_file()
    assert (plugin_dir / "rules" / "task_agent.md").is_file()

    config_path = fake_home / ".gemini" / "antigravity-cli" / "mcp_config.json"
    assert config_path.is_file()
