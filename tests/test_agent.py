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


class TestPerTaskAgentName:
    def test_generates_consistent_name(self):
        name1 = agent._per_task_agent_name("my-task", "minimal")
        name2 = agent._per_task_agent_name("my-task", "minimal")
        assert name1 == name2
        assert name1.startswith("agent-")
        assert "mytask" in name1

    def test_different_slugs_differ(self):
        name1 = agent._per_task_agent_name("task-a", "minimal")
        name2 = agent._per_task_agent_name("task-b", "minimal")
        assert name1 != name2

    def test_different_templates_differ(self):
        name1 = agent._per_task_agent_name("my-task", "minimal")
        name2 = agent._per_task_agent_name("my-task", "gh")
        assert name1 != name2

    def test_strips_special_chars(self):
        name = agent._per_task_agent_name("hello world!", "minimal")
        assert "hello" in name
        assert " " not in name
        assert "!" not in name

    def test_name_length(self):
        name = agent._per_task_agent_name("a" * 100, "minimal")
        # agent-{15chars}-{8hash} = 6+15+1+8 = 30
        assert len(name) <= 32


class TestPerTaskMetaPath:
    def test_returns_expected_path(self):
        path = agent._per_task_meta_path("my-task")
        assert path == Path(".gwt") / "my-task" / ".ta-agent.json"

    def test_uses_slug(self):
        path = agent._per_task_meta_path("hello-world")
        assert "hello-world" in str(path)


class TestStoreAndLoadMeta:
    def test_round_trip(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        task_slug = "my-task"
        (tmp_path / ".gwt" / task_slug).mkdir(parents=True)

        calls = []

        def mock_run(cmd, **kw):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        monkeypatch.setattr(agent.subprocess, "run", mock_run)

        agent.store_per_task_agent_meta(task_slug, "agent-mytask-abc12345", "minimal")

        # Verify sudo tee was called
        assert any("tee" in c for c in calls)
        assert any("sudo" in c for c in calls)

    def test_load_nonexistent_returns_none(self):
        assert agent.load_per_task_agent_meta("nonexistent") is None


class TestInitPerTaskAgent:
    def test_creates_agent_with_mocked_commands(self, monkeypatch):
        calls = []

        def mock_run(cmd, **kw):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        monkeypatch.setattr(agent.subprocess, "run", mock_run)
        monkeypatch.setattr(agent, "ensure_sudo", lambda: None)
        monkeypatch.setattr(agent, "_system_user_exists", lambda name: False)
        monkeypatch.setattr(
            agent.subprocess, "check_output", lambda cmd, **kw: "/home/user/repo\n"
        )
        monkeypatch.setattr(agent.shutil, "which", lambda cmd: "/usr/bin/ta")
        monkeypatch.setattr(Path, "mkdir", lambda self, **kw: None)
        monkeypatch.setattr(Path, "is_dir", lambda self: True)

        # Mock template loading to avoid file system dependency
        from taskagent import templates
        from taskagent.templates import Template

        tpl = Template(name="minimal", description="test")
        monkeypatch.setattr(templates, "load_template", lambda name: tpl)
        monkeypatch.setattr(templates, "materialize_dotfiles", lambda t, h, u: None)

        # Create a fake worktree
        monkeypatch.setattr(Path, "write_text", lambda self, content, **kw: None)

        result = agent.init_per_task_agent("my-task", "minimal")

        assert result["user"].startswith("agent-")
        assert "home" in result
        assert "ssh_key" in result
        assert "gitconfig" in result
        assert "profile" in result
        assert "sudoers" in result

        # Verify useradd was called
        assert any("useradd" in c for c in calls)

    def test_raises_if_worktree_missing(self, monkeypatch):
        monkeypatch.setattr(Path, "is_dir", lambda self: False)
        with pytest.raises(RuntimeError, match="Worktree not found"):
            agent.init_per_task_agent("nonexistent", "minimal")


class TestDestroyPerTaskAgent:
    def test_destroys_agent_when_meta_exists(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        task_slug = "my-task"
        meta_dir = tmp_path / ".gwt" / task_slug
        meta_dir.mkdir(parents=True)

        # Write meta file directly so load_per_task_agent_meta can find it
        (meta_dir / ".ta-agent.json").write_text(
            '{"user": "agent-mytask-abc12345", "template": "minimal", "task_slug": "my-task"}'
        )

        calls = []

        def mock_run(cmd, **kw):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        monkeypatch.setattr(agent.subprocess, "run", mock_run)
        monkeypatch.setattr(agent, "ensure_sudo", lambda: None)
        monkeypatch.setattr(agent, "_system_user_exists", lambda name: True)

        # Only mock Path.exists for the sudoers check, not for meta file
        orig_exists = Path.exists

        def selective_exists(self):
            if str(self).endswith("/etc/sudoers.d/ta-mytask-abc12345"):
                return True
            return orig_exists(self)

        monkeypatch.setattr(Path, "exists", selective_exists)

        agent.destroy_per_task_agent(task_slug)

        assert any("userdel" in str(c) for c in calls)

        # Meta file should be removed
        assert not agent.load_per_task_agent_meta(task_slug)

    def test_noop_when_no_meta(self, monkeypatch):
        calls = []

        def mock_run(cmd, **kw):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0)

        monkeypatch.setattr(agent.subprocess, "run", mock_run)

        agent.destroy_per_task_agent("nonexistent")

        # Should not attempt any user operations
        assert len(calls) == 0
