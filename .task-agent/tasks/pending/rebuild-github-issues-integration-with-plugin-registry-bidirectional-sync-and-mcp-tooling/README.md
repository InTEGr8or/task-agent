---
created_at: 2026-07-17T08:59:37.628336-07:00
blocked_by: remove-dependency-on-gh-cli-by-adding-api
---

# Rebuild GitHub Issues integration with plugin registry, bidirectional sync, and MCP tooling

## Problem

The GitHub Issues integration is partial and fragile. The `IssueProvider` Protocol exists but `GitHubPlugin` doesn't conform to it. There's no plugin registry, no bidirectional sync, no MCP tooling, and no tests.

## Current state

- `GitHubPlugin` (`plugins/github.py`) has `sync_from_github` and `create_github_issue` — works but doesn't conform to Protocol
- `IssueProvider` Protocol (`plugins/__init__.py`) has `sync_from_external`, `sync_to_external`, `get_external_issue` — none implemented
- `ta github sync` — imports open GH issues (but discards plugin slug, no pagination, no dedup)
- `ta github create <slug>` — creates a GH issue (but only sends title, not body)
- `update_github_issue` (close-on-complete) is dead code — never wired to `ta done`
- No MCP tools for GitHub
- No tests
- No Jira or other integrations

## Scope

1. **Make `GitHubPlugin` conform to `IssueProvider` Protocol** — rename methods or add adapters
2. **Add a plugin registry** — entry-point group or simple factory so new providers (Jira, Linear) can be added without touching CLI/MCP code
3. **Implement `sync_to_external`** — push all pending and active tasks to GH issues (for GH Copilot workflow)
4. **Wire `update_github_issue` into `ta done`** — closing a task closes its linked GH issue
5. **Add MCP tool `sync_to_github`** — so agents can trigger export
6. **Fix slug mismatch** — `cmd_github` discards the plugin's slug and re-derives it, causing duplicates on re-sync
7. **Fix `create` subcommand** — send the full README body, not just the title
8. **Add pagination** — `list_for_repo` needs per_page=100 + pagination loop
9. **Add tests** for the plugin
10. **Add `GITHUB_TOKEN` to `.env.example`** for documentation

## Non-goals

- Jira integration (separate task once the plugin registry exists)
- Webhook-based real-time sync (out of scope for v1)

## Completion Criteria

1. GitHubPlugin conforms to IssueProvider Protocol
2. Plugin registry allows adding new providers without CLI/MCP changes
3. `ta github push` (or `sync_to_external`) pushes all pending+active tasks to GH issues
4. `ta done` closes linked GH issue if one exists
5. MCP tool exists for GitHub sync
6. Slug mismatch fixed — re-syncing doesn't create duplicates
7. Pagination handles repos with >100 issues
8. Tests cover sync_from, sync_to, and close-on-complete
9. GITHUB_TOKEN documented in .env.example

## Completion Criteria

GitHubPlugin conforms to IssueProvider Protocol. Plugin registry allows adding new providers without CLI/MCP changes. ta github push exports all pending+active tasks to GH issues. ta done closes linked GH issue. MCP tool exists for GitHub sync. Slug mismatch fixed. Pagination handles >100 issues. Tests cover sync_from, sync_to, and close-on-complete.
