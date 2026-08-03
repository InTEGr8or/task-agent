import pytest
from taskagent.manager import TaskAgent
from taskagent.models.issue import Issue


@pytest.fixture
def manager(tmp_path):
    issues_root = tmp_path / "docs" / "tasks"
    m = TaskAgent(config_dir=str(issues_root))
    (issues_root / ".task-agent").mkdir(exist_ok=True)
    return m


def test_complete_issue_atomic_on_commit_failure(manager, monkeypatch):
    """Assert that if commit fails in complete_issue, the task remains pending and no placeholder is left on disk."""
    issue = manager.create_issue("Complete Failure Test", body="Original body")
    slug = issue.slug

    pending_file = manager.issues_root / "pending" / slug / "README.md"
    assert pending_file.exists()

    monkeypatch.setattr(manager, "_commit_task_store", lambda *a, **k: "failed")

    with pytest.raises(RuntimeError, match="Failed to commit"):
        manager.complete_issue(slug, solution_explanation="Should roll back")

    assert pending_file.exists()
    content = pending_file.read_text(encoding="utf-8")
    assert "Original body" in content
    assert "<pending-commit-id>" not in content
    assert "## Solution" not in content

    completed_files = list((manager.issues_root / "completed").glob(f"**/{slug}"))
    assert len(completed_files) == 0

    issues = manager.load_mission()
    target = next((i for i in issues if i.slug == slug), None)
    assert target is not None
    assert target.status == "pending"


def test_promote_issue_atomic_on_commit_failure(manager, monkeypatch):
    """Assert that if commit fails during promote_issue, the task remains in draft/."""
    issues = manager.load_mission()
    issue = Issue(name="Draft Task", slug="draft-task", status="draft", priority=1)
    manager.save_mission(issues + [issue])

    draft_dir = manager.issues_root / "draft" / "draft-task"
    draft_dir.mkdir(parents=True, exist_ok=True)
    draft_readme = draft_dir / "README.md"
    draft_readme.write_text("# Draft Task\n\nDraft content\n")

    monkeypatch.setattr(manager, "_commit_task_store", lambda *a, **k: "failed")

    with pytest.raises(RuntimeError, match="Failed to commit"):
        manager.promote_issue("draft-task")

    assert draft_readme.exists()
    assert not (manager.issues_root / "pending" / "draft-task").exists()


def test_demote_issue_atomic_on_commit_failure(manager, monkeypatch):
    """Assert that if commit fails during demote_issue, the task remains in pending/."""
    issue = manager.create_issue("Demote Failure Test")
    slug = issue.slug

    pending_dir = manager.issues_root / "pending" / slug
    assert pending_dir.exists()

    monkeypatch.setattr(manager, "_commit_task_store", lambda *a, **k: "failed")

    with pytest.raises(RuntimeError, match="Failed to commit"):
        manager.demote_issue(slug)

    assert pending_dir.exists()
    assert not (manager.issues_root / "draft" / slug).exists()


def test_move_to_active_atomic_on_commit_failure(manager, monkeypatch):
    """Assert that if commit fails during move_to_active, the task remains in pending/."""
    issue = manager.create_issue("Active Failure Test")
    slug = issue.slug

    pending_dir = manager.issues_root / "pending" / slug
    assert pending_dir.exists()

    monkeypatch.setattr(manager, "_commit_task_store", lambda *a, **k: "failed")

    with pytest.raises(RuntimeError, match="Failed to commit"):
        manager.move_to_active(slug)

    assert pending_dir.exists()
    assert not (manager.issues_root / "active" / slug).exists()


def test_restore_issue_atomic_on_commit_failure(manager, monkeypatch):
    """Assert that if commit fails during restore_issue, the task remains in completed/."""
    issue = manager.create_issue("Restore Failure Test")
    slug = issue.slug

    monkeypatch.setattr(manager, "_commit_task_store", lambda *a, **k: "abc1234")
    manager.complete_issue(slug, should_commit=False)

    completed_files = list((manager.issues_root / "completed").glob(f"**/{slug}"))
    assert len(completed_files) == 1

    monkeypatch.setattr(manager, "_commit_task_store", lambda *a, **k: "failed")

    with pytest.raises(RuntimeError, match="Failed to commit"):
        manager.restore_issue(slug, to_status="pending")

    completed_files_after = list((manager.issues_root / "completed").glob(f"**/{slug}"))
    assert len(completed_files_after) == 1
    assert not (manager.issues_root / "pending" / slug).exists()


def test_rename_issue_atomic_on_commit_failure(manager, monkeypatch):
    """Assert that if commit fails during rename_issue, the slug and folder are not changed."""
    issue = manager.create_issue("Original Title")
    old_slug = issue.slug

    old_dir = manager.issues_root / "pending" / old_slug
    assert old_dir.exists()

    monkeypatch.setattr(manager, "_commit_task_store", lambda *a, **k: "failed")

    with pytest.raises(RuntimeError, match="Failed to commit"):
        manager.rename_issue(old_slug, "New Title")

    assert old_dir.exists()
    assert not (manager.issues_root / "pending" / "new-title").exists()
