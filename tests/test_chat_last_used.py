import json

from multi_agent_registry import DiscoveredChat
from taskagent.chat.last_used import (
    AgentLastUsedInfo,
    _parse_last_user_comment_and_timestamp,
    get_last_active_agents,
)


def test_parse_last_user_comment_jsonl(tmp_path):
    log_file = tmp_path / "claude_session.jsonl"
    lines = [
        json.dumps({"type": "system", "content": "Init"}),
        json.dumps({"type": "user", "content": "First prompt from user"}),
        json.dumps({"type": "assistant", "content": "AI response"}),
        json.dumps(
            {
                "type": "user",
                "content": "Please refactor the database connector for production",
            }
        ),
    ]
    log_file.write_text("\n".join(lines))

    chat = DiscoveredChat(agent_id="claude", path=log_file, parser_type="jsonl")
    mtime, comment = _parse_last_user_comment_and_timestamp(chat)

    assert comment == "Please refactor the database connector for production"
    assert mtime is not None


def test_parse_last_user_comment_json(tmp_path):
    log_file = tmp_path / "session.json"
    data = {
        "messages": [
            {"say": "user", "text": "Initial task message"},
            {"say": "assistant", "text": "Working on it"},
            {"say": "user", "text": "Add unit tests for the chat discovery module"},
        ]
    }
    log_file.write_text(json.dumps(data))

    chat = DiscoveredChat(agent_id="agy", path=log_file, parser_type="json")
    mtime, comment = _parse_last_user_comment_and_timestamp(chat)

    assert comment == "Add unit tests for the chat discovery module"


def test_parse_last_user_comment_markdown(tmp_path):
    log_file = tmp_path / ".aider.chat.history.md"
    content = """# session log

#### user
Fix memory leak in background worker queue

#### assistant
Analyzing queue implementation...
"""
    log_file.write_text(content)

    chat = DiscoveredChat(agent_id="aider", path=log_file, parser_type="markdown")
    mtime, comment = _parse_last_user_comment_and_timestamp(chat)

    assert "Fix memory leak in background worker queue" in comment


def test_get_last_active_agents(monkeypatch, tmp_path):
    f1 = tmp_path / "claude.jsonl"
    f1.write_text(json.dumps({"type": "user", "content": "Claude task"}))

    f2 = tmp_path / "agy.json"
    f2.write_text(json.dumps([{"say": "user", "text": "Antigravity task"}]))

    discovered = [
        DiscoveredChat(agent_id="claude", path=f1, parser_type="jsonl"),
        DiscoveredChat(agent_id="agy", path=f2, parser_type="json"),
    ]

    monkeypatch.setattr(
        "taskagent.chat.last_used.discover_agent_chats",
        lambda project_dir=None: discovered,
    )

    results = get_last_active_agents(project_dir=tmp_path, limit=5)
    assert len(results) == 2
    agent_ids = {r.agent_id for r in results}
    assert agent_ids == {"claude", "agy"}
    for r in results:
        assert isinstance(r, AgentLastUsedInfo)
        assert r.description != ""
