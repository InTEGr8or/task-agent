"""Configuration schema and loader for chat archiver."""

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class S3Config(BaseModel):
    """S3 bucket and prefix configuration for chat archives."""

    bucket: str = Field(default="chatarch", description="AWS S3 bucket name")
    prefix: str = Field(default="chats/", description="S3 object key prefix")


class RetentionConfig(BaseModel):
    """Chat retention policy configuration."""

    days: int = Field(default=20, description="Retention threshold in days")
    keep_count: int = Field(
        default=5,
        alias="keep_recent",
        description="Number of recent chats to keep per workspace",
    )

    model_config = {
        "populate_by_name": True,
    }


class SummarizationConfig(BaseModel):
    """Summarization API configuration."""

    model: str = Field(
        default="gemini-2.5-flash",
        description="Gemini model used for chat summarization",
    )
    delay: float = Field(
        default=20.0,
        description="Delay in seconds between API calls",
    )


class ChatConfig(BaseModel):
    """Complete chat archiver configuration settings."""

    s3: S3Config = Field(default_factory=S3Config)
    retention: RetentionConfig = Field(default_factory=RetentionConfig)
    summarization: SummarizationConfig = Field(default_factory=SummarizationConfig)


def load_chat_config(config_path: Path | None = None) -> ChatConfig:
    """Load and parse chat archiver configuration from ~/.config/task-agent/config.json or custom path.

    Falls back to sensible defaults if the file does not exist, is invalid, or section is omitted.
    """
    import json

    if config_path is None:
        config_path = Path.home() / ".config" / "task-agent" / "config.json"

    if not config_path.is_file():
        return ChatConfig()

    try:
        data: Any = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return ChatConfig()

    if not isinstance(data, dict):
        return ChatConfig()

    # Support nested 'chat' or 'chat_archiver' section
    chat_data = data.get("chat") or data.get("chat_archiver")
    if isinstance(chat_data, dict):
        try:
            return ChatConfig.model_validate(chat_data)
        except Exception:
            return ChatConfig()

    # Check if s3, retention, or summarization are in root data
    if any(key in data for key in ("s3", "retention", "summarization")):
        try:
            return ChatConfig.model_validate(data)
        except Exception:
            return ChatConfig()

    return ChatConfig()
