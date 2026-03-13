import json
from taskagent.discovery import discover


def test_discover_env_var(tmp_path, monkeypatch):
    issues_dir = tmp_path / "custom_issues"
    issues_dir.mkdir()
    monkeypatch.setenv("TA_CONFIG_DIR", str(issues_dir))

    manager = discover()
    assert manager.issues_root == issues_dir
    assert (issues_dir / "pending").exists()


def test_discover_walk_up_folder(tmp_path):
    # Setup structure: root/docs/issues, root/src/subdir
    root = tmp_path / "project"
    issues_dir = root / "docs" / "issues"
    issues_dir.mkdir(parents=True)

    subdir = root / "src" / "deep" / "dir"
    subdir.mkdir(parents=True)

    # Run discovery from deep subdir
    manager = discover(start_path=subdir)
    assert manager.issues_root.resolve() == issues_dir.resolve()


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
    # No issues dir, no config, no env var
    manager = discover(start_path=tmp_path)
    assert manager.issues_root.resolve() == (tmp_path / "docs" / "issues").resolve()
