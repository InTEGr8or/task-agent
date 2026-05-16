# Change ejected mission repo location to `.task-agent/tasks/`

Currently `eject-mission` moves `docs/tasks/` to `../{repo_name}-tasks/` (a sibling directory). This scatters project files outside the repo root. Instead, move the ejected repo inside the project to `.task-agent/tasks/` so the project is self-contained.

## Implementation

### 1. Update `cmd_eject_mission` in `src/taskagent/cli.py`

- Change target path from:
  ```python
  target_path = project_root.parent / f"{project_name}-tasks"
  ```
  to:
  ```python
  target_path = project_root / ".task-agent" / "tasks"
  ```

- Update symlink creation (already uses `os.symlink(str(target_path.absolute()), str(source_dir))` — should still work)

- Update `.gitignore` entry: add `.task-agent/tasks/` instead of `docs/tasks/`

- Update `TA_EJECTED_TASKS_PATH` in `.env` to point to `.task-agent/tasks/`

### 2. Update `_handle_ejected_symlink` in `src/taskagent/discovery.py`

- The auto-heal logic constructs `docs/tasks/` symlink pointing to `TA_EJECTED_TASKS_PATH`. If the env var is set correctly, this should work transparently.

### 3. Verify `ta commit` still works

- `cmd_commit` already uses `manager.mission_root` (git root of the symlink target), so it should work with the new path without changes.

## Risks & Concerns

1. **Name collision with `.task-agent/worktree-config.json`**: The repo root already has `.task-agent/worktree-config.json` tracked by git. Using the entire `.task-agent/` as the ejected repo would bury this config file inside a separate git repo. **Solution:** Use `.task-agent/tasks/` (a subdirectory) as the ejected repo, NOT `.task-agent/` itself.

2. **`.gitignore` granularity**: Must NOT add `.task-agent/` to `.gitignore` (would un-track `worktree-config.json`). Instead, add `.task-agent/tasks/` or `.task-agent/tasks` (no trailing slash to cover both dir and sub-repo).

3. **Nested git repo**: `.task-agent/tasks/` will be a nested git repo. Git normally ignores nested repos unless registered as submodules. But ensure no submodule confusion — verify `git status` doesn't show unexpected entries.

4. **Migration path**: Existing users (including this repo itself, if ejected) need to manually migrate from the sibling directory. `eject-mission` already checks if `docs/tasks/` is a symlink and skips if so. A new `re-eject` command or `--force` flag may be needed.

5. **Discovery in worktrees**: `_handle_ejected_symlink` searches up from CWD to find the repo root, then constructs `docs/tasks/` symlink. As long as `TA_EJECTED_TASKS_PATH` is set correctly in `.env`, worktrees and new clones should auto-heal.

6. **Testing**: Update tests in `test_discovery.py` and `test_cli.py` that reference the ejected tasks path.

---

**Completion Criteria:**
- [ ] `cmd_eject_mission` creates the repo at `.task-agent/tasks/` instead of sibling directory
- [ ] Symlink `docs/tasks/` → `.task-agent/tasks/` works correctly
- [ ] `.gitignore` only ignores `.task-agent/tasks/`, not the entire `.task-agent/`
- [ ] `TA_EJECTED_TASKS_PATH` in `.env` points to `.task-agent/tasks/`
- [ ] `ta commit` works with the new symlink target
- [ ] `ta search` finds tasks in the new location
- [ ] Auto-heal in `_handle_ejected_symlink` creates correct symlink
- [ ] All existing tests pass
