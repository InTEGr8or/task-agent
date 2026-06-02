import pytest
import subprocess
from pathlib import Path
from taskagent import agent


def test_ensure_sudo_success(monkeypatch):
    monkeypatch.setattr(agent.shutil, "which", lambda cmd: "/usr/bin/sudo")
    calls = []

    def mock_run(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(agent.subprocess, "run", mock_run)

    agent.ensure_sudo()
    assert any("sudo" in c for c in calls[0])


def test_ensure_sudo_fails_when_missing(monkeypatch):
    monkeypatch.setattr(agent.shutil, "which", lambda cmd: None)
    with pytest.raises(RuntimeError, match="sudo is required"):
        agent.ensure_sudo()


def test_ensure_sudo_fails_when_not_passwordless(monkeypatch):
    monkeypatch.setattr(agent.shutil, "which", lambda cmd: "/usr/bin/sudo")

    def mock_run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 1, stderr="a password is required")

    monkeypatch.setattr(agent.subprocess, "run", mock_run)

    with pytest.raises(RuntimeError, match="sudo requires a password"):
        agent.ensure_sudo()


def test_system_user_exists_true(monkeypatch):
    def mock_run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(agent.subprocess, "run", mock_run)

    assert agent._system_user_exists("agent-test") is True


def test_system_user_exists_false(monkeypatch):
    def mock_run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 1)

    monkeypatch.setattr(agent.subprocess, "run", mock_run)

    assert agent._system_user_exists("agent-test") is False


def test_init_agent_creates_user_and_resources(monkeypatch):
    calls = []

    def mock_run(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(agent.subprocess, "run", mock_run)
    monkeypatch.setattr(
        agent.shutil,
        "which",
        lambda cmd: (
            "/usr/bin/sudo"
            if cmd == "sudo"
            else "/usr/bin/uv"
            if cmd == "uv"
            else "/usr/bin/ta"
        ),
    )

    # Don't try to find the real git root
    monkeypatch.setattr(
        agent.subprocess, "check_output", lambda cmd, **kw: "/home/user/repo\n"
    )

    # Mock user existence check
    monkeypatch.setattr(agent, "_system_user_exists", lambda name: False)

    # Mock Path.mkdir, Path.exists to avoid filesystem interaction
    monkeypatch.setattr(Path, "mkdir", lambda self, **kw: None)
    monkeypatch.setattr(Path, "exists", lambda self: False)

    result = agent.init_agent("test-agent")

    assert result["user"] == "agent-test-agent"
    assert "home" in result
    assert "ssh_key" in result
    assert "gitconfig" in result
    assert "profile" in result
    assert "local_bin" in result
    assert "sudoers" in result

    # Verify useradd was called
    assert any("useradd" in c for c in calls)

    # Verify uv symlink was created
    assert any("ln" in c for c in calls)

    # Verify .profile was created
    assert any("profile" in " ".join(c) for c in calls)


def test_init_agent_raises_if_user_exists(monkeypatch):
    monkeypatch.setattr(agent, "_system_user_exists", lambda name: True)
    monkeypatch.setattr(agent, "ensure_sudo", lambda: None)

    with pytest.raises(RuntimeError, match="already exists"):
        agent.init_agent("test-agent")


def test_init_agent_raises_on_useradd_failure(monkeypatch):
    monkeypatch.setattr(agent, "ensure_sudo", lambda: None)
    monkeypatch.setattr(agent, "_system_user_exists", lambda name: False)
    monkeypatch.setattr(Path, "mkdir", lambda self, **kw: None)

    def mock_run(cmd, **kw):
        if "useradd" in cmd:
            return subprocess.CompletedProcess(cmd, 1, stderr="permission denied")
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(agent.subprocess, "run", mock_run)

    with pytest.raises(RuntimeError, match="Failed to create user"):
        agent.init_agent("test-agent")


def test_destroy_agent_removes_user_and_sudoers(monkeypatch):
    calls = []

    def mock_run(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(agent.subprocess, "run", mock_run)
    monkeypatch.setattr(agent.shutil, "which", lambda cmd: "/usr/bin/sudo")
    monkeypatch.setattr(agent, "_system_user_exists", lambda name: True)
    monkeypatch.setattr(Path, "exists", lambda self: True)

    agent.destroy_agent("test-agent")

    assert any("userdel" in c for c in calls)
    assert any("rm" in c for c in calls)


def test_destroy_agent_raises_if_not_exists(monkeypatch):
    monkeypatch.setattr(agent, "_system_user_exists", lambda name: False)
    monkeypatch.setattr(agent, "ensure_sudo", lambda: None)

    with pytest.raises(RuntimeError, match="does not exist"):
        agent.destroy_agent("test-agent")


def test_get_agent_user_returns_name(monkeypatch):
    monkeypatch.setattr(agent, "_system_user_exists", lambda name: True)
    assert agent.get_agent_user("test-agent") == "agent-test-agent"


def test_get_agent_user_raises_if_not_exists(monkeypatch):
    monkeypatch.setattr(agent, "_system_user_exists", lambda name: False)
    with pytest.raises(RuntimeError, match="does not exist"):
        agent.get_agent_user("test-agent")


def test_get_worktree_path():
    path = agent.get_worktree_path("my-task")
    assert path == Path(".gwt") / "my-task"


def test_set_worktree_permissions(monkeypatch):
    calls = []

    def mock_run(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(agent.subprocess, "run", mock_run)

    # Patch Path.exists so the worktree check passes
    monkeypatch.setattr(Path, "exists", lambda self: True)

    agent.set_worktree_permissions("my-task", "agent-test")

    assert any("chgrp" in str(c) for c in calls)
    assert any("chmod" in str(c) for c in calls)


def test_set_worktree_permissions_raises_if_missing():
    with pytest.raises(RuntimeError, match="Worktree not found"):
        agent.set_worktree_permissions("nonexistent", "agent-test")
