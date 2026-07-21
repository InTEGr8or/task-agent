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


def test_sanitize_document_filename(manager):
    assert manager.sanitize_document_filename("findings") == "findings.md"
    assert manager.sanitize_document_filename("findings.md") == "findings.md"
    assert manager.sanitize_document_filename("a_b-2.notes.md") == "a_b-2.notes.md"
    with pytest.raises(ValueError):
        manager.sanitize_document_filename("README.md")
    with pytest.raises(ValueError):
        manager.sanitize_document_filename("../escape.md")
    with pytest.raises(ValueError):
        manager.sanitize_document_filename("path/to/x.md")
    with pytest.raises(ValueError):
        manager.sanitize_document_filename("")


def test_secondary_documents_list_format_add(manager):
    issue = manager.create_issue("Doc Task", body="Primary body", as_dir=True)
    assert manager.list_secondary_documents(issue.slug) == []

    primary_only = manager.format_task_details(issue.slug)
    assert "Primary body" in primary_only
    assert "Secondary documents" not in primary_only

    path = manager.add_task_document(
        issue.slug, "findings.md", "# Findings\n\nPlugin plan.\n"
    )
    assert path.name == "findings.md"
    assert path.exists()
    assert "Plugin plan" in path.read_text()

    docs = manager.list_secondary_documents(issue.slug)
    assert [d.name for d in docs] == ["findings.md"]

    full = manager.format_task_details(issue.slug)
    assert "Primary body" in full
    assert "## Secondary documents" in full
    assert "### findings.md" in full
    assert "Plugin plan" in full

    with pytest.raises(FileExistsError):
        manager.add_task_document(issue.slug, "findings.md", "again")

    manager.add_task_document(
        issue.slug, "findings.md", "# Overwritten\n", overwrite=True
    )
    assert "Overwritten" in path.read_text()


def test_add_task_document_migrates_file_based(manager, monkeypatch):
    """File-based tasks are migrated to folders when a document is added."""
    # Bypass init_project's migrate_all_to_folders during create
    monkeypatch.setattr(manager, "init_project", lambda: (0, 0))
    monkeypatch.setattr(manager, "_commit_task_store", lambda *a, **k: "no_changes")

    status_dir = manager.issues_root / "pending"
    status_dir.mkdir(parents=True, exist_ok=True)
    flat = status_dir / "flat-task.md"
    flat.write_text(
        "---\ncreated_at: 2026-01-01T00:00:00\n---\n\n# Flat Task\n\nBody\n"
    )
    # Manually register in mission
    from taskagent.models.issue import Issue

    manager.save_mission(
        [Issue(name="Flat Task", slug="flat-task", status="pending", priority=1)]
    )

    dest = manager.add_task_document("flat-task", "notes.md", "Note body")
    assert not flat.exists()
    assert dest == manager.issues_root / "pending" / "flat-task" / "notes.md"
    assert dest.exists()
    readme = manager.issues_root / "pending" / "flat-task" / "README.md"
    assert readme.exists()
    assert "Body" in readme.read_text()


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

    now = datetime.now()
    assert (
        manager.issues_root
        / "completed"
        / str(now.year)
        / f"{now.month:02d}"
        / "complete-me"
        / "README.md"
    ).exists()


