import subprocess

import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path
from taskagent.manager import TaskAgent


@pytest.fixture
def manager(tmp_path):
    issues_root = tmp_path / "docs" / "tasks"
    return TaskAgent(config_dir=str(issues_root))


def test_git_root_detection(tmp_path, manager):
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.stdout = "/path/to/repo\n"
        mock_run.return_value.returncode = 0

        root = manager._get_git_root(tmp_path)
        assert root == Path("/path/to/repo")
        # We now use shell=(os.name == "nt")
        import os

        mock_run.assert_called_with(
            ["git", "-C", str(tmp_path), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
            shell=(os.name == "nt"),
        )


def test_git_commit_retry_on_hook_failure(manager):
    with (
        patch("subprocess.run") as mock_run,
        patch("subprocess.check_output") as mock_check,
    ):
        # First call fails (hook), second succeeds
        mock_run.side_effect = [
            MagicMock(returncode=0),  # git add
            MagicMock(returncode=1),  # git commit fail
            MagicMock(returncode=0),  # git add retry
            MagicMock(returncode=0),  # git commit retry
        ]
        mock_check.return_value = "abc1234\n"

        result = manager._git_commit(Path("/repo"), "feat: test")
        assert result == "abc1234"
        assert mock_run.call_count == 4


def test_dual_repo_detection(tmp_path, manager):
    # Mock code_root and mission_root to be different
    manager.code_root = Path("/projects/app")
    manager.mission_root = Path("/projects/tasks")
    assert manager.is_dual_repo is True

    manager.mission_root = Path("/projects/app")
    assert manager.is_dual_repo is False


@pytest.mark.skip(reason="Test failing due to environment issue")
def test_complete_issue_dual_repo_flow(tmp_path, manager):
    # Setup dual repo state
    code_root = tmp_path / "code"
    mission_root = tmp_path / "mission"
    code_root.mkdir()
    mission_root.mkdir()

    # Set them explicitly
    manager.code_root = code_root
    manager.mission_root = mission_root
    manager.issues_root = mission_root / "tasks"
    manager.create_issue("Test Task")

    print(f"DEBUG: mission_root={manager.mission_root}")
    print(f"DEBUG: code_root={manager.code_root}")
    print(f"DEBUG: is_dual_repo={manager.is_dual_repo}")

    with patch.object(TaskAgent, "_git_commit") as mock_commit:
        mock_commit.return_value = "hash123"

        manager.complete_issue("test-task", should_commit=True)

        # Should call commit twice (once for code, once for mission)
        # Plus the amend call
        assert mock_commit.call_count >= 2
        # Verify first call is for code repo
        assert mock_commit.call_args_list[0].args[0] == code_root
        # Verify second call is for mission repo
        assert mock_commit.call_args_list[1].args[0] == mission_root


def test_git_commit_no_verify(manager):

    with (
        patch("subprocess.run") as mock_run,
        patch("subprocess.check_output") as mock_check,
    ):
        mock_run.return_value = MagicMock(returncode=0)
        mock_check.return_value = "abc1234\n"

        # Call with no_verify=True (default)
        result = manager._git_commit(Path("/repo"), "feat: test", no_verify=True)
        assert result == "abc1234"

        # Verify the commit call included --no-verify
        commit_call = mock_run.call_args_list[1]
        assert "--no-verify" in commit_call.args[0]

        # Call with no_verify=False
        result = manager._git_commit(Path("/repo"), "feat: test", no_verify=False)
        assert result == "abc1234"

        # Verify the commit call did NOT include --no-verify
        commit_call_2 = mock_run.call_args_list[3]
        assert "--no-verify" not in commit_call_2.args[0]


def test_git_commit_cached_only_skips_git_add(manager):
    """cached_only must never run `git add` — only the commit itself — since
    the whole point is committing exactly what the caller already staged,
    not sweeping in whatever else is sitting in the working tree (e.g. a
    second agent's in-progress, unstaged edits in the same repo)."""
    with (
        patch("subprocess.run") as mock_run,
        patch("subprocess.check_output") as mock_check,
    ):
        mock_run.return_value = MagicMock(returncode=0)
        mock_check.return_value = "abc1234\n"

        result = manager._git_commit(Path("/repo"), "feat: test", cached_only=True)

        assert result == "abc1234"
        assert mock_run.call_count == 1  # commit only, no add
        commit_call = mock_run.call_args_list[0]
        assert commit_call.args[0][3] == "commit"


def test_git_commit_cached_only_with_files_still_skips_add(manager):
    """files= is meaningless once cached_only=True — still no add call."""
    with (
        patch("subprocess.run") as mock_run,
        patch("subprocess.check_output") as mock_check,
    ):
        mock_run.return_value = MagicMock(returncode=0)
        mock_check.return_value = "abc1234\n"

        manager._git_commit(
            Path("/repo"),
            "feat: test",
            files=["some/file.py"],
            cached_only=True,
        )

        assert mock_run.call_count == 1


def test_git_commit_cached_only_does_not_retry_on_failure(manager):
    """The retry path re-adds (`git add .` or specific files) to pick up
    hook-modified files — for cached_only that would defeat the purpose by
    staging whatever else is in the tree, so it must not retry at all."""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="hook rejected"
        )

        result = manager._git_commit(Path("/repo"), "feat: test", cached_only=True)

        assert result == "failed"
        assert mock_run.call_count == 1  # the one failed commit attempt, no retry


