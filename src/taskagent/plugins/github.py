"""GitHub Issues integration plugin for task-agent."""

import os
from typing import List
from githubkit import GitHub, Auth
from githubkit.versions.latest.models import Issue as GitHubIssueModel

from taskagent.models.issue import Issue


class GitHubPlugin:
    """Plugin for syncing with GitHub Issues."""

    def __init__(self, config: dict):
        """Initialize with config dict containing 'token' and optionally 'repo'."""
        self.token = config.get("token") or os.environ.get("GITHUB_TOKEN")
        self.repo_full_name = config.get("repo")  # e.g., "owner/repo"

        if not self.token:
            raise ValueError(
                "GitHub token required. Set 'token' in config or GITHUB_TOKEN env var."
            )

        auth = Auth.Token(self.token)
        self.github = GitHub(auth)

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

            for gh_issue in resp.parsed_data:
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
