"""ta store remote create — forge plugin API, not gh CLI."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from taskagent.plugins.github import GitHubTasksRemoteProvider
from taskagent.store_registry import (
    create_and_attach_store_remote,
    select_remote_provider,
    write_store_meta,
)


def _seed_store(path: Path) -> Path:
    path.mkdir(parents=True)
    for d in ("pending", "active", "draft", "completed"):
        (path / d).mkdir()
    (path / ".task-agent").mkdir()
    (path / ".task-agent" / "mission.usv").write_text(
        "Name\x1fSlug\x1fDependencies\n", encoding="utf-8"
    )
    write_store_meta(path, moniker="acme/app")
    return path


def test_select_provider_github():
    p = select_remote_provider("git@github.com:acme/app.git")
    assert p.name == "github"
    with pytest.raises(ValueError, match="No remote provider"):
        select_remote_provider("git@gitlab.com:acme/app.git")


def test_create_and_attach_dry_run(tmp_path, monkeypatch):
    data = tmp_path / "data"
    monkeypatch.setenv("TA_DATA_ROOT", str(data))
    host = tmp_path / "host"
    host.mkdir()
    # fake git subject
    import subprocess

    subprocess.run(["git", "init"], cwd=host, check=True, capture_output=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "git@github.com:acme/app.git"],
        cwd=host,
        check=True,
        capture_output=True,
    )
    store = _seed_store(data / "stores" / "acme_app")
    from taskagent.store_registry import MachineRegistry, StoreEntry

    MachineRegistry(data).upsert(
        StoreEntry(
            moniker="acme/app",
            store_path=str(store),
            host_paths=[str(host)],
        )
    )

    # Force private detection without network
    with patch.object(
        GitHubTasksRemoteProvider, "subject_is_private", return_value=True
    ):
        info = create_and_attach_store_remote(host, dry_run=True, data_root=data)
    assert info["dry_run"] is True
    assert info["private"] is True
    assert info["visibility_source"] == "subject"
    assert info["provider"] == "github"
    assert "acme/app-tasks" in (info.get("planned_url") or "")


def test_create_tasks_remote_mocked_api():
    provider = GitHubTasksRemoteProvider()
    mock_gh = MagicMock()
    # get fails → create
    mock_gh.rest.repos.get.side_effect = Exception("404")
    mock_gh.rest.users.get_authenticated.return_value = MagicMock(
        parsed_data=MagicMock(login="acme")
    )
    mock_gh.rest.repos.create_for_authenticated_user.return_value = MagicMock()

    with (
        patch("taskagent.plugins.github._github_token", return_value="tok"),
        patch("taskagent.plugins.github.GitHub", return_value=mock_gh),
    ):
        created = provider.create_tasks_remote(
            "git@github.com:acme/app.git",
            "acme/app",
            private=True,
        )
    assert created.created is True
    assert created.full_name == "acme/app-tasks"
    assert created.private is True
    assert created.url == "git@github.com:acme/app-tasks.git"
    mock_gh.rest.repos.create_for_authenticated_user.assert_called_once()
    kwargs = mock_gh.rest.repos.create_for_authenticated_user.call_args.kwargs
    assert kwargs["private"] is True
    assert kwargs.get("auto_init") is False


def test_create_tasks_remote_already_exists():
    provider = GitHubTasksRemoteProvider()
    mock_gh = MagicMock()
    mock_gh.rest.repos.get.return_value = MagicMock(
        parsed_data=MagicMock(private=False)
    )
    with (
        patch("taskagent.plugins.github._github_token", return_value="tok"),
        patch("taskagent.plugins.github.GitHub", return_value=mock_gh),
    ):
        created = provider.create_tasks_remote(
            "git@github.com:acme/app.git",
            "acme/app",
            private=True,
        )
    assert created.created is False
    assert created.private is False  # from existing
    mock_gh.rest.repos.create_for_authenticated_user.assert_not_called()


def test_validate_rejects_wiki():
    p = GitHubTasksRemoteProvider()
    assert p.validate_remote("git@github.com:a/b.wiki.git") is not None