def test_api_complete_issue_with_metrics(manager):
    from taskagent.models.metric import SubtaskMetric

    manager.create_issue("Metric Task")
    metrics = SubtaskMetric.from_completion_args(
        model="grok-4",
        provider="xai",
        agent_harness="grok",
        input_tokens=1000,
        output_tokens=200,
        tokens_accuracy="measured",
        duration_seconds=90,
        cost_usd=0.01,
    )
    issue, _ = manager.complete_issue(
        "metric-task",
        should_commit=False,
        solution_explanation="Used metrics",
        metrics=metrics,
    )
    assert issue.status == "completed"

    now = datetime.now()
    task_dir = (
        manager.issues_root
        / "completed"
        / str(now.year)
        / f"{now.month:02d}"
        / "metric-task"
    )
    readme = (task_dir / "README.md").read_text(encoding="utf-8")
    assert "## Agent Metrics" in readme
    assert "grok-4" in readme
    assert "## Solution" in readme

    meta_path = task_dir / "meta.json"
    assert meta_path.exists()
    import json

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["status"] == "completed"
    assert meta["metrics"]["model"] == "grok-4"
    assert meta["metrics"]["agent_harness"] == "grok"
    assert meta["metrics"]["input_tokens"] == 1000
    assert meta["metrics"]["tokens_accuracy"] == "measured"


def test_api_complete_issue_with_open_subtasks(manager):
    manager.create_issue("Parent Epic")
    manager.create_issue("Subtask Task", subtask_of="parent-epic")

    import pytest

    with pytest.raises(
        ValueError,
        match="Cannot complete task 'parent-epic' because it has open sub-tasks: subtask-task",
    ):
        manager.complete_issue("parent-epic", should_commit=False)

    # Complete the subtask first
    manager.complete_issue("subtask-task", should_commit=False)

    # Now completing the parent epic should succeed
    issue, commit = manager.complete_issue("parent-epic", should_commit=False)
    assert issue.status == "completed"


