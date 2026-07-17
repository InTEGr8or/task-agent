---
created_at: 2026-07-17T10:34:48.929928-07:00
subtask_of: station-map-conformance-migration
---

# Regression: fix dependency model — subtask_of implies blocking, remove redundant blocked_by on epics, fix tree rendering

## What we got wrong

During the station-map conformance migration, we built a dependency model with two edge types (`blocked_by` for ordering, `subtask_of` for hierarchy) but made three mistakes:

### Mistake 1: Redundant `blocked_by` edges on epics

We explicitly listed all children in the epic's `blocked_by` field:

```
station-map-conformance-migration  blocked_by: add-ta-rename, build-station-inspector, declare-and-enforce, ...
```

This is redundant. The `subtask_of` edges already establish that children block their parent. `complete_issue` already enforces this (raises ValueError on open subtasks). The explicit `blocked_by` entries duplicate the derived blocking relationship and must be removed from both the USV index and the frontmatter of epic task files.

**Rule:** `blocked_by` is for non-hierarchical ordering only. A task should NEVER have its own child in its `blocked_by` list. The blocking of a parent by its children is derived from `subtask_of`, not stored redundantly.

### Mistake 2: Tree renderer conflates hierarchy with dependency

`cmd_tree` (`cli.py:1811`) and `cmd_list` (`cli.py:1906`) build `children_map` by iterating `issue.dependencies` — a property that combines `blocked_by` AND `subtask_of` into one flat list. The renderer nests tasks under anything that points to them, regardless of edge type.

This causes:
- Tasks with `blocked_by` on a non-parent task get visually nested under that task, making it look like a parent-child relationship when it's actually an external dependency
- `automate-task-store-commits` (subtask of station-map, blocked by declare-and-enforce) appears nested under `declare-and-enforce` instead of under the station-map epic
- `build-station-inspector` (subtask of station-map, blocked by shard-completed) appears nested under `shard-completed` instead of under the epic

**Fix:** The tree renderer must use `subtask_of` for visual nesting (hierarchy) and display `blocked_by` only as a label on the node, never as nesting. A task's visual parent is its `subtask_of` target, never its `blocked_by` target.

### Mistake 3: Completed blockers still displayed as active

When a task in `blocked_by` is completed, it's still shown in the tree as a blocking dependency. `build-station-inspector` still shows `blocked by: shard-completed-tasks-by-month` even though that task is done.

**Fix:** The tree renderer and `ta list` must filter `blocked_by` to only show non-completed blockers. This is a display concern — the stored data can keep the edge (it's historical), but the rendering should not show completed tasks as active blockers.

## The correct model

- **`subtask_of`** = hierarchy membership. Child belongs to parent. Implies blocking (parent cannot complete until all children are done). This blocking is **derived**, not stored.
- **`blocked_by`** = non-hierarchical ordering only. Task B cannot start until task C is done, where C is NOT a subtask of B's epic. External dependency.
- **A parent never blocks a child.** The child proceeds independently.
- **A child always blocks its parent.** This is automatic from `subtask_of`.
- **An epic's `blocked_by` list** should only contain external prerequisites (tasks that are NOT its children). If the only blockers are children, the list should be empty.

## Data migration

This is the SECOND edge-field migration in one week. The first was prose → frontmatter. This one removes redundant `blocked_by` entries.

### Migration approach

Extend `ingest_issues()` to detect and clean redundant `blocked_by` entries:

1. Load all issues from mission.usv
2. For each issue, check if any entry in its `blocked_by` list is also a task that has `subtask_of` pointing back at this issue
3. If so, remove that entry from `blocked_by` (it's redundant — the hierarchy already establishes the blocking)
4. Write the cleaned `blocked_by` back to frontmatter and USV
5. Idempotent: if `blocked_by` is already clean, no change

### Do we need a schema version?

No. The migration is a one-time cleanup that's trivially detectable (does an epic have children in its `blocked_by` list?). A schema version field would add complexity to the USV format and Issue model for marginal benefit. The detection-based approach we've used for all prior migrations (prose rename, frontmatter move, month-sharding) works fine and is already proven across 5-10 external repos.

If we later find ourselves doing frequent schema migrations, we can add a `schema_version` field to frontmatter at that time. For now, it's premature.

## Code changes required

1. **`extract_relations`** / **`load_mission`**: no change — read what's stored
2. **`save_mission`**: no change to USV format
3. **`ingest_issues`**: add a pass that removes redundant `blocked_by` entries (child slugs that are also in `blocked_by`)
4. **`cmd_tree`** (`cli.py:1811`): rebuild `children_map` using ONLY `subtask_of` edges, not `issue.dependencies`. Display `blocked_by` as a label, never as nesting.
5. **`cmd_list`** (`cli.py:1906`): same fix as `cmd_tree`
6. **`complete_issue`**: already correct — checks `subtask_of == slug` for open subtasks, no change needed
7. **Tree display**: filter `blocked_by` to exclude completed tasks when rendering

## Tests required

1. Epic with children in `blocked_by` → migration removes them, `subtask_of` edges remain
2. Epic with external (non-child) `blocked_by` → migration preserves them
3. Tree rendering: child appears under `subtask_of` parent, not under `blocked_by` target
4. Tree rendering: completed blockers not shown as active
5. `complete_issue` still blocks on open subtasks (regression test — already covered)

## Completion Criteria

1. No epic has its own children in its `blocked_by` list (migrated)
2. Tree renderer nests by `subtask_of` only, displays `blocked_by` as labels
3. Completed blockers not shown as active in tree or list
4. Migration is idempotent and runs on `ta ingest`
5. All existing tests pass
6. New tests cover all four scenarios above

## Completion Criteria

No epic has its own children in its blocked_by list (migrated). Tree renderer nests by subtask_of only, displays blocked_by as labels. Completed blockers not shown as active in tree or list. Migration is idempotent and runs on ta ingest. All existing tests pass. New tests cover: redundant blocked_by removal, external blocked_by preservation, tree nesting by subtask_of, completed blocker filtering.
