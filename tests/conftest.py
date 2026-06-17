import os
import pytest


@pytest.fixture(autouse=True)
def clean_test_env(monkeypatch):
    """Remove git and task-agent environment variables from the test process to prevent leakage."""
    for key in list(os.environ.keys()):
        if key.startswith("GIT_") or key.startswith("TA_"):
            monkeypatch.delenv(key, raising=False)
