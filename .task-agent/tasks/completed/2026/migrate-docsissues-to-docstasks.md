# Migrate docs/issues/ to docs/tasks/

## Background
The project started as `issue-agent` and stores everything in `docs/issues/`. We've migrated the repo and package to `task-agent`, but the storage path still uses the old name.

## Current State
- Default path: `docs/tasks`
- Eject creates: `{project}-tasks/` sibling directory with symlink at `docs/tasks`
- Config stored in: `.env` with `TA_EJECT_TASKS=true` and `TA_EJECTED_TASKS_PATH`
- Supports legacy `docs/issues` for migration (discovers both, prefers `docs/tasks`)
- Supports both `TA_EJECT_ISSUES` and `TA_EJECT_TASKS` env vars for backwards compatibility

## Migration Approach

### 1. Add a `tasks_dir` config key
Add a new config option (parallel to `issues_dir`) with default `docs/tasks`. Support both for backwards compatibility.

### 2. Update default path in `manager.py:71`
```python
issues_root = Path(env_dir) if env_dir else Path("docs/tasks")
```

### 3. Detect and migrate ejected configurations
When running `init` or detecting config, check for:
- `TA_EJECT_ISSUES=true` → migrate to `TA_EJECT_TASKS`
- Rename `{project}-issues` → `{project}-tasks`
- Recreate symlink at `docs/tasks`
- Update `.env`

### 4. Migration command
Add a `migrate-to-tasks` command that:
1. Renames local `docs/issues` → `docs/tasks`
2. Handles ejected case by renaming sibling + updating symlink + updating env
3. Updates config files (`pyproject.toml`, `.ta-config.json`)
4. Updates any hardcoded references

### 5. Backwards compatibility
Keep `issues_dir` config key working but deprecated. New installs use `docs/tasks` by default.

## Question
Should the ejected sibling directory keep the `-issues` suffix (e.g., `myproject-issues`) or also migrate to `-tasks`? The latter is cleaner but requires updating the external repo name on GitHub.

---
**Completed in commit:** `8518b7c`
