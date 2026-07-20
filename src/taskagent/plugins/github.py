"""GitHub Issues integration and task-store remote provider (SDK, not gh CLI)."""

from __future__ import annotations

import os
import re
from typing import List, Optional

from githubkit import GitHub
from githubkit.versions.latest.models import Issue as GitHubIssueModel

from taskagent.models.issue import Issue
from taskagent.plugins import CreatedRemote, RemoteSuggestion


def _parse_github_origin(host_origin_url: str) -> Optional[tuple[str, str, str]]:
    """Return (scheme_style, owner, repo) from a git remote URL if GitHub.

    scheme_style is ``ssh`` (git@host:...) or ``https``.
    """
    raw = (host_origin_url or "").strip()
    if not raw:
        return None

    owner: Optional[str] = None
    repo: Optional[str] = None
    style = "ssh"

    # git@github.com:owner/repo.git
    m = re.match(r"^git@([^:]+):(.+?)(?:\.git)?$", raw)
    if m:
        host, path = m.group(1), m.group(2)
        if "github" not in host.lower():
            return None
        parts = path.strip("/").split("/")
        if len(parts) < 2:
            return None
        owner, repo = parts[0], parts[1]
        style = "ssh"
    else:
        m = re.match(
            r"^https?://([^/]+)/(.+?)(?:\.git)?/?$",
            raw,
            flags=re.IGNORECASE,
        )
        if m:
            host, path = m.group(1), m.group(2)
            if "github" not in host.lower():
                return None
            parts = path.strip("/").split("/")
            if len(parts) < 2:
                return None
            owner, repo = parts[0], parts[1]
            style = "https"
        else:
            m = re.match(r"^ssh://git@([^/]+)/(.+?)(?:\.git)?/?$", raw)
            if not m:
                return None
            host, path = m.group(1), m.group(2)
            if "github" not in host.lower():
                return None
            parts = path.strip("/").split("/")
            if len(parts) < 2:
                return None
            owner, repo = parts[0], parts[1]
            style = "ssh"

    assert owner is not None and repo is not None
    if repo.endswith(".wiki"):
        repo = repo[: -len(".wiki")]
    return style, owner, repo


def _format_github_remote(style: str, owner: str, repo: str) -> str:
    if style == "https":
        return f"https://github.com/{owner}/{repo}.git"
    return f"git@github.com:{owner}/{repo}.git"


def _github_token() -> Optional[str]:
    return (
        os.environ.get("GITHUB_TOKEN")
        or os.environ.get("GH_TOKEN")
        or os.environ.get("github_token")
    )


def _parse_full_name(name: str) -> tuple[str, str]:
    name = name.strip().strip("/")
    if name.endswith(".git"):
        name = name[: -len(".git")]
    parts = name.split("/")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError(f"Tasks repo name must be 'owner/repo' (got {name!r})")
    return parts[0], parts[1]


class GitHubTasksRemoteProvider:
    """GitHub forge plugin for task-store remotes (githubkit SDK).

    Does not use the interactive ``gh`` CLI. Other forges implement the same
    TasksRemoteProvider protocol separately.
    """

    name = "github"

    def matches_origin(self, host_origin_url: str) -> bool:
        return _parse_github_origin(host_origin_url) is not None

    def suggest_remote(
        self, host_origin_url: str, moniker: str
    ) -> List[RemoteSuggestion]:
        parsed = _parse_github_origin(host_origin_url)
        if not parsed:
            return []
        style, owner, repo = parsed
        # Sibling *-tasks only (wiki intentionally unsupported as a product path)
        return [
            RemoteSuggestion(
                url=_format_github_remote(style, owner, f"{repo}-tasks"),
                label="sibling-tasks",
                provider=self.name,
                notes=(
                    f"Dedicated tasks repo {owner}/{repo}-tasks "
                    f"(visibility defaults to match subject; override with --private/--public)"
                ),
            ),
        ]

    def validate_remote(self, url: str) -> Optional[str]:
        if not url or not url.strip():
            return "Empty remote URL"
        if "github" not in url.lower():
            return "URL does not look like a GitHub remote"
        if ".wiki" in url.lower():
            return (
                "GitHub Wiki remotes are not supported for task stores "
                "(use a sibling *-tasks repository instead)"
            )
        return None

    def subject_is_private(self, host_origin_url: str) -> Optional[bool]:
        parsed = _parse_github_origin(host_origin_url)
        if not parsed:
            return None
        _style, owner, repo = parsed
        token = _github_token()
        if not token:
            return None
        try:
            gh = GitHub(token)
            resp = gh.rest.repos.get(owner, repo)
            # githubkit model: private is bool
            return bool(getattr(resp.parsed_data, "private", None))
        except Exception:
            return None

    def create_tasks_remote(
        self,
        host_origin_url: str,
        moniker: str,
        *,
        private: bool,
        name: Optional[str] = None,
    ) -> CreatedRemote:
        parsed = _parse_github_origin(host_origin_url)
        if not parsed:
            raise ValueError(
                f"Subject origin is not a GitHub URL: {host_origin_url!r}. "
                "Use a GitHub subject, or pass --provider when other forges are available."
            )
        style, owner, repo = parsed
        if name:
            tasks_owner, tasks_repo = _parse_full_name(name)
        else:
            tasks_owner, tasks_repo = owner, f"{repo}-tasks"

        token = _github_token()
        if not token:
            raise ValueError(
                "GitHub token required to create a tasks repo. "
                "Set GITHUB_TOKEN or GH_TOKEN (repo scope)."
            )

        gh = GitHub(token)
        full_name = f"{tasks_owner}/{tasks_repo}"
        url = _format_github_remote(style, tasks_owner, tasks_repo)

        # Already exists?
        try:
            existing = gh.rest.repos.get(tasks_owner, tasks_repo)
            priv = bool(getattr(existing.parsed_data, "private", private))
            return CreatedRemote(
                url=url,
                full_name=full_name,
                private=priv,
                provider=self.name,
                created=False,
                notes=f"Repository {full_name} already exists; will attach",
            )
        except Exception:
            pass

        # Create empty repo (no README/license) so local history can push cleanly
        try:
            me = gh.rest.users.get_authenticated()
            authed_login = getattr(me.parsed_data, "login", None)
        except Exception as e:
            raise RuntimeError(f"Failed to identify GitHub user: {e}") from e

        try:
            if authed_login and tasks_owner.lower() == str(authed_login).lower():
                gh.rest.repos.create_for_authenticated_user(
                    name=tasks_repo,
                    private=private,
                    auto_init=False,
                    description=f"task-agent store for {moniker}",
                )
            else:
                gh.rest.repos.create_in_org(
                    org=tasks_owner,
                    name=tasks_repo,
                    private=private,
                    auto_init=False,
                    description=f"task-agent store for {moniker}",
                )
        except Exception as e:
            raise RuntimeError(
                f"Failed to create GitHub repository {full_name}: {e}"
            ) from e

        return CreatedRemote(
            url=url,
            full_name=full_name,
            private=private,
            provider=self.name,
            created=True,
            notes=f"Created empty {'private' if private else 'public'} repo {full_name}",
        )


