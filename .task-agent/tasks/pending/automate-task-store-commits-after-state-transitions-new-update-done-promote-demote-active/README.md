---
created_at: 2026-07-17T08:59:25.469013-07:00
blocked_by: declare-and-enforce-durability-contract-for-the-task-station-store
subtask_of: station-map-conformance-migration
---

# Automate task-store commits after state transitions (new, update, done, promote, demote, active)

## Problem

`.task-agent/` is gitignored, so all task file changes go uncommitted. The manual commit commands (`ta commit repo|tasks`, MCP `commit_repo`/`commit_tasks`) are no-ops because `git add` skips gitignored paths. After `ta new`, `ta update`, `ta promote`, `ta demote`, `ta active`, and `ta ingest`, task files are written to disk but never committed. `ta done` commits code work but not the task file move to completed/.

This is STATION-MAP conformance gap 4: "Station store excluded from its own durability."

## Design

1. **Resolve the gitignore conflict.** Either:
   a. Remove `.task-agent/` from `.gitignore` (simplest — the station tree gets committed normally)
   b. Keep it gitignored but use `git add -f` in all commit paths (more complex, fragile)
   
   Option (a) is strongly preferred. The `.task-agent/` directory was gitignored during early development; now that task-agent is the product, its own task store should be durable.

2. **Add auto-commit hooks to state-transition methods.** After every filesystem write in `create_issue`, `update_issue`, `update_dependencies`, `update_subtask_of`, `add_dependency`, `remove_dependency`, `promote_issue`, `demote_issue`, `move_to_active`, `complete_issue`, and `ingest_issues`, call a new `_commit_task_store(message)` helper that:
   - `git add .task-agent/tasks/`
   - `git commit -m <message>`
   - Only commits if there are staged changes (no empty commits)

3. **Update `ta done`** to also commit the task file move (currently only commits code work).

4. **Update MCP `commit_repo`/`commit_tasks`** to use `git add -f` if gitignore is kept, or remove the gitignore entry.

## Blocked by

- `declare-and-enforce-durability-contract-for-the-task-station-store` (this is the implementation of that contract)

## Subtask of

- `station-map-conformance-migration`

## Completion Criteria

Task file changes are automatically committed to git after every state transition (ta new, ta update, ta done, ta promote, ta demote, ta active, ta ingest). The .gitignore entry for .task-agent is either removed or the commit uses git add -f. Commits are scoped to .task-agent/tasks/ only. No manual ta commit needed for routine operations.
