---
created_at: 2026-07-17T00:00:00-07:00
subtask_of: station-map-conformance-migration
---

# Regression: fix dependency model — subtask_of implies blocking, remove redundant blocked_by, fix tree rendering

**Subtask of:** station-map-conformance-migration

## What we got wrong

### Origin: the refactor-dependencies commit (ca4546c, 2026-07-11)

The original refactor-dependencies-relation-into-blocked-by-and-subtask-of task
split the flat dependencies list into blocked_by (ordering) and subtask_of
(hierarchy) "to prevent reversed/confusing semantics." But the refactor only
split the DATA MODEL — it did not update the CONSUMERS of the old combined
dependencies property. Three consumers were left using the conflated view:

### Mistake 1: Tree renderer never updated (the rendering bug)

cmd_tree (cli.py:1811) was written BEFORE the split, when issue.dependencies
was a single flat list. The refactor commit added subtask_of and blocked_by as
LABELS in the output but left the NESTING LOGIC using issue.dependencies — the
property that combines both edge types into one list.

The children_map is built by iterating issue.dependencies, so a task gets
visually nested under ANY task it points to — whether that is a subtask_of
(hierarchy) or a blocked_by (external dependency). This makes blocked_by
targets look like parents.

Evidence: git show ca4546c^:src/taskagent/cli.py shows the pre-refactor
cmd_tree using i.dependencies for children_map. The refactor commit adds labels
but does not change children_map. The bug has been present since the split.

### Mistake 2: Promote/demote cascade conflates edge types

The refactor commit changed promote_issue and demote_issue to use:
  if (i.subtask_of == target.slug or target.slug in i.blocked_by)

This treats both hierarchy children AND external dependents as children for
cascade purposes. A task that is merely blocked_by the target (an external
dependency, not a subtask) gets promoted/demoted when the target is
promoted/demoted. This is wrong — cascading should follow hierarchy only
(subtask_of).

Evidence: git show ca4546c shows the change from target.slug in
i.dependencies to the conflated (i.subtask_of == target.slug or
target.slug in i.blocked_by). Still present at manager.py:768 and
manager.py:806.

### Mistake 3: Redundant blocked_by edges on epics

When creating the station-map epic and its children, we explicitly listed all
children in the epic's blocked_by field. This is redundant. The subtask_of
edges already establish that children block their parent. complete_issue
already enforces this (raises ValueError on open subtasks). The explicit
blocked_by entries duplicate the derived blocking relationship.

Rule: blocked_by is for non-hierarchical ordering only. A task should NEVER
have its own child in its blocked_by list. The blocking of a parent by its
children is DERIVED from subtask_of, not stored redundantly.

### Mistake 4: Completed blockers still displayed as active

When a task in blocked_by is completed, it is still shown in the tree as a
blocking dependency. build-station-inspector still shows blocked by
shard-completed-tasks-by-month even though that task is done.

The stored data can keep the edge (it is historical), but the rendering should
filter out completed blockers.

## The correct model

- subtask_of = hierarchy membership. Child belongs to parent. Implies blocking
  — parent cannot complete until all children are done. This blocking is
  DERIVED from the hierarchy, not stored as a separate blocked_by edge.
- blocked_by = non-hierarchical ordering only. Task B cannot start until task C
  is done, where C is NOT a subtask of B's epic. External dependency.
- A parent never blocks a child. The child proceeds independently.
- A child always blocks its parent. This is automatic from subtask_of.
- An epic's blocked_by list should only contain external prerequisites (tasks
  that are NOT its children). If the only blockers are children, the list
  should be empty.
- Cascading (promote/demote) follows subtask_of only, never blocked_by.

## Why this happened (root cause)

The refactor split the data model but treated dependencies as a
backward-compatible property that combines both edges. Every consumer that used
dependencies — the tree renderer, the promote/demote cascade, the cycle checker
— silently inherited the conflation. The refactor task's completion criteria
was "test suite fully green" but no test verified that the two edge types were
treated differently by consumers. The tests only verified the data model split.

The Jira insight: issue tracking systems like Jira distinguish between subtask
(hierarchy — a Jira subtask belongs to a parent issue and blocks it) and linked
issue / blocks (ordering — issue A blocks issue B, no hierarchy). task-agent's
subtask_of maps to Jira's subtask; blocked_by maps to Jira's is-blocked-by
link. The two are semantically different and must not be conflated in rendering
or cascading. This was the original motivation for the split, but the split was
incomplete.

## Data migration

This is the SECOND edge-field migration in one week (first was prose to
frontmatter). This one removes redundant blocked_by entries from epics.

### Migration approach

Extend ingest_issues to detect and clean redundant blocked_by entries:

1. Load all issues from mission.usv
2. For each issue, check if any entry in its blocked_by list is also a task
   that has subtask_of pointing back at this issue
3. If so, remove that entry from blocked_by (redundant — hierarchy already
   establishes the blocking)
4. Write the cleaned blocked_by back to frontmatter and USV
5. Idempotent: if blocked_by is already clean, no change

### Do we need a schema version?

The refactor task mentioned schema version 2 (V2) but no schema version field
was actually implemented — the USV format just gained a 4th column. No version
marker exists in the data.

A schema version is NOT needed yet. The migration is trivially detectable
(does an epic have children in its blocked_by list?). The detection-based
approach used for all prior migrations works fine. If we later add frequent
schema changes, we can add a schema_version field to frontmatter at that time.

## Code changes required

1. cmd_tree (cli.py:1811): rebuild children_map using ONLY subtask_of edges.
   Display blocked_by as a label on the node, never as nesting. Filter
   completed blockers from the label.
2. cmd_list (cli.py:1906): same fix as cmd_tree — nest by subtask_of only.
3. promote_issue (manager.py:768): change cascade to use
   i.subtask_of == target.slug only, remove the or target.slug in
   i.blocked_by condition.
4. demote_issue (manager.py:806): same fix — subtask_of only.
5. ingest_issues: add a pass that removes redundant blocked_by entries (child
   slugs that are also subtask_of this issue).
6. Tree/list display: filter blocked_by to exclude completed tasks when
   rendering.
7. complete_issue: already correct — checks subtask_of == slug for open
   subtasks. No change needed.
8. _check_dependency_cycle: currently uses i.dependencies (combined). Should
   use blocked_by + subtask_of separately — but the combined check is
   conservative (will not miss cycles). Leave as-is for now; not a correctness
   issue.

## Tests required

1. Epic with children in blocked_by -> migration removes them, subtask_of
   edges remain
2. Epic with external (non-child) blocked_by -> migration preserves them
3. Tree rendering: child appears under subtask_of parent, not under
   blocked_by target
4. Tree rendering: completed blockers not shown as active
5. Promote cascade: only subtask_of children are cascaded, not blocked_by
   dependents
6. Demote cascade: same
7. complete_issue still blocks on open subtasks (regression test — already
   covered)

## Completion Criteria

1. No epic has its own children in its blocked_by list (migrated)
2. Tree and list renderers nest by subtask_of only, display blocked_by as
   labels
3. Completed blockers not shown as active in tree or list
4. Promote/demote cascades follow subtask_of only
5. Migration is idempotent and runs on ta ingest
6. All existing tests pass
7. New tests cover all six scenarios above
