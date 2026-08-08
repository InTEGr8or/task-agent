from typing import Dict, Type

from taskagent.importers.base import BaseImporter, ImportedTask, ImportResult
from taskagent.importers.antigravity import AntigravityImporter
from taskagent.importers.claude_code import ClaudeCodeImporter
from taskagent.importers.generic import GenericImporter

_REGISTRY: Dict[str, Type[BaseImporter]] = {
    "antigravity": AntigravityImporter,
    "agy": AntigravityImporter,
    "claude": ClaudeCodeImporter,
    "claude-code": ClaudeCodeImporter,
    "generic": GenericImporter,
}


def get_importer(agent_type: str = "antigravity") -> BaseImporter:
    """Return an instance of the requested agent importer driver."""
    key = (agent_type or "antigravity").lower().strip()
    cls = _REGISTRY.get(key, GenericImporter)
    return cls()


__all__ = [
    "BaseImporter",
    "ImportedTask",
    "ImportResult",
    "AntigravityImporter",
    "ClaudeCodeImporter",
    "GenericImporter",
    "get_importer",
]
