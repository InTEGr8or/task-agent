import pytest
from unittest.mock import MagicMock, patch
from taskagent import mcp
from taskagent.models.issue import Issue


@pytest.fixture
def mock_manager():
    with patch("taskagent.mcp.get_manager") as mock:
        manager = MagicMock()
        manager.should_show_strategy.return_value = False
        # Prefer slugify path in tests unless explicitly configured
        manager.resolve_issue_slug.return_value = None
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
    assert "[2] DRAFT: Task 2 (blocked by: task-1)" in result


def test_mcp_create_task(mock_manager):
    mock_manager.create_issue.return_value = Issue(
        name="New Task", slug="new-task", status="pending"
    )

    result = mcp.create_task(
        "New Task", completion_criteria="Must pass tests", body="Desc"
    )
    assert "Created task: new-task (Status: pending)" in result
    mock_manager.create_issue.assert_called_once_with(
        "New Task",
        "Desc",
        False,
        blocked_by=None,
        subtask_of=None,
        completion_criteria="Must pass tests",
    )


def test_mcp_create_tasks(mock_manager):
    mock_manager.create_issue.return_value = Issue(
        name="Task 1", slug="task-1", status="pending"
    )

    tasks = [
        {"title": "Task 1", "completion_criteria": "Must pass tests", "body": "Desc 1"},
        {"title": "Task 2", "completion_criteria": "Done 2", "draft": True},
    ]

    result = mcp.create_tasks(tasks)
    assert "Successfully created tasks:" in result
    assert "- task-1 (Status: pending)" in result
    assert mock_manager.create_issue.call_count == 2


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
    assert "Task Completed Successfully" in result
    assert "- **Slug**: `task-1`" in result
    assert "- **Git Commit SHA**: `abc1234`" in result
    assert "Implemented feature X" in result
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
        def __init__(self, priority, status, name, blocked_by=None, subtask_of=None):
            self.priority = priority
            self.status = status
            self.name = name
            self.blocked_by = blocked_by or []
            self.subtask_of = subtask_of

    class DummyManager:
        def sync_mission(self):
            return [
                DummyIssue(1, "active", "Task 1"),
                DummyIssue(2, "pending", "Task 2"),
                DummyIssue(3, "active", "Task 3", blocked_by=["Task 1"]),
            ]

    monkeypatch.setattr(mcp, "get_manager", lambda: DummyManager())
    result = mcp.list_active_tasks()
    assert "[1] ACTIVE: Task 1" in result
    assert "Task 2" not in result
    assert "[3] ACTIVE: Task 3 (blocked by: Task 1)" in result


class _SlugManager:
    """Minimal manager stub: slugify + identity resolve_issue_slug."""

    def slugify(self, name):
        return name.lower().replace(" ", "-")

    def resolve_issue_slug(self, name, include_completed=True, allow_title_match=True):
        return self.slugify(name)


def test_mcp_update_task_dependencies(monkeypatch):
    called = []

    class DummyManager(_SlugManager):
        def update_dependencies(self, slug, blocked_by):
            called.append((slug, blocked_by))

    monkeypatch.setattr(mcp, "get_manager", lambda: DummyManager())
    result = mcp.update_task_dependencies("Task One", "task-two,task-three")
    assert "Successfully set blocked_by for task 'task-one'" in result
    assert called == [("task-one", "task-two, task-three")]


def test_mcp_set_task_blocked_by(monkeypatch):
    called = []

    class DummyManager(_SlugManager):
        def update_dependencies(self, slug, blocked_by):
            called.append((slug, blocked_by))

    monkeypatch.setattr(mcp, "get_manager", lambda: DummyManager())
    result = mcp.set_task_blocked_by("Task One", "Task Two, Task Three")
    assert "Successfully set blocked_by for task 'task-one'" in result
    assert "task-two, task-three" in result
    assert called == [("task-one", "task-two, task-three")]

    result_clear = mcp.set_task_blocked_by("Task One", "")
    assert "Successfully cleared blocked_by for task 'task-one'" in result_clear
    assert called[-1] == ("task-one", "")


def test_mcp_add_and_remove_task_blocked_by(monkeypatch):
    class DummyManager(_SlugManager):
        def __init__(self):
            self.blocked = []

        def add_dependency(self, slug, blocked_by):
            for b in [x.strip() for x in blocked_by.split(",") if x.strip()]:
                if b not in self.blocked:
                    self.blocked.append(b)
            return Issue(
                name="Task One",
                slug=slug,
                blocked_by=list(self.blocked),
                status="pending",
            )

        def remove_dependency(self, slug, blocked_by):
            remove = {x.strip() for x in blocked_by.split(",") if x.strip()}
            self.blocked = [b for b in self.blocked if b not in remove]
            return Issue(
                name="Task One",
                slug=slug,
                blocked_by=list(self.blocked),
                status="pending",
            )

    mgr = DummyManager()
    monkeypatch.setattr(mcp, "get_manager", lambda: mgr)

    r1 = mcp.add_task_blocked_by("Task One", "dep-a")
    assert "Successfully added blocked_by" in r1
    assert "dep-a" in r1

    r2 = mcp.add_task_blocked_by("Task One", "dep-b")
    assert "dep-a" in r2 and "dep-b" in r2

    r3 = mcp.remove_task_blocked_by("Task One", "dep-a")
    assert "dep-b" in r3

    r4 = mcp.remove_task_blocked_by("Task One", "dep-b")
    assert "No blockers remain" in r4


