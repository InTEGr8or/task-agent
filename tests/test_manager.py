import pytest
from taskagent.manager import TaskAgent
from datetime import datetime


@pytest.fixture
def manager(tmp_path):
    issues_root = tmp_path / "docs" / "issues"
    return TaskAgent(config_dir=str(issues_root))


def test_api_create_issue(manager):
    issue = manager.create_issue("API Task", body="Body from API")
    assert issue.slug == "api-task"
    assert issue.status == "pending"

    # Check filesystem
    file = manager.issues_root / "pending" / "api-task.md"
    assert file.exists()
    assert "Body from API" in file.read_text()


def test_slugify_hashes(manager):
    assert manager.slugify("# My Title") == "my-title"
    assert manager.slugify("Issue #123: Fix") == "issue-123-fix"
    assert manager.slugify("### Heavily Hashed ###") == "heavily-hashed"


def test_api_ingest_with_titles(manager):
    issues_root = manager.issues_root
    # Create file manually with a specific title
    (issues_root / "pending" / "task-1.md").write_text("# My Custom Title\nContent")

    # Ingest
    manager.save_mission([])
    manager.ingest_issues()

    issues = manager.load_mission()
    assert issues[0].name == "My Custom Title"
    assert issues[0].slug == "task-1"


def test_mission_file_protection(manager):
    # Initial state
    manager.create_issue("Protect Me")
    manager.save_datapackage()
    manager.lock_mission_files()

    import os
    import stat

    # Check read-only bit
    mode = os.stat(manager.mission_path).st_mode
    assert not (mode & stat.S_IWRITE)

    dp_path = manager.issues_root / "datapackage.json"
    mode_dp = os.stat(dp_path).st_mode
    assert not (mode_dp & stat.S_IWRITE)

    # Test that save_mission can still write (by toggling bit)
    manager.save_mission(manager.load_mission())
    # Should still be read-only after operation
    assert not (os.stat(manager.mission_path).st_mode & stat.S_IWRITE)


def test_find_issue_file_resilient(manager):
    # Create a file with underscores manually
    pending_dir = manager.issues_root / "pending"
    pending_dir.mkdir(parents=True, exist_ok=True)
    file_with_underscores = pending_dir / "my_test_issue.md"
    file_with_underscores.write_text("# My Test Issue")

    # Try to find it using hyphenated slug
    found = manager.find_issue_file("my-test-issue")
    assert found is not None
    assert found.name == "my_test_issue.md"


def test_api_complete_issue(manager):
    manager.create_issue("Complete Me")
    # complete_issue returns (issue, commit_hash)
    issue, commit = manager.complete_issue("complete-me", should_commit=False)

    assert issue.slug == "complete-me"
    assert issue.status == "completed"

    year = str(datetime.now().year)
    assert (manager.issues_root / "completed" / year / "complete-me.md").exists()


def test_api_restore_issue(manager):
    manager.create_issue("Restore Me")
    manager.complete_issue("restore-me", should_commit=False)

    # Verify it is in completed
    year = str(datetime.now().year)
    assert (manager.issues_root / "completed" / year / "restore-me.md").exists()

    # Restore it
    manager.restore_issue("restore-me", to_status="active")

    assert (manager.issues_root / "active" / "restore-me.md").exists()
    assert not (manager.issues_root / "completed" / year / "restore-me.md").exists()

    issues = manager.load_mission()
    issue = next(i for i in issues if i.slug == "restore-me")
    assert issue.status == "active"


def test_api_sync_mission(manager):
    manager.create_issue("Task A", draft=True)
    manager.create_issue("Task B", draft=False)

    issues = manager.sync_mission()
    # pending (B) should be before draft (A)
    assert issues[0].slug == "task-b"
    assert issues[1].slug == "task-a"


def test_api_demote_issue(manager):
    manager.create_issue("Demote Me")
    # Starts as pending
    assert (manager.issues_root / "pending" / "demote-me.md").exists()

    manager.demote_issue("demote-me")
    assert not (manager.issues_root / "pending" / "demote-me.md").exists()
    assert (manager.issues_root / "draft" / "demote-me.md").exists()