def test_api_restore_issue(manager):
    manager.create_issue("Restore Me")
    manager.complete_issue("restore-me", should_commit=False)

    # Verify it is in completed
    now = datetime.now()
    assert (
        manager.issues_root
        / "completed"
        / str(now.year)
        / f"{now.month:02d}"
        / "restore-me"
        / "README.md"
    ).exists()

    # Restore it
    manager.restore_issue("restore-me", to_status="active")

    assert (manager.issues_root / "active" / "restore-me" / "README.md").exists()
    assert not (
        manager.issues_root
        / "completed"
        / str(now.year)
        / f"{now.month:02d}"
        / "restore-me"
        / "README.md"
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


def test_api_sync_mission_auto_ingest(manager):
    # Create an issue using the manager API (which creates files and adds to mission)
    manager.create_issue("Task A", draft=False)

    # Simulate a file manually added/created on disk
    pending_dir = manager.issues_root / "pending" / "task-b"
    pending_dir.mkdir(parents=True, exist_ok=True)
    readme = pending_dir / "README.md"
    readme.write_text("# Task B\n\n## Completion Criteria\n\nCC 2", encoding="utf-8")

    # Sync mission: this should auto-ingest the manually added task-b!
    issues = manager.sync_mission()

    # Verify both tasks exist and are in the synced issues list
    slugs = [i.slug for i in issues]
    assert "task-a" in slugs
    assert "task-b" in slugs


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

    manager.update_subtask_of("child", "parent")

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

    manager.update_subtask_of("child", "parent")

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
    assert "blocked_by: other-task" in updated_readme
    assert "Depends on" not in updated_readme

    # Verify updating existing issue relationships from disk
    (dir_task / "README.md").write_text("# Dir Task\n**Subtask of:** new-parent-task")
    num_new, num_removed = manager.ingest_issues()
    assert num_new == 0

    issues = manager.load_mission()
    dir_issue = next(i for i in issues if i.slug == "dir-task")
    assert dir_issue.subtask_of == "new-parent-task"
    assert dir_issue.blocked_by == []


def test_api_add_dependency(manager):
    manager.create_issue("Task A")
    manager.create_issue("Task B")

    manager.add_dependency("task-b", "task-a")

    issue_file = manager.find_issue_file("task-b")
    content = issue_file.read_text()
    assert "blocked_by: task-a" in content


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
    manager.create_issue("Task B", blocked_by="task-a")

    manager.remove_dependency("task-b", "task-a")

    issue_file = manager.find_issue_file("task-b")
    deps = manager.extract_deps(issue_file)
    assert deps == []
    content = issue_file.read_text(encoding="utf-8")
    # Property removed entirely when last blocker is cleared
    assert "blocked_by:" not in content


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


def test_api_update_issue_preserves_frontmatter(manager):
    """update_issue must round-trip frontmatter fields the caller did not set."""
    manager.create_issue("Task A")
    issue = manager.create_issue(
        "Original Task",
        body="Original body",
        blocked_by="task-a",
    )
    issue_file = manager.find_issue_file(issue.slug)
    assert issue_file is not None
    original = issue_file.read_text(encoding="utf-8")
    assert "created_at:" in original
    assert "blocked_by: task-a" in original

    # Update with content that omits frontmatter and edge fields
    new_content = "# Original Task\n\nNew body text only.\n"
    manager.update_issue(issue.slug, new_content)

    updated = issue_file.read_text(encoding="utf-8")
    # Frontmatter should be preserved
    assert "created_at:" in updated
    # Edge field should be preserved
    assert "blocked_by: task-a" in updated
    # New body should be present
    assert "New body text only." in updated


def test_api_update_issue_preserves_edge_fields(manager):
    """update_issue must preserve blocked_by and subtask_of the caller did not set."""
    manager.create_issue("Parent Task")
    manager.create_issue("Dep Task")
    manager.create_issue("Main Task", blocked_by="dep-task", subtask_of="parent-task")

    issue_file = manager.find_issue_file("main-task")
    assert issue_file is not None
    original = issue_file.read_text(encoding="utf-8")
    assert "blocked_by: dep-task" in original
    assert "subtask_of: parent-task" in original

    # Update body only — no edge fields in new content
    new_content = "---\ncreated_at: 2025-01-01T00:00:00-07:00\n---\n\n# Main Task\n\nUpdated body.\n"
    manager.update_issue("main-task", new_content)

    updated = issue_file.read_text(encoding="utf-8")
    assert "blocked_by: dep-task" in updated
    assert "subtask_of: parent-task" in updated
    assert "Updated body." in updated


def test_api_update_issue_overrides_edge_fields_when_present(manager):
    """update_issue should use new edge fields when explicitly provided."""
    manager.create_issue("Task A")
    manager.create_issue("Task B")
    manager.create_issue("My Task", blocked_by="task-a")

    issue_file = manager.find_issue_file("my-task")
    assert issue_file is not None
    assert "blocked_by: task-a" in issue_file.read_text(encoding="utf-8")

    # New content with different blocked_by (in frontmatter)
    new_content = "---\ncreated_at: 2025-01-01T00:00:00-07:00\nblocked_by: task-b\n---\n\n# My Task\n\nNew body.\n"
    manager.update_issue("my-task", new_content)

    updated = issue_file.read_text(encoding="utf-8")
    assert "blocked_by: task-b" in updated
    assert "task-a" not in updated.replace(
        "task-a-slug", ""
    )  # task-a not in blocked_by
    assert "New body." in updated


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


# ── Station conformance tests ───────────────────────────────────────


def test_walk_completed_flat_and_sharded(manager):
    """walk_completed must handle both flat completed/YYYY/ and sharded completed/YYYY/MM/."""
    completed = manager.issues_root / "completed"
    # Flat: completed/2025/old-task/README.md
    flat_dir = completed / "2025" / "old-task"
    flat_dir.mkdir(parents=True)
    (flat_dir / "README.md").write_text("# Old Task\n", encoding="utf-8")
    # Sharded: completed/2026/03/new-task/README.md
    sharded_dir = completed / "2026" / "03" / "new-task"
    sharded_dir.mkdir(parents=True)
    (sharded_dir / "README.md").write_text("# New Task\n", encoding="utf-8")

    results = manager.walk_completed()
    slugs = {slug for _, slug in results}
    assert "old-task" in slugs
    assert "new-task" in slugs
    # Each entry should be (Path, slug)
    paths = {p for p, _ in results}
    assert (flat_dir / "README.md") in paths
    assert (sharded_dir / "README.md") in paths


def test_walk_completed_file_based(manager):
    """walk_completed should find file-based tasks (slug.md) too."""
    completed = manager.issues_root / "completed"
    flat_file = completed / "2025" / "file-task.md"
    flat_file.parent.mkdir(parents=True)
    flat_file.write_text("# File Task\n", encoding="utf-8")

    results = manager.walk_completed()
    slugs = {slug for _, slug in results}
    assert "file-task" in slugs


def test_ingest_migrates_flat_completed_to_month_sharded(manager):
    """ingest_issues should relocate flat completed/YYYY/ entries to completed/YYYY/MM/."""
    completed = manager.issues_root / "completed"
    # Create a flat entry with created_at in March
    flat_dir = completed / "2025" / "flat-task"
    flat_dir.mkdir(parents=True)
    (flat_dir / "README.md").write_text(
        "---\ncreated_at: 2025-03-15T10:00:00-07:00\n---\n\n# Flat Task\n",
        encoding="utf-8",
    )

    manager.ingest_issues()

    # Should now be at completed/2025/03/flat-task/README.md
    sharded = completed / "2025" / "03" / "flat-task" / "README.md"
    assert sharded.exists()
    # Old flat path should be gone
    assert not (flat_dir / "README.md").exists()


def test_find_issue_file_recurses_month_sharded_completed(manager):
    """find_issue_file must find tasks in completed/YYYY/MM/ subdirectories."""
    completed = manager.issues_root / "completed"
    sharded_dir = completed / "2026" / "03" / "deep-task"
    sharded_dir.mkdir(parents=True)
    (sharded_dir / "README.md").write_text("# Deep Task\n", encoding="utf-8")

    found = manager.find_issue_file("deep-task", include_completed=True)
    assert found is not None
    assert found.exists()
    assert "deep-task" in str(found)


def test_extract_relations_frontmatter_preferred_over_prose(manager):
    """extract_relations should prefer frontmatter edge fields over prose."""
    issues_root = manager.issues_root
    task_dir = issues_root / "pending" / "dual-task"
    task_dir.mkdir(parents=True)
    # Both frontmatter AND prose — frontmatter should win
    (task_dir / "README.md").write_text(
        "---\ncreated_at: 2025-01-01T00:00:00-07:00\n"
        "blocked_by: front-dep\nsubtask_of: front-parent\n---\n\n"
        "# Dual Task\n\n**Blocked by:** prose-dep\n**Subtask of:** prose-parent\n",
        encoding="utf-8",
    )

    blocked_by, subtask_of = TaskAgent.extract_relations(task_dir / "README.md")
    assert blocked_by == ["front-dep"]
    assert subtask_of == "front-parent"


def test_extract_relations_prose_fallback(manager):
    """extract_relations should fall back to prose when frontmatter has no edge fields."""
    issues_root = manager.issues_root
    task_dir = issues_root / "pending" / "legacy-task"
    task_dir.mkdir(parents=True)
    # Only prose, no edge fields in frontmatter
    (task_dir / "README.md").write_text(
        "---\ncreated_at: 2025-01-01T00:00:00-07:00\n---\n\n"
        "# Legacy Task\n\n**Blocked by:** legacy-dep\n**Subtask of:** legacy-parent\n",
        encoding="utf-8",
    )

    blocked_by, subtask_of = TaskAgent.extract_relations(task_dir / "README.md")
    assert blocked_by == ["legacy-dep"]
    assert subtask_of == "legacy-parent"


def test_create_issue_writes_edges_to_frontmatter_not_prose(manager):
    """create_issue must write edge fields to frontmatter, never to prose."""
    manager.create_issue("Task A")
    manager.create_issue("Parent Task")
    issue = manager.create_issue(
        "Edge Task",
        blocked_by="task-a",
        subtask_of="parent-task",
    )

    issue_file = manager.find_issue_file(issue.slug)
    assert issue_file is not None
    content = issue_file.read_text(encoding="utf-8")

    # Frontmatter should have edge fields
    assert "blocked_by: task-a" in content
    assert "subtask_of: parent-task" in content
    # Prose lines should NOT exist
    assert "**Blocked by:**" not in content
    assert "**Subtask of:**" not in content


def test_add_dependency_no_prose_written(manager):
    """add_dependency must write to frontmatter, leaving no prose lines."""
    manager.create_issue("Task A")
    manager.create_issue("Task B")

    manager.add_dependency("task-b", "task-a")

    issue_file = manager.find_issue_file("task-b")
    content = issue_file.read_text(encoding="utf-8")
    assert "blocked_by: task-a" in content
    assert "**Blocked by:**" not in content


def test_update_dependencies_no_prose_written(manager):
    """update_dependencies must write to frontmatter, leaving no prose lines."""
    manager.create_issue("Task A")
    manager.create_issue("Task B")
    manager.create_issue("Task C")

    manager.update_dependencies("task-b", "task-a, task-c")

    issue_file = manager.find_issue_file("task-b")
    content = issue_file.read_text(encoding="utf-8")
    assert "blocked_by: task-a, task-c" in content
    assert "**Blocked by:**" not in content


def test_update_subtask_of_no_prose_written(manager):
    """update_subtask_of must write to frontmatter, leaving no prose lines."""
    manager.create_issue("Parent Task")
    manager.create_issue("Child Task")

    manager.update_subtask_of("child-task", "parent-task")

    issue_file = manager.find_issue_file("child-task")
    content = issue_file.read_text(encoding="utf-8")
    assert "subtask_of: parent-task" in content
    assert "**Subtask of:**" not in content


def test_bulk_update_dependencies(manager):
    manager.create_issue("Blocker")
    manager.create_issue("Task A")
    manager.create_issue("Task B")
    manager.create_issue("Task C")

    results = manager.bulk_update_dependencies(
        ["task-a", "task-b", "missing-task"], "blocker"
    )
    by_slug = {r["slug"]: r for r in results}
    assert by_slug["task-a"]["ok"] is True
    assert by_slug["task-b"]["ok"] is True
    assert by_slug["missing-task"]["ok"] is False

    assert manager.extract_deps(manager.find_issue_file("task-a")) == ["blocker"]
    assert manager.extract_deps(manager.find_issue_file("task-b")) == ["blocker"]
    # Unrelated task untouched
    assert manager.extract_deps(manager.find_issue_file("task-c")) == []

    # Clear blockers on both
    clear_results = manager.bulk_update_dependencies(["task-a", "task-b"], "")
    assert all(r["ok"] for r in clear_results)
    assert manager.extract_deps(manager.find_issue_file("task-a")) == []
    assert manager.extract_deps(manager.find_issue_file("task-b")) == []


def test_bulk_update_subtask_of(manager):
    manager.create_issue("Epic")
    manager.create_issue("Child A")
    manager.create_issue("Child B")

    results = manager.bulk_update_subtask_of(["child-a", "child-b"], "epic")
    assert all(r["ok"] for r in results)

    issues = {i.slug: i for i in manager.load_mission()}
    assert issues["child-a"].subtask_of == "epic"
    assert issues["child-b"].subtask_of == "epic"

    clear = manager.bulk_update_subtask_of(["child-a", "child-b"], None)
    assert all(r["ok"] for r in clear)
    issues = {i.slug: i for i in manager.load_mission()}
    assert issues["child-a"].subtask_of is None
    assert issues["child-b"].subtask_of is None
    # Empty parent clears the frontmatter key
    content = manager.find_issue_file("child-a").read_text(encoding="utf-8")
    assert "subtask_of:" not in content


def test_clear_blocked_by_removes_frontmatter_key(manager):
    manager.create_issue("Dep")
    manager.create_issue("Main", blocked_by="dep")
    path = manager.find_issue_file("main")
    assert "blocked_by: dep" in path.read_text(encoding="utf-8")

    manager.update_dependencies("main", "")
    content = path.read_text(encoding="utf-8")
    assert "blocked_by:" not in content


def test_add_then_remove_last_blocked_by_removes_property(manager):
    manager.create_issue("A")
    manager.create_issue("B")
    manager.create_issue("C")
    manager.add_dependency("c", "a")
    manager.add_dependency("c", "b")
    content = manager.find_issue_file("c").read_text(encoding="utf-8")
    assert "blocked_by: a, b" in content or "blocked_by: a" in content

    manager.remove_dependency("c", "a, b")
    content = manager.find_issue_file("c").read_text(encoding="utf-8")
    assert "blocked_by:" not in content
    assert manager.extract_relations(manager.find_issue_file("c"))[0] == []


def test_resolve_and_find_by_renamed_title(manager):
    """Lookups by current display title work when slug still matches creation title."""
    issue = manager.create_issue("Original Title")
    assert issue.slug == "original-title"

    path = manager.find_issue_file("original-title")
    assert path is not None
    # Retitle H1 without renaming directory/slug
    text = path.read_text(encoding="utf-8")
    text = text.replace("# Original Title", "# Completely New Name")
    path.write_text(text, encoding="utf-8")

    # Sync mission name from file (ingest-style update of in-memory name)
    issues = manager.load_mission()
    for i in issues:
        if i.slug == "original-title":
            i.name = "Completely New Name"
    manager.save_mission(issues)

    assert manager.resolve_issue_slug("Completely New Name") == "original-title"
    assert manager.resolve_issue_slug("completely-new-name") == "original-title"
    found = manager.find_issue_file("Completely New Name")
    assert found is not None
    assert found.parent.name == "original-title"


def test_ingest_migrates_prose_edges_to_frontmatter(manager):
    """ingest_issues should migrate prose edge lines to frontmatter."""
    issues_root = manager.issues_root
    task_dir = issues_root / "pending" / "prose-task"
    task_dir.mkdir(parents=True)
    (task_dir / "README.md").write_text(
        "---\ncreated_at: 2025-01-01T00:00:00-07:00\n---\n\n"
        "# Prose Task\n\n**Blocked by:** other-task\n**Subtask of:** parent-task\n",
        encoding="utf-8",
    )

    manager.save_mission([])
    manager.ingest_issues()

    content = (task_dir / "README.md").read_text(encoding="utf-8")
    assert "blocked_by: other-task" in content
    assert "subtask_of: parent-task" in content
    assert "**Blocked by:**" not in content
    assert "**Subtask of:**" not in content


def test_index_rebuildable_from_station_tree(manager):
    """Wiping mission.usv and re-ingesting should rebuild the index from station dirs."""
    manager.create_issue("Task A", draft=False)
    manager.create_issue("Task B", draft=True)
    manager.create_issue("Task C", blocked_by="task-a")

    # Verify initial state
    issues = manager.load_mission()
    assert len(issues) == 3

    # Wipe the index
    manager.save_mission([])
    assert len(manager.load_mission()) == 0

    # Re-ingest from station tree
    manager.ingest_issues()

    issues = manager.load_mission()
    slugs = {i.slug for i in issues}
    assert "task-a" in slugs
    assert "task-b" in slugs
    assert "task-c" in slugs

    # Edge fields should be reconstructed
    task_c = next(i for i in issues if i.slug == "task-c")
    assert task_c.blocked_by == ["task-a"]


# ── Dependency model regression tests ───────────────────────────────


def test_ingest_removes_redundant_blocked_by_on_epic(manager):
    """If a child slug is in the epic's blocked_by, ingest should remove it."""
    # Create epic and child
    manager.create_issue("Epic Task")
    manager.create_issue("Child Task", subtask_of="epic-task")

    # Directly manipulate the USV to create the redundant state
    # (update_dependencies would correctly refuse this as a cycle)
    issues = manager.load_mission()
    epic = next(i for i in issues if i.slug == "epic-task")
    epic.blocked_by = ["child-task"]
    manager.save_mission(issues)
    # Also write to frontmatter so ingest can read it
    epic_file = manager.find_issue_file("epic-task")
    content = epic_file.read_text(encoding="utf-8")
    content = TaskAgent._write_frontmatter_edges(content, blocked_by=["child-task"])
    manager._set_writable(epic_file, True)
    epic_file.write_text(content, encoding="utf-8")

    # Verify the redundant state exists
    issues = manager.load_mission()
    epic = next(i for i in issues if i.slug == "epic-task")
    assert "child-task" in epic.blocked_by

    # Ingest should clean it
    manager.ingest_issues()

    issues = manager.load_mission()
    epic = next(i for i in issues if i.slug == "epic-task")
    assert "child-task" not in epic.blocked_by
    # subtask_of should be untouched
    child = next(i for i in issues if i.slug == "child-task")
    assert child.subtask_of == "epic-task"


def test_ingest_preserves_external_blocked_by(manager):
    """External (non-child) blocked_by entries should survive the cleanup."""
    manager.create_issue("Task A")
    manager.create_issue("Epic Task")
    manager.create_issue("Child Task", subtask_of="epic-task")

    # Directly manipulate USV + frontmatter to add both child AND external
    # (update_dependencies would refuse child-task as a cycle)
    issues = manager.load_mission()
    epic = next(i for i in issues if i.slug == "epic-task")
    epic.blocked_by = ["child-task", "task-a"]
    manager.save_mission(issues)
    epic_file = manager.find_issue_file("epic-task")
    content = epic_file.read_text(encoding="utf-8")
    content = TaskAgent._write_frontmatter_edges(
        content, blocked_by=["child-task", "task-a"]
    )
    manager._set_writable(epic_file, True)
    epic_file.write_text(content, encoding="utf-8")

    manager.ingest_issues()

    issues = manager.load_mission()
    epic = next(i for i in issues if i.slug == "epic-task")
    # Child should be removed (redundant)
    assert "child-task" not in epic.blocked_by
    # External should be preserved
    assert "task-a" in epic.blocked_by


def test_promote_cascades_subtask_of_only(manager):
    """Promote should cascade to subtask_of children, not blocked_by dependents."""
    manager.create_issue("Epic", draft=True)
    manager.create_issue("Child", draft=True, subtask_of="epic")
    manager.create_issue("External Dep", draft=True, blocked_by="epic")

    manager.promote_issue("epic")

    # Epic promoted
    assert (manager.issues_root / "pending" / "epic" / "README.md").exists()
    # Child cascaded (subtask_of)
    assert (manager.issues_root / "pending" / "child" / "README.md").exists()
    # External dep NOT cascaded (blocked_by is not hierarchy)
    assert not (manager.issues_root / "pending" / "external-dep" / "README.md").exists()
    assert (manager.issues_root / "draft" / "external-dep" / "README.md").exists()


def test_demote_cascades_subtask_of_only(manager):
    """Demote should cascade to subtask_of children, not blocked_by dependents."""
    manager.create_issue("Epic", draft=False)
    manager.create_issue("Child", draft=False, subtask_of="epic")
    manager.create_issue("External Dep", draft=False, blocked_by="epic")

    manager.demote_issue("epic")

    # Epic demoted
    assert (manager.issues_root / "draft" / "epic" / "README.md").exists()
    # Child cascaded (subtask_of)
    assert (manager.issues_root / "draft" / "child" / "README.md").exists()
    # External dep NOT cascaded
    assert not (manager.issues_root / "draft" / "external-dep" / "README.md").exists()
    assert (manager.issues_root / "pending" / "external-dep" / "README.md").exists()
