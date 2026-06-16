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
        Issue(name="Task 1", slug="task-1", status="pending", priority=1),
        Issue(
            name="Task 2",
            slug="task-2",
            status="draft",
            priority=2,
            dependencies=["task-1"],
        ),
    ]

    result = mcp.list_tasks()
    assert "[1] PENDING: Task 1" in result
    assert "[2] DRAFT: Task 2 (depends on: task-1)" in result


def test_mcp_create_task(mock_manager):
    mock_manager.create_issue.return_value = Issue(
        name="New Task", slug="new-task", status="pending"
    )

    result = mcp.create_task(
        "New Task", completion_criteria="Must pass tests", body="Desc"
    )
    assert "Created task: new-task (Status: pending)" in result
    mock_manager.create_issue.assert_called_once_with(
        "New Task", "Desc", False, None, completion_criteria="Must pass tests"
    )


def test_mcp_mark_task_active(mock_manager):
    mock_manager.slugify.return_value = "task-1"
    result = mcp.mark_task_active("Task 1")
    assert "Task 'task-1' is now active." in result
    mock_manager.move_to_active.assert_called_once_with("task-1")


def test_mcp_complete_task(mock_manager):
    mock_manager.slugify.return_value = "task-1"
    mock_manager.complete_issue.return_value = (
        Issue(name="Task 1", slug="task-1", status="completed"),
        "abc1234",
    )

    result = mcp.complete_task(
        "Task 1", solution="Implemented feature X", message="Done"
    )
    assert "Task 'task-1' completed. Commit: abc1234" in result
    mock_manager.complete_issue.assert_called_once_with(
        "task-1", commit_message="Done", solution_explanation="Implemented feature X"
    )


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
    mock_manager.restore_issue.return_value = Issue(
        name="Task 1", slug="task-1", status="active"
    )

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


def test_mcp_commit_repo_no_tasks_dir(mock_manager):
    mock_manager.issues_root = None
    result = mcp.commit_repo("msg")
    assert result == "Tasks directory not found."


def test_mcp_commit_repo_no_git_root(mock_manager, tmp_path):
    mock_manager.issues_root = tmp_path / "tasks"
    (tmp_path / "tasks").mkdir()
    mock_manager.mission_root = None
    result = mcp.commit_repo("msg")
    assert result == "No git repository found for tasks directory."


def test_mcp_commit_repo_no_changes(mock_manager, tmp_path):
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    mock_manager.issues_root = tasks_dir
    mock_manager.mission_root = tmp_path

    with patch("taskagent.mcp.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        result = mcp.commit_repo("msg")
        assert result == "No changes to commit."


def test_mcp_commit_repo_success(mock_manager, tmp_path):
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    mock_manager.issues_root = tasks_dir
    mock_manager.mission_root = tmp_path

    with patch("taskagent.mcp.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1)
        result = mcp.commit_repo("test commit")
        assert "Committed: test commit" in result


def test_mcp_commit_tasks_no_git_root():
    with patch("taskagent.mcp.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1)
        result = mcp.commit_tasks("msg")
        assert result == "No git repository found for task-agent project."


def test_mcp_commit_tasks_success():
    with patch("taskagent.mcp.subprocess.run") as mock_run:
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="/fake/root\n"),  # rev-parse
            MagicMock(),  # git add
            MagicMock(returncode=1),  # diff shows changes
            MagicMock(),  # git commit
        ]
        result = mcp.commit_tasks("test commit")
        assert "Committed: test commit" in result


def test_mcp_list_active_tasks(monkeypatch):
    class DummyIssue:
        def __init__(self, priority, status, name, dependencies=None):
            self.priority = priority
            self.status = status
            self.name = name
            self.dependencies = dependencies or []

    class DummyManager:
        def sync_mission(self):
            return [
                DummyIssue(1, "active", "Task 1"),
                DummyIssue(2, "pending", "Task 2"),
                DummyIssue(3, "active", "Task 3", ["Task 1"]),
            ]

    monkeypatch.setattr(mcp, "get_manager", lambda: DummyManager())
    result = mcp.list_active_tasks()
    assert "[1] ACTIVE: Task 1" in result
    assert "Task 2" not in result
    assert "[3] ACTIVE: Task 3 (depends on: Task 1)" in result


def test_mcp_update_task_dependencies(monkeypatch):
    called = []

    class DummyManager:
        def slugify(self, name):
            return name.lower().replace(" ", "-")

        def update_dependencies(self, slug, depends_on):
            called.append((slug, depends_on))

    monkeypatch.setattr(mcp, "get_manager", lambda: DummyManager())
    result = mcp.update_task_dependencies("Task One", "task-two,task-three")
    assert result == "Successfully updated dependencies for task 'task-one'."
    assert called == [("task-one", "task-two,task-three")]


EXPECTED_TOOLS = {
    "list_tasks",
    "list_active_tasks",
    "create_task",
    "promote_task",
    "demote_task",
    "mark_task_active",
    "complete_task",
    "search_task",
    "restore_task",
    "get_task_details",
    "update_task",
    "update_task_dependencies",
    "commit_repo",
    "commit_tasks",
}


def test_mcp_all_tools_registered():
    import asyncio

    tools = asyncio.run(mcp.mcp.list_tools())
    registered = {t.name for t in tools}
    assert registered == EXPECTED_TOOLS, (
        f"Missing: {EXPECTED_TOOLS - registered}, "
        f"Unexpected: {registered - EXPECTED_TOOLS}"
    )