def test_mcp_set_task_parent(monkeypatch):
    called = []

    class DummyManager(_SlugManager):
        def update_subtask_of(self, slug, parent):
            called.append((slug, parent))

    monkeypatch.setattr(mcp, "get_manager", lambda: DummyManager())
    result = mcp.set_task_parent("Child Task", "Parent Epic")
    assert result == "Successfully set parent of task 'child-task' to 'parent-epic'."
    assert called == [("child-task", "parent-epic")]

    result_clear = mcp.set_task_parent("Child Task", "")
    assert result_clear == "Successfully cleared parent of task 'child-task'."
    assert called[-1] == ("child-task", None)


def test_mcp_bulk_set_task_blocked_by(monkeypatch):
    class DummyManager(_SlugManager):
        def bulk_update_dependencies(self, slugs, blocked_by):
            return [
                {"slug": slugs[0], "ok": True, "error": None},
                {"slug": slugs[1], "ok": False, "error": "not found"},
            ]

    monkeypatch.setattr(mcp, "get_manager", lambda: DummyManager())
    result = mcp.bulk_set_task_blocked_by("Task A, Task B", "blocker")
    assert "1 succeeded, 1 failed" in result
    assert "OK: task-a" in result
    assert "FAIL: task-b" in result


def test_mcp_bulk_set_task_parent(monkeypatch):
    class DummyManager(_SlugManager):
        def bulk_update_subtask_of(self, slugs, parent):
            assert parent == "epic"
            return [{"slug": s, "ok": True, "error": None} for s in slugs]

    monkeypatch.setattr(mcp, "get_manager", lambda: DummyManager())
    result = mcp.bulk_set_task_parent("a, b, c", "Epic")
    assert "3 succeeded, 0 failed" in result
    assert "OK: a" in result


def test_mcp_get_strategy(mock_manager):
    mock_manager.get_strategy.return_value = None
    assert mcp.get_strategy() == "No strategy defined yet."

    mock_manager.get_strategy.return_value = (
        "# Core Strategy\n<!-- comment -->\nFocus on quality."
    )
    assert mcp.get_strategy() == "# Core Strategy\nFocus on quality."


def test_mcp_list_tasks_with_strategy(mock_manager):
    mock_manager.sync_mission.return_value = [
        Issue(name="Task 1", slug="task-1", status="pending", priority=1)
    ]
    mock_manager.should_show_strategy.return_value = True
    mock_manager.get_strategy.return_value = (
        "# Core Strategy\n<!-- comment -->\nFocus on quality."
    )

    result = mcp.list_tasks()
    assert "## 📐 Core Strategy" in result
    assert "Focus on quality." in result
    assert "[1] PENDING: Task 1" in result
    mock_manager.update_strategy_last_shown.assert_called_once()


def test_mcp_list_tasks_without_strategy(mock_manager):
    mock_manager.sync_mission.return_value = [
        Issue(name="Task 1", slug="task-1", status="pending", priority=1)
    ]
    mock_manager.should_show_strategy.return_value = False

    result = mcp.list_tasks()
    assert "## 📐" not in result
    assert "[1] PENDING: Task 1" in result


EXPECTED_TOOLS = {
    "list_tasks",
    "list_active_tasks",
    "create_task",
    "create_tasks",
    "promote_task",
    "demote_task",
    "mark_task_active",
    "complete_task",
    "search_task",
    "restore_task",
    "get_task_details",
    "update_task",
    "update_task_dependencies",
    "set_task_blocked_by",
    "add_task_blocked_by",
    "remove_task_blocked_by",
    "set_task_parent",
    "bulk_set_task_blocked_by",
    "bulk_set_task_parent",
    "commit_repo",
    "commit_tasks",
    "get_strategy",
}


def test_mcp_all_tools_registered():
    import asyncio

    tools = asyncio.run(mcp.mcp.list_tools())
    registered = {t.name for t in tools}
    assert registered == EXPECTED_TOOLS, (
        f"Missing: {EXPECTED_TOOLS - registered}, "
        f"Unexpected: {registered - EXPECTED_TOOLS}"
    )
