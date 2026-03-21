import json
import subprocess
from pathlib import Path
from taskagent.discovery import discover


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
