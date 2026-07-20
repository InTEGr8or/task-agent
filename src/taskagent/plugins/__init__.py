"""Plugin system for task-agent external integrations.

Hosted remotes (GitHub, future GitLab/Bitbucket) implement
:class:`TasksRemoteProvider`. Core task-agent only stores git URLs; creating
and naming repos is always plugin work so interoperability is not narrowed
to a single forge.
"""

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


@dataclass(frozen=True)
class CreatedRemote:
    """Result of creating (or locating) a tasks remote on a forge."""

    url: str
    full_name: str
    private: bool
    provider: str
    created: bool  # False if the remote already existed
    notes: str = ""


@runtime_checkable
class TasksRemoteProvider(Protocol):
    """Plugin protocol for forge-specific task-store remotes.

    Core only speaks git URLs after create. Implementations may use their
    forge's SDK/API (not interactive CLIs). Future GitLab/Bitbucket plugins
    implement the same protocol.
    """

    name: str

    def matches_origin(self, host_origin_url: str) -> bool:
        """True if this provider can handle the subject's origin URL."""
        ...

    def suggest_remote(
        self, host_origin_url: str, moniker: str
    ) -> List[RemoteSuggestion]:
        """Return zero or more remote suggestions for this host/moniker."""
        ...

    def validate_remote(self, url: str) -> Optional[str]:
        """Return an error message if ``url`` is invalid for this provider, else None."""
        ...

    def subject_is_private(self, host_origin_url: str) -> Optional[bool]:
        """Return True/False if subject repo visibility is known, else None."""
        ...

    def create_tasks_remote(
        self,
        host_origin_url: str,
        moniker: str,
        *,
        private: bool,
        name: Optional[str] = None,
    ) -> CreatedRemote:
        """Create an empty tasks repo on the forge (or return existing).

        Implementations should create without README/license so local history
        can push cleanly. If the repo already exists, return its URL with
        ``created=False``.
        """
        ...
