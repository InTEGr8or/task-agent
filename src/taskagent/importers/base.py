from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone


@dataclass
class ImportedTask:
    id: str
    title: str
    status: str = "pending"  # pending, active, completed, draft
    description: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ImportResult:
    agent_type: str
    tasks: List[ImportedTask]
    source: str
    extracted_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_type": self.agent_type,
            "source": self.source,
            "extracted_at": self.extracted_at,
            "count": len(self.tasks),
            "tasks": [t.to_dict() for t in self.tasks],
        }


class BaseImporter(ABC):
    """Base interface for agent task importers with N-1 version compatibility support."""

    agent_type: str = "generic"

    @abstractmethod
    def parse(self, raw_content: str, source: str = "unknown") -> ImportResult:
        """Parse raw task content into normalized ImportResult."""
        pass

    @abstractmethod
    def discover_and_extract(self) -> Optional[ImportResult]:
        """Automatically discover active agent tasks from filesystem environment."""
        pass
