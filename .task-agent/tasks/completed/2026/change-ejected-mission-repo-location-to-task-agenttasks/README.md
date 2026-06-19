---
created_at: 2026-05-15 19:33
---

# Change ejected mission repo location to `.task-agent/tasks/`

Currently `eject-mission` moves `docs/tasks/` to `../{repo_name}-tasks/` (a sibling directory). This scatters project files outside the repo root. Instead, move the ejected repo inside the project to `.task-agent/tasks/` so the project is self-contained.

## Implementation

### 1. Update `cmd_eject_mission` in `src/taskagent/cli.py`

- Change target path:
  ```python
  target_path = project_root / ".task-agent" / "tasks"
  ```

- Update `.gitignore` entry: write `.task-agent/tasks/` instead of `docs/tasks/`

- Update `TA_EJECTED_TASKS_PATH` in `.env` to point to `.task-agent/tasks/`

- Symlink creation unchanged — still works

### 2. Add auto-heal migration in `_handle_ejected_symlink` in `src/taskagent/discovery.py`

The function already runs on every `ta` invocation. Extend it to:

1. **Detect old ejection**: `docs/tasks/` is a symlink pointing to a sibling `{repo_name}-tasks/` path (or any path outside the project root)
2. **Run migration once**: Create `.task-agent/tasks/`, move files, update `.env`, update `.gitignore`, fix symlink, remove old sibling dir
3. **Idempotent**: After migration, no-op on subsequent runs

Edge cases:
- Sibling dir doesn't exist → just update the symlink
- `.task-agent/tasks/` already exists → abort migration
- `.env` doesn't exist → create it

### 3. Verify `ta commit` still works

- No changes needed — already resolves through symlink via `manager.mission_root`

## Risks & Concerns

1. **Name collision**: `.task-agent/worktree-config.json` is tracked. Use `.task-agent/tasks/` subdirectory, not `.task-agent/` itself.

2. **`.gitignore` granularity**: Must add `.task-agent/tasks/` specifically, not `.task-agent/` (would un-track `worktree-config.json`).

3. **Auto-heal safety**: Migration only triggers when old sibling path is detected. Runs once. Idempotent.

---

**Completion Criteria:**
- [ ] `eject-mission` targets `.task-agent/tasks/` instead of sibling directory
- [ ] Auto-heal migrates existing sibling ejections transparently
- [ ] `.gitignore` adds `.task-agent/tasks/` only
- [ ] `TA_EJECTED_TASKS_PATH` points to `.task-agent/tasks/`
- [ ] `ta commit` works with the new location
- [ ] `ta search` finds tasks in the new location
- [ ] All existing tests pass

---
**Completed in commit:** `34e36cf`
