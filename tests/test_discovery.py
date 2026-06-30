import json
import subprocess
from pathlib import Path
from taskagent.discovery import discover
import os


def _init_git_repo(path: Path):
    """Initialize a git repo at the given path."""
    subprocess.run(["git", "init"], cwd=path, capture_output=True)


def test_discover_env_var(tmp_path, monkeypatch):
    issues_dir = tmp_path / "custom_issues"
    issues_dir.mkdir()
    monkeypatch.setenv("TA_CONFIG_DIR", str(issues_dir))

    manager = discover()
    assert manager.issues_root == issues_dir
    assert (issues_dir / "pending").exists()


def test_discover_walk_up_folder(tmp_path):
    # Setup structure: root/docs/tasks, root/src/subdir
    root = tmp_path / "project"
    tasks_dir = root / "docs" / "tasks"
    tasks_dir.mkdir(parents=True)

    subdir = root / "src" / "deep" / "dir"
    subdir.mkdir(parents=True)

    # Run discovery from deep subdir
    manager = discover(start_path=subdir)
    assert manager.issues_root.resolve() == tasks_dir.resolve()


def test_discover_config_file(tmp_path):
    # Setup root with .ta-config.json pointing to custom location
    root = tmp_path / "project"
    root.mkdir()
    custom_dir = root / "my_tasks"

    config = {"issues_dir": "my_tasks"}
    (root / ".ta-config.json").write_text(json.dumps(config))

    manager = discover(start_path=root)
    assert manager.issues_root.resolve() == custom_dir.resolve()
    assert (custom_dir / "pending").exists()


def test_discover_fallback(tmp_path):
    # No tasks/issues dir, no config, no env var
    manager = discover(start_path=tmp_path)
    assert manager.issues_root.resolve() == (tmp_path / "docs" / "tasks").resolve()


def test_discover_nested_git_repo_favors_child(tmp_path):
    """
    When running from a nested git repo inside another git repo,
    discovery should find the child's docs/tasks, not the parent's.
    """
    parent = tmp_path / "parent"
    parent.mkdir()
    _init_git_repo(parent)
    parent_tasks = parent / "docs" / "tasks"
    parent_tasks.mkdir(parents=True)

    child = parent / "child"
    child.mkdir()
    _init_git_repo(child)
    child_tasks = child / "docs" / "tasks"
    child_tasks.mkdir(parents=True)

    # Run from child repo
    manager = discover(start_path=child)
    assert manager.issues_root.resolve() == child_tasks.resolve()


def test_discover_nested_git_repo_creates_in_child(tmp_path):
    """
    When running from a nested git repo with no docs/tasks yet,
    discovery should default to child, not parent.
    """
    parent = tmp_path / "parent"
    parent.mkdir()
    _init_git_repo(parent)
    parent_tasks = parent / "docs" / "tasks"
    parent_tasks.mkdir(parents=True)

    child = parent / "child"
    child.mkdir()
    _init_git_repo(child)
    # Child has no docs/tasks yet

    manager = discover(start_path=child)
    expected = child / "docs" / "tasks"
    assert manager.issues_root.resolve() == expected.resolve()


def test_discover_non_git_subdir_in_git_repo(tmp_path):
    """
    When running from a non-git subdirectory inside a git repo,
    discovery should find the parent repo's docs/tasks.
    """
    root = tmp_path / "project"
    root.mkdir()
    _init_git_repo(root)
    tasks_dir = root / "docs" / "tasks"
    tasks_dir.mkdir(parents=True)

    subdir = root / "src" / "subdir"
    subdir.mkdir(parents=True)
    # subdir is NOT a git repo

    manager = discover(start_path=subdir)
    assert manager.issues_root.resolve() == tasks_dir.resolve()


def test_discover_non_git_subdir_in_nested_git_repo(tmp_path):
    """
    When running from a non-git subdir inside a nested git repo,
    discovery should find the nested repo's docs/tasks.
    """
    parent = tmp_path / "parent"
    parent.mkdir()
    _init_git_repo(parent)

    child = parent / "child"
    child.mkdir()
    _init_git_repo(child)
    child_tasks = child / "docs" / "tasks"
    child_tasks.mkdir(parents=True)

    subdir = child / "src" / "subdir"
    subdir.mkdir(parents=True)
    # subdir is NOT a git repo, but it's inside the child git repo

    manager = discover(start_path=subdir)
    assert manager.issues_root.resolve() == child_tasks.resolve()


def test_discover_fails_when_docs_tasks_is_file(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    _init_git_repo(root)
    # Create docs/tasks as a file, not a directory
    docs_dir = root / "docs"
    docs_dir.mkdir()
    tasks_file = docs_dir / "tasks"
    tasks_file.write_text("not a directory")

    import pytest

    with pytest.raises(RuntimeError) as exc_info:
        discover(start_path=root)
    assert "exists but is not a directory" in str(exc_info.value)


def test_discover_fails_when_parent_exists_but_is_file(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    _init_git_repo(root)
    # Create docs as a file, not a directory
    docs_file = root / "docs"
    docs_file.write_text("not a directory")

    import pytest

    with pytest.raises(RuntimeError) as exc_info:
        discover(start_path=root)
    assert "exists but is not a directory" in str(exc_info.value)


def test_discover_relative_ejected_path_resolved_relative_to_repo_root(
    tmp_path, monkeypatch
):
    # Clear environment variables first to avoid inheriting from parent process
    monkeypatch.delenv("TA_EJECT_TASKS", raising=False)
    monkeypatch.delenv("TA_EJECTED_TASKS_PATH", raising=False)
    monkeypatch.delenv("TA_EJECTED_ISSUES_PATH", raising=False)

    root = tmp_path / "project"
    root.mkdir()
    _init_git_repo(root)

    # Write a .env file with a relative ejected path
    env_content = "TA_EJECT_TASKS=true\nTA_EJECTED_TASKS_PATH=custom_eject_dir\n"
    (root / ".env").write_text(env_content)

    # CWD is inside a subdirectory
    subdir = root / "src" / "deep"
    subdir.mkdir(parents=True)

    # Use monkeypatch to run with cwd = subdir
    monkeypatch.chdir(subdir)

    # Run discover
    print("BEFORE DISCOVER: CWD =", Path.cwd())
    print("BEFORE DISCOVER: root .env exists =", (root / ".env").exists())
    print("BEFORE DISCOVER: root .git exists =", (root / ".git").exists())

    manager = discover(start_path=subdir)

    print("AFTER DISCOVER: TA_EJECT_TASKS =", os.environ.get("TA_EJECT_TASKS"))
    print(
        "AFTER DISCOVER: TA_EJECTED_TASKS_PATH =",
        os.environ.get("TA_EJECTED_TASKS_PATH"),
    )
    print("AFTER DISCOVER: manager.issues_root =", manager.issues_root)

    # The ejection path should be resolved relative to root (where .env and .git exist),
    # not relative to CWD (subdir)
    expected_eject_path = root / "custom_eject_dir"
    assert expected_eject_path.is_dir()

    tasks_link = root / "docs" / "tasks"
    assert tasks_link.is_symlink()
    assert tasks_link.resolve() == expected_eject_path.resolve()
