---
created_at: 2026-06-14T10:03:52-07:00
---

# Add Dependency model with required reason for dependency declarations

At the architecture level, enforce that every dependency declaration includes a human-readable reason. This prevents agents from creating false dependency chains (using `--blocked-by` as a grouping mechanism rather than expressing a true prerequisite).

The dependency is stored only in the markdown file — the USV stays as bare slugs (lightweight index, not source of truth). The model lives in the data layer so any future interface (CLI, MCP, GUI) inherits the constraint automatically.

## Design

Add `Dependency` model to `models/issue.py`:

```python
class Dependency(BaseModel):
    slug: str
    reason: str  # human-readable explanation
```

Change `Issue.dependencies` from `List[str]` to `List[Dependency]`. `Issue.to_usv()` still serializes only slugs — no USV format change.

## Markdown storage

- Current: `Blocked by: slug1, slug2`
- New: `Blocked by: slug1 -- reason text, slug2 -- reason text`
- `extract_deps()` splits on `, `, then each entry on ` -- `
- Backward compat: entries without ` -- ` get empty reason (old files parse cleanly)

## CLI

- `ta new "Foo" --blocked-by "bar" --reason "because auth needs to ship first"`
- `--reason` is required when `--blocked-by` is used
- `ta add-dep <slug> <dep-slug> --reason "text"` — add more deps later
- `ta remove-dep <slug> <dep-slug>`
- Update existing `add_dependency` and `remove_dependency` in manager.py

## MCP

- `create_task` dependency schema: `[{"slug": "bar", "reason": "because..."}]`
- `reason` required within each dependency object
- Matching `add_dependency` tool with `slug`, `dep_slug`, `reason`

## Display (ta tree, ta list)

```
○ foo
  └─ ○ bar  (blocked by: foo — because auth needs to ship first)
```

## Backward compatibility

- Old USV entries with bare slug strings — unchanged by design
- Old markdown `Blocked by: slug1, slug2` — no ` -- ` separator found, reason defaults to `""`
- Existing tests: update fixtures from `["slug1", "slug2"]` to `[Dependency(slug="slug1"), ...]`

Only the markdown files need updating to include reasons. No database or index migration needed.

## Completion Criteria

- [ ] `Dependency` model in `models/issue.py`
- [ ] `Issue.dependencies` updated to `List[Dependency]`
- [ ] `to_usv()` unchanged (bare slugs only)
- [ ] `load_mission()` populates Dependency objects from file
- [ ] `save_mission()` still calls to_usv() — no USV change
- [ ] `extract_deps()` parses `slug -- reason` format, backward compat
- [ ] `--reason` required on `--blocked-by` for `ta new`
- [ ] `ta add-dep` / `ta remove-dep` CLI commands
- [ ] MCP `create_task` / `add_dependency` with required `reason`
- [ ] `ta tree` displays reason in dependency annotations
- [ ] Backward compat: old files without ` -- ` get empty reason, no crash
- [ ] All existing tests pass
