import pytest
from taskagent.manager import TaskAgent
from datetime import datetime


@pytest.fixture
def manager(tmp_path):
    issues_root = tmp_path / "docs" / "tasks"
    m = TaskAgent(config_dir=str(issues_root))
    # Ensure .task-agent directory exists for tests
    (issues_root / ".task-agent").mkdir(exist_ok=True)
    return m


def test_api_create_issue(manager):
    issue = manager.create_issue("API Task", body="Body from API")
    assert issue.slug == "api-task"
    assert issue.status == "pending"

    # Check filesystem
    file = manager.issues_root / "pending" / "api-task" / "README.md"
    assert file.exists()
    assert "Body from API" in file.read_text()


def test_slugify_hashes(manager):
    assert manager.slugify("# My Title") == "my-title"
    assert manager.slugify("Issue #123: Fix") == "issue-123-fix"
    assert manager.slugify("### Heavily Hashed ###") == "heavily-hashed"


def test_slugify_with_dots(manager):
    assert manager.slugify("1.1 Setup CI") == "1.1-setup-ci"
    assert manager.slugify("v2.0") == "v2.0"


def test_create_issue_with_dotted_title(manager):
    issue = manager.create_issue("1.1 Dotted Task", "Body with dots: v2.0 here")
    assert issue.slug == "1.1-dotted-task"
    issue_file = manager.find_issue_file(issue.slug)
    assert issue_file is not None
    assert issue_file.exists()
    content = issue_file.read_text()
    assert "# 1.1 Dotted Task" in content
    assert "v2.0" in content


def test_ingest_with_dotted_slug(manager):
    issues_root = manager.issues_root
    slug = "1.1.dotted.task"
    (issues_root / "pending" / slug).mkdir(parents=True)
    (issues_root / "pending" / slug / "README.md").write_text(
        "# 1.1 Dotted Task\nContent"
    )

    manager.save_mission([])
    manager.ingest_issues()

    issues = manager.load_mission()
    assert len(issues) == 1
    assert issues[0].slug == slug
    assert issues[0].name == "1.1 Dotted Task"


def test_api_ingest_with_titles(manager):
    issues_root = manager.issues_root
    # Create file manually with a specific title
    (issues_root / "pending" / "task-1").mkdir(parents=True)
    (issues_root / "pending" / "task-1" / "README.md").write_text(
        "# My Custom Title\nContent"
    )

    # Ingest
    manager.save_mission([])
    manager.ingest_issues()

    issues = manager.load_mission()
    assert len(issues) == 1
    assert issues[0].name == "My Custom Title"
    assert issues[0].slug == "task-1"


def test_mission_file_protection(manager):
    # Initial state
    manager.create_issue("Protect Me")
    manager.save_datapackage()
    manager.lock_mission_files()

    import os
    import stat

    # Check read-only bit on mission.usv in .task-agent/
    mode = os.stat(manager.mission_path).st_mode
    assert not (mode & stat.S_IWRITE)
    assert "mission.usv" in str(manager.mission_path)
    assert ".task-agent" in str(manager.mission_path)

    # Check datapackage.json in .task-agent/
    dp_path = manager.mission_dir / "datapackage.json"
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
    file_with_underscores = pending_dir / "my-test-issue" / "README.md"
    file_with_underscores.parent.mkdir(parents=True, exist_ok=True)
    file_with_underscores.write_text("# My Test Issue")

    # Try to find it using hyphenated slug
    found = manager.find_issue_file("my_test_issue")
    assert found is not None
    assert found.parent.name == "my-test-issue"


def test_api_complete_issue(manager):
    manager.create_issue("Complete Me")
    # complete_issue returns (issue, commit_hash)
    issue, commit = manager.complete_issue("complete-me", should_commit=False)

    assert issue.slug == "complete-me"
    assert issue.status == "completed"

    year = str(datetime.now().year)
    assert (
        manager.issues_root / "completed" / year / "complete-me" / "README.md"
    ).exists()


