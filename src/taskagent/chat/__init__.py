"""Chat archival module for task-agent."""

from taskagent.chat.config import (
    ChatConfig,
    RetentionConfig,
    S3Config,
    SummarizationConfig,
    load_chat_config,
)
from taskagent.chat.discovery import (
    DiscoveredChat,
    discover_agent_chats,
)

__all__ = [
    "ChatConfig",
    "DiscoveredChat",
    "RetentionConfig",
    "S3Config",
    "SummarizationConfig",
    "discover_agent_chats",
    "load_chat_config",
]
