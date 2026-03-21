# Migrate docs/issues/ to docs/tasks/

## Background
The project has been renamed from `issue-agent` to `task-agent`. The default storage directory should be `docs/tasks/` to reflect this change. We had a regression where some parts of the code and documentation still refer to `docs/issues/`.

## Completion Criteria
- [ ] Update `TaskAgent.init_project` to automatically migrate `docs/issues/` to `docs/tasks/`.
- [ ] Ensure `ta init` handles symlinks correctly during migration.
- [ ] Scour all documentation (excluding `completed/` tasks) and update `docs/issues/` references to `docs/tasks/`.
- [ ] Update `docs/architecture/README.md` to reflect the correct directory.
- [ ] Ensure `discovery.py` prefers `docs/tasks/` but maintains backwards compatibility for discovery.
- [ ] Verify that `ta init` is idempotent and safe to run multiple times.

## Solution Plan
1.  **Code Change**: Modify `manager.py` to detect if `docs/issues` exists and `docs/tasks` does not (or we are in `init`).
2.  **Move Logic**: In `init_project`, if `self.issues_root` is `docs/issues` and it's not explicitly configured, move it to `docs/tasks`.
3.  **Documentation**: Use `grep_search` to find all occurrences of `docs/issues` and replace them.
