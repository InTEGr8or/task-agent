"""Tests for chat archiver configuration schema and loading."""

import json
from pathlib import Path
from taskagent.chat import (
    ChatConfig,
    load_chat_config,
)


def test_default_chat_config():
    config = ChatConfig()
    assert config.s3.bucket == "chatarch"
    assert config.s3.prefix == "chats/"
    assert config.retention.days == 20
    assert config.retention.keep_count == 5
    assert config.summarization.model == "gemini-2.5-flash"
    assert config.summarization.delay == 20.0


def test_load_chat_config_nonexistent_file(tmp_path: Path):
    nonexistent = tmp_path / "config.json"
    config = load_chat_config(nonexistent)
    assert config.s3.bucket == "chatarch"
    assert config.retention.days == 20


def test_load_chat_config_nested(tmp_path: Path):
    config_file = tmp_path / "config.json"
    data = {
        "chat": {
            "s3": {"bucket": "my-custom-bucket", "prefix": "custom-prefix/"},
            "retention": {"days": 10, "keep_count": 3},
            "summarization": {"model": "gemini-2.5-pro", "delay": 10.5},
        }
    }
    config_file.write_text(json.dumps(data), encoding="utf-8")

    config = load_chat_config(config_file)
    assert config.s3.bucket == "my-custom-bucket"
    assert config.s3.prefix == "custom-prefix/"
    assert config.retention.days == 10
    assert config.retention.keep_count == 3
    assert config.summarization.model == "gemini-2.5-pro"
    assert config.summarization.delay == 10.5


def test_load_chat_config_keep_recent_alias(tmp_path: Path):
    config_file = tmp_path / "config.json"
    data = {
        "chat": {
            "retention": {"days": 15, "keep_recent": 7},
        }
    }
    config_file.write_text(json.dumps(data), encoding="utf-8")

    config = load_chat_config(config_file)
    assert config.retention.days == 15
    assert config.retention.keep_count == 7


def test_load_chat_config_top_level(tmp_path: Path):
    config_file = tmp_path / "config.json"
    data = {
        "s3": {"bucket": "root-bucket", "prefix": "root-prefix/"},
    }
    config_file.write_text(json.dumps(data), encoding="utf-8")

    config = load_chat_config(config_file)
    assert config.s3.bucket == "root-bucket"
    assert config.s3.prefix == "root-prefix/"
    assert config.retention.days == 20  # Default


def test_load_chat_config_invalid_json(tmp_path: Path):
    config_file = tmp_path / "config.json"
    config_file.write_text("invalid json {{{", encoding="utf-8")

    config = load_chat_config(config_file)
    assert config.s3.bucket == "chatarch"