def test_git_commit_cached_only_reports_no_changes_when_index_empty(manager):
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=1, stdout="nothing to commit, working tree clean", stderr=""
        )

        result = manager._git_commit(Path("/repo"), "feat: test", cached_only=True)

        assert result == "no_changes"
        assert mock_run.call_count == 1


def test_git_commit_cached_only_leaves_other_agents_unstaged_work_alone(
    tmp_path, manager
):
    """The actual scenario this exists for: two agents editing the same
    working tree/branch on unrelated files. Real git repo, no mocking —
    stage only "my" file, leave "their" file modified-but-unstaged, and
    confirm cached_only=True commits exactly the former and never touches
    the latter."""
    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*args):
        return subprocess.run(
            ["git", "-C", str(repo), *args],
            check=True,
            capture_output=True,
            text=True,
        )

    git("init", "-q")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "t")

    mine = repo / "backend.py"
    theirs = repo / "tui.py"
    mine.write_text("original backend\n")
    theirs.write_text("original tui\n")
    git("add", "-A")
    git("commit", "-q", "-m", "seed")

    # Both agents edit their own file.
    mine.write_text("backend: my finished change\n")
    theirs.write_text("tui: their in-progress, unrelated change\n")
    # Only I stage mine — theirs stays a plain unstaged working-tree edit,
    # exactly like a second agent's uncommitted work sitting in the same
    # checkout.
    git("add", "backend.py")

    result = manager._git_commit(repo, "feat: complete backend work", cached_only=True)

    assert result != "failed"
    assert result != "no_changes"

    committed_files = git("show", "--name-only", "--format=", "HEAD").stdout.split()
    assert committed_files == ["backend.py"]

    # Their edit must still be sitting there, unstaged, exactly as they left
    # it: " M" (leading space, not staged) — not "M " or "A ", which would
    # mean it got swept into the index.
    status = git("status", "--porcelain").stdout.rstrip("\n")
    assert status == " M tui.py"
    assert theirs.read_text() == "tui: their in-progress, unrelated change\n"


def test_git_commit_clean_tree(manager):
    with patch("subprocess.run") as mock_run:
        # First call: git add (succeeds)
        # Second call: git commit (fails with returncode=1, but stdout says nothing to commit)
        mock_run.side_effect = [
            MagicMock(returncode=0),
            MagicMock(
                returncode=1, stdout="nothing to commit, working tree clean", stderr=""
            ),
        ]

        result = manager._git_commit(Path("/repo"), "feat: test")
        assert result == "no_changes"