def test_api_restore_issue(manager):
    manager.create_issue("Restore Me")
    manager.complete_issue("restore-me", should_commit=False)

    # Verify it is in completed
    year = str(datetime.now().year)
    assert (
        manager.issues_root / "completed" / year / "restore-me" / "README.md"
    ).exists()

    # Restore it
    manager.restore_issue("restore-me", to_status="active")

    assert (manager.issues_root / "active" / "restore-me" / "README.md").exists()
    assert not (
        manager.issues_root / "completed" / year / "restore-me" / "README.md"
    ).exists()

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
    assert (manager.issues_root / "pending" / "demote-me" / "README.md").exists()

    manager.demote_issue("demote-me")
    assert not (manager.issues_root / "pending" / "demote-me" / "README.md").exists()
    assert (manager.issues_root / "draft" / "demote-me" / "README.md").exists()


def test_api_demote_active_to_pending(manager):
    manager.create_issue("Active Demote")
    manager.move_to_active("active-demote")
    assert (manager.issues_root / "active" / "active-demote" / "README.md").exists()

    manager.demote_issue("active-demote")
    assert not (manager.issues_root / "active" / "active-demote" / "README.md").exists()
    assert (manager.issues_root / "pending" / "active-demote" / "README.md").exists()

    issues = manager.load_mission()
    issue = next(i for i in issues if i.slug == "active-demote")
    assert issue.status == "pending"


def test_api_promote_cascades_to_children(manager):
    """When a parent is promoted, draft children are also promoted."""
    manager.create_issue("Parent", draft=True)
    manager.create_issue("Child", draft=True)

    manager.add_dependency("child", "parent")

    manager.promote_issue("parent")

    assert (manager.issues_root / "pending" / "parent" / "README.md").exists()
    assert (manager.issues_root / "pending" / "child" / "README.md").exists()

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

    assert (manager.issues_root / "draft" / "parent" / "README.md").exists()
    assert (manager.issues_root / "draft" / "child" / "README.md").exists()

    issues = manager.load_mission()
    parent = next(i for i in issues if i.slug == "parent")
    child = next(i for i in issues if i.slug == "child")
    assert parent.status == "draft"
    assert child.status == "draft"


def test_api_move_to_active(manager):
    manager.create_issue("Active Me")
    manager.move_to_active("active-me")

    assert (manager.issues_root / "active" / "active-me" / "README.md").exists()
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
    dir_task.mkdir(parents=True)
    (dir_task / "README.md").write_text("# Dir Task\n**Depends on:** other-task")

    # Create file-based issue manually
    file_task = issues_root / "draft" / "file-task"
    file_task.mkdir(parents=True)
    (file_task / "README.md").write_text("# File Task")

    # Wipe mission.usv
    manager.save_mission([])

    # Must trigger folder migration for existing old-style files (if any existed, but here we created new-style manually)
    num_new, num_removed = manager.ingest_issues()
    assert num_new == 2

    issues = manager.load_mission()
    slugs = [i.slug for i in issues]
    assert "dir-task" in slugs
    assert "file-task" in slugs

    # Check dependencies extracted
    dir_issue = next(i for i in issues if i.slug == "dir-task")
    assert dir_issue.dependencies == ["other-task"]
    assert dir_issue.blocked_by == ["other-task"]

    # Verify automatic migration of the markdown file headers
    updated_readme = (dir_task / "README.md").read_text()
    assert "**Blocked by:** other-task" in updated_readme
    assert "Depends on" not in updated_readme


def test_api_add_dependency(manager):
    manager.create_issue("Task A")
    manager.create_issue("Task B")

    manager.add_dependency("task-b", "task-a")

    issue_file = manager.find_issue_file("task-b")
    content = issue_file.read_text()
    assert "**Blocked by:** task-a" in content


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


