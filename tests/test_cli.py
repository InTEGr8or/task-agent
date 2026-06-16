import pytest
from pathlib import Path
from taskagent.cli import (
    cmd_new,
    cmd_done,
    cmd_ingest,
    cmd_promote,
    get_project_version,
    main,
)
from taskagent.manager import TaskAgent
from rich.console import Console
from datetime import datetime


@pytest.fixture
def temp_issues_dir(tmp_path):
    """Create a temporary issues structure."""
    issues_root = tmp_path / "docs" / "tasks"
    for subdir in ["pending", "draft", "active", "completed"]:
        (issues_root / subdir).mkdir(parents=True)
    return issues_root


@pytest.fixture
def manager(temp_issues_dir):
    return TaskAgent(config_dir=str(temp_issues_dir))


def test_slugify(manager):
    assert manager.slugify("Hello World") == "hello-world"
    assert manager.slugify("Task: Do Something!") == "task-do-something"
    assert manager.slugify("Already-Slugified") == "already-slugified"


def test_slugify_dots(manager):
    assert manager.slugify("1.1 Setup CI") == "1.1-setup-ci"
    assert manager.slugify("v2.0 Migration") == "v2.0-migration"
    assert manager.slugify("bug.1.2.3 Fix") == "bug.1.2.3-fix"
    assert manager.slugify("no.dots") == "no.dots"


def test_cmd_new_file(manager, temp_issues_dir):
    console = Console()
    cmd_new(console, manager, "Test Task", "Task Body", draft=False)

    issue_file = temp_issues_dir / "pending" / "test-task" / "README.md"
    assert issue_file.exists()
    assert "# Test Task" in issue_file.read_text()

    issues = manager.load_mission()
    assert len(issues) == 1
    assert issues[0].name == "Test Task"
    assert issues[0].slug == "test-task"
    assert issues[0].status == "pending"


def test_cmd_new_dir(manager, temp_issues_dir):
    console = Console()
    cmd_new(
        console,
        manager,
        "Dir Task",
        "Body",
        draft=True,
        as_dir=True,
    )

    readme = temp_issues_dir / "draft" / "dir-task" / "README.md"
    assert readme.exists()

    issues = manager.load_mission()
    assert issues[0].name == "Dir Task"
    assert issues[0].slug == "dir-task"
    assert issues[0].status == "draft"


def test_cmd_done(manager, temp_issues_dir):
    console = Console()
    cmd_new(console, manager, "Done Task", "Body", draft=False)

    cmd_done(console, manager, "done-task", should_commit=False)

    # Should be in completed/year/
    year = str(datetime.now().year)
    completed_file = temp_issues_dir / "completed" / year / "done-task" / "README.md"
    assert completed_file.exists()
    assert "Completed in commit" in completed_file.read_text()

    # Should be removed from mission
    issues = manager.load_mission()
    assert len(issues) == 0


def test_cmd_ingest(manager, temp_issues_dir):
    console = Console()
    # Create files manually
    (temp_issues_dir / "pending" / "task-1").mkdir()
    (temp_issues_dir / "pending" / "task-1" / "README.md").write_text("# Task 1")
    (temp_issues_dir / "draft" / "task-2").mkdir()
    (temp_issues_dir / "draft" / "task-2" / "README.md").write_text(
        "# Task 2\n\n**Depends on:** task-1"
    )

    cmd_ingest(console, manager)

    issues = manager.load_mission()
    assert len(issues) == 2
    assert issues[0].slug == "task-1"
    assert issues[1].slug == "task-2"
    assert issues[1].dependencies == ["task-1"]

    assert (temp_issues_dir / ".task-agent" / "datapackage.json").exists()


def test_cmd_start(manager, temp_issues_dir, monkeypatch):
    from taskagent import cli
    import subprocess

    console = Console()
    cmd_new(console, manager, "Start Task", "Body", draft=False)

    calls = []

    def mock_run(args, **kwargs):
        calls.append(args)

        class MockCompletedProcess:
            returncode = 0
            stdout = ""
            stderr = ""

        return MockCompletedProcess()

    monkeypatch.setattr(subprocess, "run", mock_run)

    cli.cmd_start(console, manager, "start-task")

    assert (temp_issues_dir / "active" / "start-task" / "README.md").exists()
    assert not (temp_issues_dir / "pending" / "start-task" / "README.md").exists()
    assert len(calls) > 0


def test_cmd_run(manager, temp_issues_dir, monkeypatch):
    from taskagent import cli
    import subprocess
    from pathlib import Path

    console = Console()

    # Create an active issue
    cmd_new(console, manager, "Run Task", "Body", draft=False)
    cli.cmd_active(console, manager, "run-task", silent=True)

    calls = []

    def mock_run(args, **kwargs):
        calls.append((args, kwargs.get("env", {})))

        class MockCompletedProcess:
            returncode = 0

        return MockCompletedProcess()

    monkeypatch.setattr(subprocess, "run", mock_run)

    original_exists = Path.exists

    def mock_exists(self):
        if str(self).endswith(".ta/worker"):
            return True
        return original_exists(self)

    monkeypatch.setattr(Path, "exists", mock_exists)
    monkeypatch.setattr("os.access", lambda path, mode: True)

    cli.cmd_run(console, manager, "run-task")

    assert len(calls) == 1
    args, env = calls[0]
    assert str(args[0]).endswith(".ta/worker")
    assert env["TA_SLUG"] == "run-task"


def test_cmd_promote(manager, temp_issues_dir):
    console = Console()
    cmd_new(console, manager, "Draft Task", "Body", draft=True)

    cmd_promote(console, manager, "draft-t")

    assert (temp_issues_dir / "pending" / "draft-task" / "README.md").exists()
    assert not (temp_issues_dir / "draft" / "draft-task" / "README.md").exists()

    issues = manager.load_mission()
    assert issues[0].status == "pending"


