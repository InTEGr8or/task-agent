import sys
import os
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Mock google and google.adk modules before importing worker
google_mock = MagicMock()
sys.modules["google"] = google_mock
sys.modules["google.adk"] = google_mock
sys.modules["google.adk.agents"] = google_mock
sys.modules["google.adk.models"] = google_mock
sys.modules["google.adk.tools"] = google_mock
sys.modules["google.adk.tools.tool_context"] = google_mock
sys.modules["google.adk.runners"] = google_mock
sys.modules["google.genai"] = google_mock

# Now add sidecar directory to python path
sys.path.insert(0, str(Path(__file__).parent.parent / "sidecars" / "adk-worker"))

# Set GOOGLE_API_KEY environment variable to satisfy the module-level check
os.environ["GOOGLE_API_KEY"] = "dummy-key"
import worker  # noqa: E402


def test_get_available_cli():
    with patch("shutil.which") as mock_which:
        # None available
        mock_which.return_value = None
        assert worker.get_available_cli() is None

        # agy available
        mock_which.side_effect = lambda x: f"/usr/bin/{x}" if x == "agy" else None
        assert worker.get_available_cli() == "agy"

        # claude available
        mock_which.side_effect = lambda x: f"/usr/bin/{x}" if x == "claude" else None
        assert worker.get_available_cli() == "claude"

        # opencode available
        mock_which.side_effect = lambda x: f"/usr/bin/{x}" if x == "opencode" else None
        assert worker.get_available_cli() == "opencode"


def test_read_task_description(tmp_path):
    # Non-existent file
    non_existent = tmp_path / "missing.md"
    res = worker.read_task_description(str(non_existent))
    assert "Could not read task description" in res

    # Existent file
    existing = tmp_path / "readme.md"
    existing.write_text("Hello task description", encoding="utf-8")
    res = worker.read_task_description(str(existing))
    assert res == "Hello task description"


def test_run_agy_cli_workflow_success(tmp_path):
    slug = "test-slug"
    file_path = tmp_path / "task.md"
    file_path.write_text("Test Task Content", encoding="utf-8")
    project_root = tmp_path

    mock_runner_cls = MagicMock()
    google_mock.InMemoryRunner = mock_runner_cls

    # Mock get_available_cli to return "agy"
    # Mock subprocess.run to succeed
    with (
        patch("worker.get_available_cli", return_value="agy"),
        patch("subprocess.run") as mock_run,
    ):
        # Mock subprocess run result
        mock_run.return_value = MagicMock(
            returncode=0, stdout="Worker output", stderr=""
        )

        # Mock InMemoryRunner instance
        mock_runner = MagicMock()
        mock_runner_cls.return_value = mock_runner

        # Mock event sequence: first event has event.actions.escalate = True
        mock_event = MagicMock()
        mock_event.actions = MagicMock(escalate=True)
        mock_event.content = MagicMock(parts=[MagicMock(text="Validation passed")])
        mock_runner.run.return_value = [mock_event]

        # Mock session retrieval
        mock_session = MagicMock()
        mock_session.state = {"validation_feedback": "Validation succeeded!"}
        mock_runner.session_service._get_session_impl.return_value = mock_session

        # Run the workflow
        worker.run_agy_cli_workflow(slug, str(file_path), str(project_root))

        # Check that agy -p was run
        mock_run.assert_any_call(
            [
                "agy",
                "-p",
                "Solve the following task in the codebase:\n\nTest Task Content\n\nInstructions:\n1. Attempt to solve the task or make appropriate changes to the codebase.\n2. If the task is too complex, break it into smaller sub-tasks (decompose it) and report these actions in the task completion notes.\n",
            ],
            capture_output=True,
            text=True,
            check=True,
        )

        # Check that MR file was written
        mr_file = project_root / "docs" / "tasks" / "mr" / f"{slug}.md"
        assert mr_file.exists()
        assert mr_file.read_text(encoding="utf-8") == "Validation succeeded!"


