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


def test_parse_last_user_comment_grok_summary(tmp_path):
    summary_file = tmp_path / "summary.json"
    data = {
        "info": {
            "id": "test-grok-uuid",
            "cwd": str(tmp_path),
        },
        "session_summary": "Implementing quantum key distribution",
        "last_turn_summary": "Fixed unit tests and verified coverage",
        "last_active_at": "2026-11-06T18:48:46Z",
    }
    summary_file.write_text(json.dumps(data))

    chat = DiscoveredChat(agent_id="grok", path=summary_file, parser_type="json")
    mtime, comment = _parse_last_user_comment_and_timestamp(chat)

    assert comment == "Implementing quantum key distribution"
    assert mtime.year == 2026
    assert mtime.month == 11
    assert mtime.day == 6


def test_get_global_recent_sessions(monkeypatch, tmp_path):
    from taskagent.chat.last_used import get_global_recent_sessions

    f1 = tmp_path / "summary.json"
    f1.write_text(
        json.dumps(
            {
                "info": {"id": "grok-session-123", "cwd": "/tmp/myproject"},
                "session_summary": "Grok session title",
                "last_active_at": "2026-11-06T20:00:00Z",
            }
        )
    )

    f2 = tmp_path / "claude-session-456.jsonl"
    f2.write_text(json.dumps({"type": "user", "content": "Claude prompt"}))

    monkeypatch.setattr(
        "glob.glob",
        lambda pat, recursive=False: [str(f1)] if "summary.json" in pat else [],
    )

    discovered = [
        DiscoveredChat(agent_id="claude", path=f2, parser_type="jsonl"),
    ]
    monkeypatch.setattr(
        "taskagent.chat.last_used.discover_agent_chats",
        lambda agent_id=None: discovered,
    )

    sessions = get_global_recent_sessions(limit=10)
    assert len(sessions) >= 2
    grok_sess = next(s for s in sessions if s.agent_id == "grok")
    assert grok_sess.session_id == "grok-session-123"
    assert str(grok_sess.cwd) == "/tmp/myproject"
    assert "grok --resume grok-session-123" in grok_sess.reopen_command
    assert grok_sess.title == "Grok session title"

    claude_sess = next(s for s in sessions if s.agent_id == "claude")
    assert claude_sess.session_id == "claude-session-456"
    assert "claude --resume claude-session-456" in claude_sess.reopen_command


def test_agent_and_agents_print_help_when_incomplete(capsys, monkeypatch):
    import sys
    from taskagent.cli import main

    # 1. ta agent (no subcommand)
    monkeypatch.setattr(sys, "argv", ["ta", "agent"])
    main()
    captured = capsys.readouterr()
    assert "usage: ta agent" in captured.out
    assert (
        "{list,inspect,status,import,recent,last-used}" in captured.out
        or "import" in captured.out
    )

    # 2. ta agents (no agent name or flag)
    monkeypatch.setattr(sys, "argv", ["ta", "agents"])
    main()
    captured = capsys.readouterr()
    assert "usage: ta agents" in captured.out
    assert "agent_name" in captured.out
