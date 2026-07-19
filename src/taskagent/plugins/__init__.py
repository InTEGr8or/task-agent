"""Plugin system for task-agent external integrations."""

from dataclasses import dataclass
from typing import List, Optional, Protocol, runtime_checkable

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


@dataclass(frozen=True)
class RemoteSuggestion:
    """A suggested git remote URL for a centralized task store."""

    url: str
    label: str
    provider: str
    notes: str = ""


@runtime_checkable
class TasksRemoteProvider(Protocol):
    """Plugin protocol: suggest/validate git remotes for task stores.

    Core task-agent only stores and uses git URLs. Provider-specific
    knowledge (sibling ``*-tasks`` repos, GitHub Wiki, etc.) lives here.
    """

    name: str

    def suggest_remote(
        self, host_origin_url: str, moniker: str
    ) -> List[RemoteSuggestion]:
        """Return zero or more remote suggestions for this host/moniker."""
        ...

    def validate_remote(self, url: str) -> Optional[str]:
        """Return an error message if ``url`` is invalid for this provider, else None."""
        ...