def test_api_promote_cascades_to_children(manager):
    """When a parent is promoted, draft children are also promoted."""
    manager.create_issue("Parent", draft=True)
    manager.create_issue("Child", draft=True)

    manager.add_dependency("child", "parent")

    manager.promote_issue("parent")

    assert (manager.issues_root / "pending" / "parent.md").exists()
    assert (manager.issues_root / "pending" / "child.md").exists()

    issues = manager.load_mission()
    parent = next(i for i in issues if i.slug == "parent")
    child = next(i for i in issues if i.slug == "child")
    assert parent.status == "pending"
    assert child.status == "pending"


def test_api_demote_cascades_to_children(manager):
    """When a parent is demoted, pending children are also demoted."""
    manager.create_issue("Parent", draft=False)
    manager.create_issue("Child", draft=False)

    manager.add_dependency("child", "parent")

    manager.demote_issue("parent")

    assert (manager.issues_root / "draft" / "parent.md").exists()
    assert (manager.issues_root / "draft" / "child.md").exists()

    issues = manager.load_mission()
    parent = next(i for i in issues if i.slug == "parent")
    child = next(i for i in issues if i.slug == "child")
    assert parent.status == "draft"
    assert child.status == "draft"


def test_api_move_to_active(manager):
    manager.create_issue("Active Me")
    manager.move_to_active("active-me")

    assert (manager.issues_root / "active" / "active-me.md").exists()
    issues = manager.load_mission()
    assert issues[0].status == "active"


def test_api_prioritize_issue(manager):
    manager.create_issue("Task 1")
    manager.create_issue("Task 2")
    manager.create_issue("Task 3")

    # Initial: 1, 2, 3
    manager.prioritize_issue("task-2", "up")
    issues = manager.load_mission()
    assert issues[0].slug == "task-2"
    assert issues[1].slug == "task-1"

    manager.prioritize_issue("task-2", "down")
    issues = manager.load_mission()
    assert issues[1].slug == "task-2"


def test_api_ingest_issues(manager, tmp_path):
    issues_root = manager.issues_root
    # Create directory-based issue manually
    dir_task = issues_root / "pending" / "dir-task"
    dir_task.mkdir()
    (dir_task / "README.md").write_text("# Dir Task\n**Depends on:** other-task")

    # Create file-based issue manually
    (issues_root / "draft" / "file-task.md").write_text("# File Task")

    # Wipe mission.usv
    manager.save_mission([])

    num_new, num_removed = manager.ingest_issues()
    assert num_new == 2

    issues = manager.load_mission()
    slugs = [i.slug for i in issues]
    assert "dir-task" in slugs
    assert "file-task" in slugs

    # Check dependencies extracted
    dir_issue = next(i for i in issues if i.slug == "dir-task")
    assert dir_issue.dependencies == ["other-task"]


def test_api_add_dependency(manager):
    manager.create_issue("Task A")
    manager.create_issue("Task B")

    manager.add_dependency("task-b", "task-a")

    issue_file = manager.find_issue_file("task-b")
    content = issue_file.read_text()
    assert "**Depends on:** task-a" in content


def test_api_add_dependency_existing(manager):
    manager.create_issue("Task A")
    manager.create_issue("Task B", body="**Depends on:** task-a")

    # Add same dependency again
    manager.add_dependency("task-b", "task-a")

    issue_file = manager.find_issue_file("task-b")
    deps = manager.extract_deps(issue_file)
    assert deps == ["task-a"]


def test_api_remove_dependency(manager):
    manager.create_issue("Task A")
    manager.create_issue("Task B", body="**Depends on:** task-a")

    manager.remove_dependency("task-b", "task-a")

    issue_file = manager.find_issue_file("task-b")
    deps = manager.extract_deps(issue_file)
    assert deps == []


def test_api_add_multiple_dependencies(manager):
    manager.create_issue("Task A")
    manager.create_issue("Task B")
    manager.create_issue("Task C")

    manager.add_dependency("task-c", "task-a")
    manager.add_dependency("task-c", "task-b")

    issue_file = manager.find_issue_file("task-c")
    deps = manager.extract_deps(issue_file)
    assert "task-a" in deps
    assert "task-b" in deps
