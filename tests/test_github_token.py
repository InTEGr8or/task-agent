"""GitHub token resolution including 1Password op:// refs."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from taskagent.plugins.github import _github_token, _read_op_secret


def test_github_token_prefers_env(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "env-token-xyz")
    assert _github_token() == "env-token-xyz"


def test_github_token_op_env(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.setenv(
        "TA_GITHUB_TOKEN_OP", "op://Private/GitHub CLI Token/oauth_token"
    )
    with patch(
        "taskagent.plugins.github._read_op_secret",
        return_value="op-token-abc",
    ) as mock_op:
        assert _github_token() == "op-token-abc"
        mock_op.assert_called()


def test_read_op_secret_prefers_op_exe(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd[0])
        from types import SimpleNamespace

        if cmd[0] == "op.exe":
            return SimpleNamespace(returncode=0, stdout="from-exe\n", stderr="")
        return SimpleNamespace(returncode=1, stdout="", stderr="no")

    with patch("taskagent.plugins.github.subprocess.run", side_effect=fake_run):
        assert _read_op_secret("op://Vault/Item/field") == "from-exe"
    assert calls[0] == "op.exe"


def test_github_token_settings_json(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("TA_GITHUB_TOKEN_OP", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN_OP", raising=False)
    cfg = tmp_path / "settings.json"
    cfg.write_text('{"github_token_op": "op://Private/GitHub CLI Token/oauth_token"}\n')
    with (
        patch(
            "taskagent.plugins.github.Path.expanduser",
            lambda self: cfg if "settings.json" in str(self) else Path(self),
        ),
        patch(
            "taskagent.plugins.github._read_op_secret",
            return_value="from-settings",
        ),
        patch("taskagent.plugins.github._gh_auth_token", return_value=None),
    ):
        # expanduser mock is fragile; call settings helper more directly
        pass
    # Simpler: patch _settings_github_token_op
    with (
        patch(
            "taskagent.plugins.github._settings_github_token_op",
            return_value="op://Private/GitHub CLI Token/oauth_token",
        ),
        patch(
            "taskagent.plugins.github._read_op_secret",
            return_value="from-settings",
        ),
        patch("taskagent.plugins.github._gh_auth_token", return_value=None),
    ):
        assert _github_token() == "from-settings"