def test_api_soft_delete(manager):
    manager.create_issue("Delete Me", body="Will be archived")
    assert manager.find_issue_file("delete-me")

    issue = manager.soft_delete_issue("delete-me")

    assert issue.slug == "delete-me"
    assert issue.status == "deleted"

    # File should be in deleted/ now
    assert (manager.issues_root / "deleted" / "delete-me" / "README.md").exists()

    # deleted.usv should exist with the entry
    deleted_usv = manager.issues_root / "deleted" / "deleted.usv"
    assert deleted_usv.exists()
    content = deleted_usv.read_text()
    assert "delete-me" in content
    assert "pending" in content  # original status

    # Should be removed from mission
    issues = manager.load_mission()
    assert not any(i.slug == "delete-me" for i in issues)


def test_api_update_dependencies(manager):
    manager.create_issue("Task A")
    manager.create_issue("Task B")
    manager.create_issue("Task C")

    # Update dependencies of B to depend on A
    manager.update_dependencies("task-b", "task-a")
    issue_file = manager.find_issue_file("task-b")
    assert manager.extract_deps(issue_file) == ["task-a"]

    # Try updating B to depend on C and A
    manager.update_dependencies("task-b", "task-c, task-a")
    assert manager.extract_deps(issue_file) == ["task-c", "task-a"]

    # Try introducing a self-loop (should fail)
    with pytest.raises(ValueError, match="cannot depend on itself"):
        manager.update_dependencies("task-b", "task-b")

    # Try introducing a cycle: A depends on B (B already depends on A)
    with pytest.raises(ValueError, match="introduce a cycle"):
        manager.update_dependencies("task-a", "task-b")

    # Try updating with non-existent task
    with pytest.raises(ValueError, match="does not exist"):
        manager.update_dependencies("task-b", "non-existent-task")

    # Clear dependencies
    manager.update_dependencies("task-b", "")
    assert manager.extract_deps(issue_file) == []


def test_get_strategy_returns_none_when_no_file(manager):
    assert manager.get_strategy() is None


def test_get_strategy_reads_content(manager):
    manager.strategy_dir.mkdir(parents=True, exist_ok=True)
    manager.strategy_file.write_text("# Test Strategy\nContent here", encoding="utf-8")
    assert manager.get_strategy() == "# Test Strategy\nContent here"


def test_strategy_meta_roundtrip(manager):
    assert manager.get_strategy_meta() == {}
    manager.update_strategy_last_shown()
    meta = manager.get_strategy_meta()
    assert "last_shown_at" in meta
    # Try parsing it
    datetime.fromisoformat(meta["last_shown_at"])


def test_should_show_strategy_no_file_returns_false(manager):
    assert not manager.should_show_strategy()


def test_should_show_strategy_first_time_returns_true(manager):
    manager.init_strategy()
    assert manager.should_show_strategy()


def test_should_show_strategy_within_cooldown_returns_false(manager):
    manager.init_strategy()
    manager.update_strategy_last_shown()
    assert not manager.should_show_strategy()


def test_should_show_strategy_after_cooldown_returns_true(manager):
    from datetime import datetime as dt, timedelta
    import json

    manager.init_strategy()
    # Mock last shown far in the past
    past_time = dt.now() - timedelta(hours=3)
    manager.strategy_dir.mkdir(parents=True, exist_ok=True)
    with manager.strategy_meta_file.open("w", encoding="utf-8") as f:
        json.dump({"last_shown_at": past_time.isoformat()}, f)
    assert manager.should_show_strategy(cooldown_hours=2.0)
    assert not manager.should_show_strategy(cooldown_hours=4.0)


def test_init_strategy_creates_files(manager):
    assert not manager.strategy_dir.exists()
    assert not manager.strategy_file.exists()
    path = manager.init_strategy()
    assert path == manager.strategy_file
    assert manager.strategy_dir.exists()
    assert manager.strategy_file.exists()
    content = manager.strategy_file.read_text(encoding="utf-8")
    assert "# Strategy" in content
