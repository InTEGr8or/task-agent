"""GitHub Issues integration and task-store remote suggestions."""

from __future__ import annotations

import os
import re
from typing import List, Optional
from githubkit import GitHub
from githubkit.versions.latest.models import Issue as GitHubIssueModel

from taskagent.models.issue import Issue
from taskagent.plugins import RemoteSuggestion


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
    # Strip wiki suffix if someone passes a wiki remote as origin
    if repo.endswith(".wiki"):
        repo = repo[: -len(".wiki")]
    return style, owner, repo


def _format_github_remote(style: str, owner: str, repo: str) -> str:
    if style == "https":
        return f"https://github.com/{owner}/{repo}.git"
    return f"git@github.com:{owner}/{repo}.git"


class GitHubTasksRemoteProvider:
    """Suggest GitHub remotes for centralized task stores (no API required)."""

    name = "github"

    def suggest_remote(
        self, host_origin_url: str, moniker: str
    ) -> List[RemoteSuggestion]:
        parsed = _parse_github_origin(host_origin_url)
        if not parsed:
            return []
        style, owner, repo = parsed
        suggestions = [
            RemoteSuggestion(
                url=_format_github_remote(style, owner, f"{repo}-tasks"),
                label="sibling-tasks",
                provider=self.name,
                notes=f"Dedicated private/public repo {owner}/{repo}-tasks",
            ),
            RemoteSuggestion(
                url=_format_github_remote(style, owner, f"{repo}.wiki"),
                label="wiki",
                provider=self.name,
                notes=(
                    f"GitHub Wiki remote for {owner}/{repo} "
                    "(requires wiki enabled; limited tooling)"
                ),
            ),
            RemoteSuggestion(
                url=_format_github_remote(style, owner, repo),
                label="same-repo",
                provider=self.name,
                notes=(
                    "Same remote as the subject repo (tasks live on a branch "
                    "or co-located history — usually not recommended)"
                ),
            ),
        ]
        return suggestions

    def validate_remote(self, url: str) -> Optional[str]:
        if not url or not url.strip():
            return "Empty remote URL"
        if "github" not in url.lower():
            return "URL does not look like a GitHub remote"
        return None


class GitHubPlugin:
    """Plugin for syncing with GitHub Issues."""

    def __init__(self, config: dict):
        """Initialize with config dict containing 'token' and optionally 'repo'."""
        # Allow config to come from worktree-config.json under "github" key
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
        # Use GitHub issue number as part of slug for uniqueness
        slug = f"gh-{gh_issue.number}-{gh_issue.title.lower().replace(' ', '-')[:50]}"

        return Issue(
            name=gh_issue.title or f"GitHub Issue #{gh_issue.number}",
            slug=slug,
            dependencies=[],  # GitHub doesn't have native dependency tracking
            priority=0,  # Will be assigned by task-agent
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
            # Get open issues (excluding pull requests)
            resp = self.github.rest.issues.list_for_repo(owner, repo, state="open")

            for gh_issue in resp.parsed_data:  # type: ignore[attr-defined]
                # Skip pull requests (they appear as issues in GitHub API)
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
