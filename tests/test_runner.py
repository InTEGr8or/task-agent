from pathlib import Path
from taskagent.manager import TaskAgent
from taskagent.runner import TaskCompletionResult, TaskWorktreeRunner


def test_task_completion_result_pydantic():
    result = TaskCompletionResult(
        slug="test-task",
        solution_explanation="Implemented feature X",
        input_tokens=1200,
        output_tokens=350,
        cost_usd=0.0042,
        tokens_accuracy="measured",
    )
    assert result.schema_version == 1
    assert result.slug == "test-task"
    assert result.input_tokens == 1200
    assert result.tokens_accuracy == "measured"


def test_runner_fsm_lifecycle(tmp_path: Path):
    tasks_dir = tmp_path / "docs" / "tasks"
    mission_dir = tasks_dir / ".task-agent"
    mission_dir.mkdir(parents=True)
    (mission_dir / "mission.usv").write_text("Runner Task\x1frunner-task\x1f\x1f\n")
    (mission_dir / "datapackage.json").write_text("{}")

    pending_dir = tasks_dir / "pending" / "runner-task"
    pending_dir.mkdir(parents=True)
    (pending_dir / "README.md").write_text("# Runner Task\n")

    manager = TaskAgent(config_dir=str(tasks_dir))
    manager.sync_mission(ingest=True)

    runner = TaskWorktreeRunner(
        manager,
        "runner-task",
        agent_name="antigravity",
        model_name="gemini-3.6-flash",
    )
    assert runner.state == "init"

    # Transition to running
    runner.start()
    assert runner.state == "running"

    record = runner.get_state_record()
    assert record.slug == "runner-task"
    assert record.state == "running"
    assert record.agent_name == "antigravity"

    # Heartbeat
    lease = runner.heartbeat()
    assert lease["slug"] == "runner-task"
    assert lease["status"] == "active"

    # Finish task
    completion = TaskCompletionResult(
        slug="runner-task",
        solution_explanation="Completed runner task execution.",
    )
    runner.finish(completion, should_commit=False)
    assert runner.state == "completed"
    assert manager.get_lease("runner-task") is None


def test_runner_fsm_failure_flow(tmp_path: Path):
    tasks_dir = tmp_path / "docs" / "tasks"
    mission_dir = tasks_dir / ".task-agent"
    mission_dir.mkdir(parents=True)
    (mission_dir / "mission.usv").write_text("Fail Task\x1ffail-task\x1f\x1f\n")
    (mission_dir / "datapackage.json").write_text("{}")

    pending_dir = tasks_dir / "pending" / "fail-task"
    pending_dir.mkdir(parents=True)
    (pending_dir / "README.md").write_text("# Fail Task\n")

    manager = TaskAgent(config_dir=str(tasks_dir))
    manager.sync_mission(ingest=True)

    runner = TaskWorktreeRunner(manager, "fail-task")
    runner.start()
    assert runner.state == "running"

    runner.fail("Worker process exited with code 1")
    assert runner.state == "failed"
    assert runner.error_message == "Worker process exited with code 1"
    assert manager.get_lease("fail-task") is None
