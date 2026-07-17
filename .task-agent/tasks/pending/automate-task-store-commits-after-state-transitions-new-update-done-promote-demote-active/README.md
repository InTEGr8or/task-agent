---
created_at: 2026-07-17T00:00:00-07:00
blocked_by: declare-and-enforce-durability-contract-for-the-task-station-store
subtask_of: station-map-conformance-migration
---

# Automate task-store commits after state transitions

## Problem

After `ta new`, `ta update`, `ta promote`, `ta demote`, `ta active`, and `ta ingest`,
task files are written to disk but never committed. `ta done` commits code work but
not the task file move to completed/. The manual commit commands are no-ops because
`.task-agent/` is gitignored in the consumer repo — and it must STAY gitignored.

The whole point of the eject-mission architecture is that task files live in a
separate mission repo, not the consumer code repo. Committing task files into the
consumer repo would pollute code PRs, bloat clones, and confuse code review.

## Design

1. **Keep `.task-agent/` gitignored in the consumer repo.** This is correct and intentional.

2. **Auto-commit to the MISSION repo, not the code repo.** After every state
   transition, commit task file changes to the mission repo (the git root of
   `issues_root`). In a single-repo setup where the mission repo IS the code repo,
   use `git add -f .task-agent/tasks/` to force-add the gitignored paths. In a
   dual-repo (ejected) setup, the mission repo tracks the tasks dir normally.

3. **Add auto-commit hooks to state-transition methods.** After every filesystem
   write in `create_issue`, `update_issue`, `update_dependencies`,
   `update_subtask_of`, `add_dependency`, `remove_dependency`, `promote_issue`,
   `demote_issue`, `move_to_active`, `complete_issue`, and `ingest_issues`, call
   a `_commit_task_store(message)` helper that:
   - In single-repo: `git add -f .task-agent/tasks/` + `git commit`
   - In dual-repo: `git add .task-agent/tasks/` + `git commit` (mission repo)
   - Only commits if there are staged changes

4. **Update `ta done`** to also commit the task file move (currently only commits
   code work via `git add .` which skips gitignored paths).

5. **Update MCP `commit_repo`/`commit_tasks`** to use `git add -f` in single-repo mode.

## Constraints

- `.task-agent/` stays gitignored in the consumer repo — do NOT remove the entry
- Commits go to the mission repo, scoped to the tasks directory only
- No empty commits
- The ejected-mission architecture must continue to work

## Completion Criteria

1. Task file changes are committed after every state transition
2. Commits target the mission repo, not the code repo (or use -f in single-repo)
3. .task-agent/ remains gitignored in the consumer repo
4. No empty commits
5. Ejected-mission (dual-repo) setup continues to work
6. All existing unit tests pass