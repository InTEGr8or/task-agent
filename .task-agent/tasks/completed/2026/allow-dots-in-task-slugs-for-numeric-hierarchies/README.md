# Allow dots in task slugs for numeric hierarchies

The `slugify` method in `manager.py` uses the regex `[^\w\s-]` which strips dots from task titles. This prevents agents from using numeric hierarchy notation like `1.1`, `1.2`, `2.1` etc. in task titles, which some agents natively produce when decomposing work.

**Problem:**
- `slugify()` at `manager.py:224` removes all non-word characters including `.`
- `slugify('1.1 Setup CI')` → `1-1-setup-ci` instead of `1.1-setup-ci`
- This breaks round-trip fidelity when an agent generates a numbered task breakdown and the slugs lose their structural hierarchy

**Solution:**
- Add `.` to the allowed character set in `slugify()`, e.g. `[^\w\s.-]`
- Audit all downstream consumers of slugs to ensure dots don't break:
  - `find_issue_file()` — uses file globs and path joins; dots in directory names are valid on all OS
  - `mission.usv` parser — uses USV (`\x1f`) delimiter, not dot-separated
  - `move_to_active()` / worktree paths — dots in branch/worktree names are valid in git
  - `complete_issue()` — stores in `completed/` directories; dots are valid
  - `soft_delete_issue()` — stores in `deleted/`; dots are valid
- Add unit tests for slugify with dot-containing titles
- Add an integration test: create a task titled `1.1 Test Task`, verify slug is `1.1-test-task`, verify file operations succeed

**Risk:**
- Existing slugs won't change (they have no dots).
- `find_issue_file()` uses `glob(f\"{slug}.*\")` which could match multiple entries if other files contain the slug as a prefix with dot. But this is the same risk as any existing slug (e.g. `foo` matching `foo.md` vs `foo-bar.md`). No regression.

**Completion Criteria:**
- [ ] `slugify()` updated to preserve `.` characters
- [ ] All downstream slug consumers verified for dot-compatibility
- [ ] Existing test suite passes (no regressions from dot-allowing)
- [ ] New unit tests for dot-slug variants
- [ ] Manual test: `ta new '1.1 Test Task' && ta list` shows slug `1.1-test-task`
- [ ] Manual test: worktree creation with a dot-containing slug works

---
**Completed in commit:** `<pending-commit-id>`
