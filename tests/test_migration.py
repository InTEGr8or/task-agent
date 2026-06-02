import pytest
import os
import shutil


@pytest.fixture
def legacy_setup(tmp_path):
    """Create a legacy docs/issues structure."""
    project_root = tmp_path / "project"
    project_root.mkdir()
    issues_dir = project_root / "docs" / "issues"
    issues_dir.mkdir(parents=True)

    for subdir in ["pending", "draft", "active", "completed"]:
        (issues_dir / subdir).mkdir()

    # Add a task
    task_file = issues_dir / "pending" / "old-task.md"
    task_file.write_text("# Old Task")

    # Create mission.usv
    mission_file = issues_dir / "mission.usv"
    mission_file.write_text("Old Task\x1fold-task\x1f\n")

    return project_root


@pytest.fixture
def chdir_legacy(legacy_setup):
    """Change to legacy setup dir and restore afterward."""
    orig = os.getcwd()
    os.chdir(legacy_setup)
    yield legacy_setup
    os.chdir(orig)


def test_migration_issues_to_tasks(chdir_legacy):
    from taskagent.discovery import discover

    manager = discover()

    legacy_setup = chdir_legacy
    assert manager.issues_root.name == "issues"

    # Run init
    num_new, num_removed = manager.init_project()

    # Verify migration
    assert not (legacy_setup / "docs" / "issues").exists()
    assert (legacy_setup / "docs" / "tasks").exists()
    assert (legacy_setup / "docs" / "tasks" / ".task-agent" / "mission.usv").exists()
    assert (
        legacy_setup / "docs" / "tasks" / "pending" / "old-task" / "README.md"
    ).exists()

    # Verify content preservation
    issues = manager.load_mission()
    assert len(issues) == 1
    assert issues[0].slug == "old-task"
    assert issues[0].status == "pending"


def test_migration_preserves_usv_content(chdir_legacy):
    from taskagent.discovery import discover

    manager = discover()

    legacy_setup = chdir_legacy

    # Pre-check
    assert len(manager.load_mission()) == 1

    # Run init
    manager.init_project()

    # Check if content is still there
    issues = manager.load_mission()
    assert len(issues) == 1
    assert issues[0].slug == "old-task"
    assert (
        legacy_setup / "docs" / "tasks" / "pending" / "old-task" / "README.md"
    ).exists()
    assert (legacy_setup / "docs" / "tasks" / ".task-agent" / "mission.usv").exists()


def test_migration_with_symlink(legacy_setup, tmp_path):
    # Change dir to legacy setup
    orig = os.getcwd()
    os.chdir(legacy_setup)
    try:
        remote_dir = tmp_path / "project-issues"
        shutil.move(str(legacy_setup / "docs" / "issues"), str(remote_dir))
        os.symlink(str(remote_dir), str(legacy_setup / "docs" / "issues"))

        from taskagent.discovery import discover

        manager = discover()

        # Run init
        manager.init_project()

        # Verify symlink migration
        assert not (legacy_setup / "docs" / "issues").is_symlink()
        tasks_link = legacy_setup / "docs" / "tasks"
        assert tasks_link.exists()
        assert (tasks_link / ".task-agent" / "mission.usv").exists()
        assert (tasks_link / "pending" / "old-task" / "README.md").exists()
    finally:
        os.chdir(orig)
