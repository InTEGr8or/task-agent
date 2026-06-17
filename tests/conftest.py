import os
import pytest


@pytest.fixture(autouse=True)
def clean_git_env(monkeypatch):
    """Remove all git-related environment variables from the test process to prevent leakage."""
    for key in list(os.environ.keys()):
        if key.startswith("GIT_"):
            monkeypatch.delenv(key, raising=False)
