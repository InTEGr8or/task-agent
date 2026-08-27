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
from taskagent.chat.last_used import (
    AgentLastUsedInfo,
    get_last_active_agents,
)

__all__ = [
    "AgentLastUsedInfo",
    "ChatConfig",
    "DiscoveredChat",
    "RetentionConfig",
    "S3Config",
    "SummarizationConfig",
    "discover_agent_chats",
    "get_last_active_agents",
    "load_chat_config",
]