class GitHubPlugin:
    """Plugin for syncing with GitHub Issues."""

    def __init__(self, config: dict):
        """Initialize with config dict containing 'token' and optionally 'repo'."""
        github_config = config.get("github", {})

        self.token = (
            github_config.get("token")
            or config.get("token")
            or os.environ.get("GITHUB_TOKEN")
        )
        self.repo_full_name = github_config.get("repo") or config.get("repo")

        if not self.token:
            raise ValueError(
                "GitHub token required. Set 'github.token' in config or GITHUB_TOKEN env var."
            )

        if not self.repo_full_name:
            raise ValueError("GitHub repo required. Set 'github.repo' in config.")

        self.github = GitHub(self.token)

    def _to_task_agent_issue(self, gh_issue: GitHubIssueModel) -> Issue:
        """Convert a GitHub Issue to TaskAgent Issue."""
        slug = f"gh-{gh_issue.number}-{gh_issue.title.lower().replace(' ', '-')[:50]}"

        return Issue(
            name=gh_issue.title or f"GitHub Issue #{gh_issue.number}",
            slug=slug,
            dependencies=[],
            priority=0,
            status="pending" if gh_issue.state == "open" else "completed",
        )

    def _to_github_issue(self, issue: Issue) -> dict:
        """Convert TaskAgent Issue to GitHub Issue creation payload."""
        return {
            "title": issue.name,
            "body": f"Imported from TaskAgent\nSlug: {issue.slug}",
        }

    def sync_from_github(self) -> List[Issue]:
        """Import open issues from GitHub repository."""
        if not self.repo_full_name:
            raise ValueError("Repository not specified. Set 'repo' in config.")

        owner, repo = self.repo_full_name.split("/")
        issues: List[Issue] = []

        try:
            resp = self.github.rest.issues.list_for_repo(owner, repo, state="open")

            for gh_issue in resp.parsed_data:  # type: ignore[attr-defined]
                if hasattr(gh_issue, "pull_request"):
                    continue

                issue = self._to_task_agent_issue(gh_issue)
                issues.append(issue)

            return issues
        except Exception as e:
            raise RuntimeError(f"Failed to fetch GitHub issues: {e}")

    def create_github_issue(self, issue: Issue) -> dict:
        """Create a GitHub Issue from a TaskAgent Issue."""
        if not self.repo_full_name:
            raise ValueError("Repository not specified. Set 'repo' in config.")

        owner, repo = self.repo_full_name.split("/")
        payload = self._to_github_issue(issue)

        try:
            resp = self.github.rest.issues.create(owner, repo, **payload)
            return {
                "number": resp.parsed_data.number,
                "url": resp.parsed_data.html_url,
            }
        except Exception as e:
            raise RuntimeError(f"Failed to create GitHub issue: {e}")

    def update_github_issue(self, gh_issue_number: int, status: str):
        """Update a GitHub Issue (e.g., close when completed in task-agent)."""
        if not self.repo_full_name:
            raise ValueError("Repository not specified. Set 'repo' in config.")

        owner, repo = self.repo_full_name.split("/")

        try:
            if status == "completed":
                self.github.rest.issues.update(
                    owner, repo, gh_issue_number, state="closed"
                )
            elif status == "pending":
                self.github.rest.issues.update(
                    owner, repo, gh_issue_number, state="open"
                )
        except Exception as e:
            raise RuntimeError(f"Failed to update GitHub issue: {e}")
