import json
import os
import subprocess
from pathlib import Path
import pytest


@pytest.fixture
def plugin_dir():
    repo_root = Path(__file__).parent.parent
    return repo_root / "plugins" / "claude-code"


def test_plugin_json_structure(plugin_dir):
    plugin_json_path = plugin_dir / ".claude-plugin" / "plugin.json"
    assert plugin_json_path.is_file()

    with open(plugin_json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data.get("name") == "task-agent"
    assert "version" in data
    assert "description" in data
    assert "keywords" in data


def test_plugin_mcp_json(plugin_dir):
    mcp_json_path = plugin_dir / ".mcp.json"
    assert mcp_json_path.is_file()

    with open(mcp_json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert "mcpServers" in data
    assert "task_agent" in data["mcpServers"]
    server = data["mcpServers"]["task_agent"]
    assert server.get("command") == "uv"
    assert server.get("args") == ["run", "ta", "mcp"]


def test_plugin_hooks(plugin_dir):
    hooks_json_path = plugin_dir / "hooks" / "hooks.json"
    assert hooks_json_path.is_file()

    with open(hooks_json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert "hooks" in data
    assert "SessionStart" in data["hooks"]

    session_start_script = plugin_dir / "hooks" / "session_start.sh"
    assert session_start_script.is_file()
    assert os.access(session_start_script, os.X_OK)


def test_plugin_scripts(plugin_dir):
    statusline_script = plugin_dir / "scripts" / "statusline.sh"
    assert statusline_script.is_file()
    assert os.access(statusline_script, os.X_OK)


def test_plugin_skills(plugin_dir):
    skills_dir = plugin_dir / "skills"
    assert skills_dir.is_dir()

    expected_skills = ["next-task", "complete-task", "mission-workflow", "agent-import"]
    for skill_name in expected_skills:
        skill_file = skills_dir / skill_name / "SKILL.md"
        assert skill_file.is_file()
        content = skill_file.read_text(encoding="utf-8")
        assert "---" in content
        assert f"name: {skill_name}" in content


def test_session_start_execution(plugin_dir, tmp_path):
    session_start_script = plugin_dir / "hooks" / "session_start.sh"
    result = subprocess.run(
        [str(session_start_script)],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert result.returncode == 0
    assert "Task Agent Context" in result.stdout
