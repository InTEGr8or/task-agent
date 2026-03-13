import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path
from taskagent.manager import TaskAgent


@pytest.fixture
def manager(tmp_path):
    issues_root = tmp_path / "docs" / "issues"
    return TaskAgent(config_dir=str(issues_root))


def test_git_root_detection(tmp_path, manager):
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.stdout = "/path/to/repo\n"
        mock_run.return_value.returncode = 0

        root = manager._get_git_root(tmp_path)
        assert root == Path("/path/to/repo")
        mock_run.assert_called_with(
            ["git", "-C", str(tmp_path), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
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


def test_complete_issue_dual_repo_flow(tmp_path, manager):
    # Setup dual repo state
    manager.code_root = tmp_path / "code"
    manager.mission_root = tmp_path / "mission"
    manager.code_root.mkdir()
    manager.mission_root.mkdir()

    # Create issue in mission repo
    manager.issues_root = manager.mission_root / "issues"
    manager.create_issue("Test Task")

    with patch.object(TaskAgent, "_git_commit") as mock_commit:
        mock_commit.return_value = "hash123"

        manager.complete_issue("test-task", should_commit=True)

        # Should call commit twice (once for code, once for mission)
        # Plus the amend call
        assert mock_commit.call_count >= 2
        # Verify first call is for code repo
        assert mock_commit.call_args_list[0].args[0] == manager.code_root
        # Verify second call is for mission repo
        assert mock_commit.call_args_list[1].args[0] == manager.mission_root
