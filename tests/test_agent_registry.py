import pytest

from taskagent.agent_registry import (
    get_agent_cli_registry,
    inspect_agent_cli,
    inspect_all_agent_clis,
)


def test_agent_cli_registry_has_popular_clis():
    registry = get_agent_cli_registry()
    assert "claude" in registry
    assert "agy" in registry
    assert "opencode" in registry
    assert "copilot" in registry
    assert "grok" in registry
    assert "cursor" in registry
    assert "windsurf" in registry
    assert len(registry) >= 15


def test_inspect_agent_cli_known(monkeypatch, tmp_path):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)

    res = inspect_agent_cli("claude")
    assert res["id"] == "claude"
    assert res["name"] == "Claude Code"
    assert "installed" in res
    assert "mcp_registered" in res


def test_inspect_agent_cli_unknown():
    with pytest.raises(ValueError, match="Unknown agent CLI"):
        inspect_agent_cli("nonexistent_cli_xyz")


def test_inspect_all_agent_clis():
    all_results = inspect_all_agent_clis()
    assert isinstance(all_results, list)
    assert len(all_results) >= 15
    ids = [item["id"] for item in all_results]
    assert "claude" in ids
    assert "opencode" in ids


def test_agent_plugin_enable_disable_config(tmp_path, monkeypatch):
    from taskagent.agent_registry import (
        get_disabled_agent_plugins,
        is_agent_plugin_enabled,
        set_agent_plugin_enabled,
    )

    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)

    assert is_agent_plugin_enabled("grok") is True
    assert get_disabled_agent_plugins() == []

    set_agent_plugin_enabled("grok", enabled=False)
    assert is_agent_plugin_enabled("grok") is False
    assert "grok" in get_disabled_agent_plugins()

    set_agent_plugin_enabled("grok", enabled=True)
    assert is_agent_plugin_enabled("grok") is True
    assert get_disabled_agent_plugins() == []