def test_prior_command_is_registered():
    import sys
    from unittest.mock import patch

    with patch.object(sys, "argv", ["ta", "--help"]):
        with pytest.raises(SystemExit):
            main()

    with patch.object(sys, "argv", ["ta", "prior", "--help"]):
        with pytest.raises(SystemExit):
            main()


def test_version_detection_pyproject(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "1.2.3"\n')
    version, source = get_project_version(tmp_path)
    assert version == "1.2.3"
    assert source == "pyproject.toml"


def test_version_detection_package_json(tmp_path):
    (tmp_path / "package.json").write_text('{"name": "test", "version": "2.3.4"}')
    version, source = get_project_version(tmp_path)
    assert version == "2.3.4"
    assert source == "package.json"


def test_version_detection_cargo_toml(tmp_path):
    (tmp_path / "Cargo.toml").write_text(
        '[package]\nname = "test"\nversion = "3.4.5"\n'
    )
    version, source = get_project_version(tmp_path)
    assert version == "3.4.5"
    assert source == "Cargo.toml"


def test_version_detection_csproj(tmp_path):
    (tmp_path / "Test.csproj").write_text(
        "<Project><PropertyGroup><Version>4.5.6</Version></PropertyGroup></Project>"
    )
    version, source = get_project_version(tmp_path)
    assert version == "4.5.6"
    assert source == "Test.csproj"


def test_version_detection_pom_xml(tmp_path):
    (tmp_path / "pom.xml").write_text("<project><version>5.6.7</version></project>")
    version, source = get_project_version(tmp_path)
    assert version == "5.6.7"
    assert source == "pom.xml"


def test_version_detection_build_gradle(tmp_path):
    (tmp_path / "build.gradle").write_text(
        'plugins {\n  id "java"\n}\nversion = "6.7.8"\n'
    )
    version, source = get_project_version(tmp_path)
    assert version == "6.7.8"
    assert source == "build.gradle"


def test_version_detection_priority(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "1.0.0"\n')
    (tmp_path / "package.json").write_text('{"name": "test", "version": "2.0.0"}')
    (tmp_path / "Cargo.toml").write_text(
        '[package]\nname = "test"\nversion = "3.0.0"\n'
    )
    version, source = get_project_version(tmp_path)
    assert version == "1.0.0"
    assert source == "pyproject.toml"


def test_cmd_init_mcp_claude(tmp_path):
    from unittest.mock import patch, MagicMock
    from taskagent.cli import cmd_init_mcp

    console = Console()

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock()
        cmd_init_mcp(console, claude=True)

        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert call_args[0] == "claude"
        assert call_args[1] == "mcp"
        assert call_args[2] == "add"
        assert call_args[3] == "task-agent"
        assert call_args[4] == "--"
        assert call_args[5] == "uv"
        assert "run" in call_args


def test_detect_current_slug_from_git():
    from unittest.mock import patch, MagicMock
    from taskagent.cli import detect_current_slug_from_git

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="issue/my-cool-task\n", returncode=0)
        assert detect_current_slug_from_git() == "my-cool-task"

        mock_run.return_value = MagicMock(stdout="main\n", returncode=0)
        assert detect_current_slug_from_git() is None

        mock_run.side_effect = Exception("git failed")
        assert detect_current_slug_from_git() is None


def test_find_worktree_path_for_slug(tmp_path):
    from unittest.mock import patch, MagicMock
    from taskagent.cli import find_worktree_path_for_slug

    with patch("subprocess.run") as mock_run:
        mock_output = (
            "worktree /path/to/main-repo\n"
            "branch refs/heads/main\n"
            "\n"
            "worktree /path/to/worktrees/some-slug\n"
            "branch refs/heads/issue/some-slug\n"
        )
        mock_run.return_value = MagicMock(stdout=mock_output, returncode=0)
        assert find_worktree_path_for_slug("some-slug") == Path(
            "/path/to/worktrees/some-slug"
        )
        assert find_worktree_path_for_slug("other-slug") is None


def test_cmd_done_cleanup(manager, temp_issues_dir, tmp_path):
    from unittest.mock import patch
    from taskagent.cli import cmd_done

    console = Console()
    cmd_new(console, manager, "Done Clean Task", "Body", draft=False)

    # Let's mock subprocess.run to simulate:
    # 1. find_worktree_path_for_slug finds a registered worktree under tmp_path
    # 2. CWD is NOT inside the worktree
    # 3. Removing the worktree and branch succeeds
    worktree_mock_path = tmp_path / "gwt-mock"
    worktree_mock_path.mkdir()

    mock_worktree_output = (
        f"worktree {worktree_mock_path}\nbranch refs/heads/issue/done-clean-task\n"
    )

    def mock_run(cmd, **kwargs):
        cmd_str = " ".join(cmd) if isinstance(cmd, list) else cmd

        class MockCompletedProcess:
            returncode = 0
            stdout = ""
            stderr = ""

        res = MockCompletedProcess()
        if "worktree list" in cmd_str:
            res.stdout = mock_worktree_output
        elif "worktree remove" in cmd_str:
            # Delete mock directory to simulate success
            import shutil

            shutil.rmtree(worktree_mock_path)
        elif "rev-parse" in cmd_str:
            res.stdout = "abcdef12"
        return res

    with patch("subprocess.run", side_effect=mock_run):
        cmd_done(console, manager, "done-clean-task", should_commit=False)
        assert not worktree_mock_path.exists()
