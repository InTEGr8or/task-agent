import pytest
from unittest.mock import MagicMock, patch
from taskagent import mcp
from taskagent.models.issue import Issue


@pytest.fixture
def mock_manager():
    with patch("taskagent.mcp.get_manager") as mock:
        manager = MagicMock()
        mock.return_value = manager
        yield manager


def test_mcp_list_tasks(mock_manager):
    mock_manager.sync_mission.return_value = [
        Issue(slug="task-1", status="pending", priority=1),
        Issue(slug="task-2", status="draft", priority=2, dependencies=["task-1"]),
    ]

    result = mcp.list_tasks()
    assert "[1] PENDING: task-1" in result
    assert "[2] DRAFT: task-2 (depends on: task-1)" in result


def test_mcp_create_task(mock_manager):
    mock_manager.create_issue.return_value = Issue(slug="new-task", status="pending")

    result = mcp.create_task("New Task", body="Desc")
    assert "Created task: new-task (Status: pending)" in result
    mock_manager.create_issue.assert_called_once_with("New Task", "Desc", False, None)


def test_mcp_mark_task_active(mock_manager):
    mock_manager.slugify.return_value = "task-1"
    result = mcp.mark_task_active("Task 1")
    assert "Task 'task-1' is now active." in result
    mock_manager.move_to_active.assert_called_once_with("task-1")


def test_mcp_complete_task(mock_manager):
    mock_manager.slugify.return_value = "task-1"
    mock_manager.complete_issue.return_value = (
        Issue(slug="task-1", status="completed"),
        "abc1234",
    )

    result = mcp.complete_task("Task 1", message="Done")
    assert "Task 'task-1' completed. Commit: abc1234" in result
    mock_manager.complete_issue.assert_called_once_with("task-1", commit_message="Done")


def test_mcp_search_task(mock_manager, tmp_path):
    mock_manager.slugify.return_value = "task-1"
    issue_file = tmp_path / "pending" / "task-1.md"
    issue_file.parent.mkdir()
    issue_file.write_text("content")
    mock_manager.find_issue_file.return_value = issue_file

    result = mcp.search_task("Task 1")
    assert "found in [bold]pending[/bold]" in result
    mock_manager.find_issue_file.assert_called_once_with(
        "task-1", include_completed=True
    )


def test_mcp_restore_task(mock_manager):
    mock_manager.slugify.return_value = "task-1"
    mock_manager.restore_issue.return_value = Issue(slug="task-1", status="active")

    result = mcp.restore_task("Task 1", status="active")
    assert "Task 'task-1' restored to 'active'" in result
    mock_manager.restore_issue.assert_called_once_with("task-1", to_status="active")


def test_mcp_get_task_details(mock_manager, tmp_path):
    mock_manager.slugify.return_value = "task-1"
    issue_file = tmp_path / "task-1.md"
    issue_file.write_text("# Task 1\nContent")
    mock_manager.find_issue_file.return_value = issue_file

    result = mcp.get_task_details("Task 1")
    assert "# Task 1" in result
    assert "Content" in result
