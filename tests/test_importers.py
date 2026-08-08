import json
from pathlib import Path
import pytest

from taskagent.importers import (
    AntigravityImporter,
    ClaudeCodeImporter,
    GenericImporter,
    get_importer,
)
from taskagent.manager import TaskAgent


def test_get_importer_registry():
    assert isinstance(get_importer("antigravity"), AntigravityImporter)
    assert isinstance(get_importer("agy"), AntigravityImporter)
    assert isinstance(get_importer("claude"), ClaudeCodeImporter)
    assert isinstance(get_importer("claude-code"), ClaudeCodeImporter)
    assert isinstance(get_importer("generic"), GenericImporter)
    assert isinstance(get_importer("unknown"), GenericImporter)


def test_antigravity_importer_json_v2():
    importer = AntigravityImporter()
    raw = json.dumps(
        {
            "tasks": [
                {"id": "ag-1", "title": "Setup database", "status": "completed"},
                {"id": "ag-2", "title": "Create endpoints", "status": "pending"},
            ]
        }
    )
    res = importer.parse(raw, source="test")
    assert res.agent_type == "antigravity"
    assert len(res.tasks) == 2
    assert res.tasks[0].id == "ag-1"
    assert res.tasks[0].title == "Setup database"
    assert res.tasks[0].status == "completed"
    assert res.tasks[1].title == "Create endpoints"


def test_antigravity_importer_legacy_v1_and_markdown():
    importer = AntigravityImporter()
    raw_json_v1 = json.dumps(["Step 1", "Step 2"])
    res = importer.parse(raw_json_v1)
    assert len(res.tasks) == 2
    assert res.tasks[0].title == "Step 1"

    raw_md = "- [ ] Pending item\n- [x] Done item"
    res_md = importer.parse(raw_md)
    assert len(res_md.tasks) == 2
    assert res_md.tasks[0].status == "pending"
    assert res_md.tasks[1].status == "completed"


def test_claude_code_importer():
    importer = ClaudeCodeImporter()
    raw = json.dumps(
        {
            "todos": [
                {"id": "c1", "content": "Refactor auth", "completed": False},
                {"id": "c2", "content": "Write unit tests", "completed": True},
            ]
        }
    )
    res = importer.parse(raw)
    assert res.agent_type == "claude-code"
    assert len(res.tasks) == 2
    assert res.tasks[0].title == "Refactor auth"
    assert res.tasks[0].status == "pending"
    assert res.tasks[1].title == "Write unit tests"
    assert res.tasks[1].status == "completed"


def test_resolve_working_task_ambiguity(tmp_path: Path):
    tasks_dir = tmp_path / "docs" / "tasks"
    mission_dir = tasks_dir / ".task-agent"
    mission_dir.mkdir(parents=True)
    (mission_dir / "mission.usv").write_text(
        "Task A\x1ftask-a\x1f\x1f\nTask B\x1ftask-b\x1f\x1f\n"
    )
    (mission_dir / "datapackage.json").write_text("{}")

    active_dir = tasks_dir / "active"
    active_dir.mkdir(parents=True)

    manager = TaskAgent(config_dir=str(tasks_dir))
    manager.sync_mission(ingest=True)

    # Scenario 1: 0 active tasks -> raises ValueError requiring --slug
    with pytest.raises(ValueError, match="No active working task found"):
        manager.resolve_working_task()

    # Explicit slug works
    (active_dir / "task-a").mkdir()
    (active_dir / "task-a" / "README.md").write_text("# Task A\n")
    manager.sync_mission(ingest=True)
    assert manager.resolve_working_task("task-a") == "task-a"

    # Scenario 2: >1 active tasks -> raises ValueError requiring --slug
    (active_dir / "task-b").mkdir()
    (active_dir / "task-b" / "README.md").write_text("# Task B\n")
    manager.sync_mission(ingest=True)
    with pytest.raises(ValueError, match="Multiple active working tasks found"):
        manager.resolve_working_task()


def test_import_agent_tasks_to_imports_folder(tmp_path: Path):
    tasks_dir = tmp_path / "docs" / "tasks"
    mission_dir = tasks_dir / ".task-agent"
    mission_dir.mkdir(parents=True)
    (mission_dir / "mission.usv").write_text("Task Active\x1ftask-active\x1f\x1f\n")
    (mission_dir / "datapackage.json").write_text("{}")

    active_dir = tasks_dir / "active" / "task-active"
    active_dir.mkdir(parents=True)
    (active_dir / "README.md").write_text("# Task Active\n")

    manager = TaskAgent(config_dir=str(tasks_dir))
    manager.sync_mission(ingest=True)

    raw_payload = json.dumps([{"title": "Sub-item 1", "status": "pending"}])

    res = manager.import_agent_tasks(
        slug="task-active",
        agent_type="antigravity",
        raw_content=raw_payload,
    )

    assert res["slug"] == "task-active"
    assert res["count"] == 1

    imported_file = active_dir / "imports" / "antigravity_tasks.json"
    assert imported_file.exists()

    data = json.loads(imported_file.read_text(encoding="utf-8"))
    assert data["agent_type"] == "antigravity"
    assert data["tasks"][0]["title"] == "Sub-item 1"
