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
    # Name, Slug, Deps
    mission_file.write_text("Old Task\x1fold-task\x1f\n")

    return project_root


def test_migration_issues_to_tasks(legacy_setup):
    # Discovery will find docs/issues
    os.chdir(legacy_setup)
    from taskagent.discovery import discover

    manager = discover()

    assert manager.issues_root.name == "issues"

    # Run init
    num_new, num_removed = manager.init_project()

    # Verify migration
    assert not (legacy_setup / "docs" / "issues").exists()
    assert (legacy_setup / "docs" / "tasks").exists()
    # mission.usv is now in .task-agent/ subdirectory
    assert (legacy_setup / "docs" / "tasks" / ".task-agent" / "mission.usv").exists()
    assert (
        legacy_setup / "docs" / "tasks" / "pending" / "old-task" / "README.md"
    ).exists()

    # Verify content preservation
    issues = manager.load_mission()
    assert len(issues) == 1
    assert issues[0].slug == "old-task"
    assert issues[0].status == "pending"


def test_migration_preserves_usv_content(legacy_setup):
    # Discovery will find docs/issues
    os.chdir(legacy_setup)
    from taskagent.discovery import discover

    manager = discover()

    # Pre-check
    assert len(manager.load_mission()) == 1

    # Run init
    manager.init_project()

    # Check if content is still there (mission files now in .task-agent/)
    issues = manager.load_mission()
    assert len(issues) == 1
    assert issues[0].slug == "old-task"
    assert (
        legacy_setup / "docs" / "tasks" / "pending" / "old-task" / "README.md"
    ).exists()
    # Verify mission.usv is in .task-agent/
    assert (legacy_setup / "docs" / "tasks" / ".task-agent" / "mission.usv").exists()


def test_migration_with_symlink(legacy_setup, tmp_path):
    # Move issues to a "remote" location and symlink it
    # We rename it to project-issues to test the target-rename logic
    remote_dir = tmp_path / "project-issues"
    shutil.move(str(legacy_setup / "docs" / "issues"), str(remote_dir))
    os.symlink(str(remote_dir), str(legacy_setup / "docs" / "issues"))

    os.chdir(legacy_setup)
    from taskagent.discovery import discover

    manager = discover()

    # Run init
    manager.init_project()

    # Verify symlink migration - issues should be moved to tasks
    # The symlink at docs/issues should be replaced
    assert not (legacy_setup / "docs" / "issues").is_symlink()
    tasks_link = legacy_setup / "docs" / "tasks"
    assert tasks_link.exists()

    # Verify mission files are in .task-agent/
    assert (tasks_link / ".task-agent" / "mission.usv").exists()
    assert (tasks_link / "pending" / "old-task" / "README.md").exists()
