"""Plugin system for task-agent external integrations."""

from typing import Protocol, List, Optional
from taskagent.models.issue import Issue


class IssueProvider(Protocol):
    """Protocol for external issue tracking system providers."""

    def __init__(self, config: dict): ...

    def sync_from_external(self) -> List[Issue]:
        """Import issues from external system."""
        ...

    def sync_to_external(self, issues: List[Issue]) -> None:
        """Export issues to external system."""
        ...

    def get_external_issue(self, issue_id: str) -> Optional[Issue]:
        """Get a specific issue by ID."""
        ...