def test_run_agy_cli_workflow_failure_then_success(tmp_path):
    slug = "test-slug"
    file_path = tmp_path / "task.md"
    file_path.write_text("Test Task Content", encoding="utf-8")
    project_root = tmp_path

    mock_runner_cls = MagicMock()
    google_mock.InMemoryRunner = mock_runner_cls

    with (
        patch("worker.get_available_cli", return_value="claude"),
        patch("subprocess.run") as mock_run,
    ):
        # Mock subprocess runs
        mock_run.return_value = MagicMock(returncode=0, stdout="Output", stderr="")

        # We will run 2 iterations:
        # Iteration 1: validator fails (yields event with escalate=False)
        # Iteration 2: validator passes (yields event with escalate=True)
        mock_runner = MagicMock()
        mock_runner_cls.return_value = mock_runner

        event_fail = MagicMock()
        event_fail.actions = MagicMock(escalate=False)
        event_fail.content = MagicMock(parts=[MagicMock(text="Validation failed")])

        event_pass = MagicMock()
        event_pass.actions = MagicMock(escalate=True)
        event_pass.content = MagicMock(parts=[MagicMock(text="Validation passed")])

        # side_effect for runner.run
        mock_runner.run.side_effect = [[event_fail], [event_pass]]

        # side_effect for session state
        session_fail = MagicMock()
        session_fail.state = {"validation_feedback": "Please fix formatting."}
        session_pass = MagicMock()
        session_pass.state = {"validation_feedback": "Looks good!"}
        mock_runner.session_service._get_session_impl.side_effect = [
            session_fail,
            session_pass,
        ]

        # Run workflow
        worker.run_agy_cli_workflow(slug, str(file_path), str(project_root))

        # Should have executed subprocess.run twice (first iteration and second iteration)
        assert mock_run.call_count == 2

        # Second run should have included the feedback from iteration 1 in prompt
        second_call_args = mock_run.call_args_list[1][0][0]
        assert "Please fix formatting." in second_call_args[2]

        # MR file should have the final success solution
        mr_file = project_root / "docs" / "tasks" / "mr" / f"{slug}.md"
        assert mr_file.exists()
        assert mr_file.read_text(encoding="utf-8") == "Looks good!"


def test_main_agy_cli(tmp_path, monkeypatch):
    # Set up environment variables
    monkeypatch.setenv("TA_SLUG", "test-slug")
    monkeypatch.setenv("TA_FILE", str(tmp_path / "task.md"))
    monkeypatch.setenv("TA_ROOT", str(tmp_path))

    # Create dummy files
    (tmp_path / "task.md").write_text("Task info", encoding="utf-8")

    # Create .ta-agent.json pointing to agy-cli template
    import json

    with open(tmp_path / ".ta-agent.json", "w") as f:
        json.dump({"template": "agy-cli", "user": "agent-user"}, f)

    # Monkeypatch the working directory to tmp_path so it finds .ta-agent.json
    monkeypatch.chdir(tmp_path)

    with patch("worker.run_agy_cli_workflow") as mock_workflow:
        worker.main()
        mock_workflow.assert_called_once_with(
            "test-slug", str(tmp_path / "task.md"), str(tmp_path)
        )


def test_run_agy_cli_workflow_auth_failed(tmp_path):
    import subprocess

    slug = "test-slug"
    file_path = tmp_path / "task.md"
    file_path.write_text("Test Task Content", encoding="utf-8")
    project_root = tmp_path

    # Mock get_available_cli to return "agy"
    # Mock subprocess.run to raise CalledProcessError with authentication error message
    with (
        patch("worker.get_available_cli", return_value="agy"),
        patch("subprocess.run") as mock_run,
    ):
        mock_error = subprocess.CalledProcessError(
            returncode=1,
            cmd=["agy", "-p", "..."],
            output="Please login to Antigravity CLI",
            stderr="gcloud auth login required",
        )
        mock_run.side_effect = mock_error

        # Running this should call sys.exit(1)
        with pytest.raises(SystemExit) as exc_info:
            worker.run_agy_cli_workflow(slug, str(file_path), str(project_root))

        assert exc_info.value.code == 1
