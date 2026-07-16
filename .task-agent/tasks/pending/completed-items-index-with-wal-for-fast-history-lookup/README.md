---
created_at: 2026-07-16T15:37:58.773967-07:00
---

# Completed items index with WAL for fast history lookup

**Blocked by:** shard-completed-tasks-by-month

Split from `shard-completed-tasks-by-month-and-index-history`.

The directory sharding (`completed/YYYY/MM/`) is handled by the parent task; this task covers only the **index + WAL** portion: a persistent structure for fast history lookup without git conflict issues.

## Design notes

- The WAL handles distributed updates: agents completing tasks in separate worktrees append WAL entries; compaction folds them into the main index.
- Compaction is a separate operation (triggered manually or on a schedule) that folds WAL entries into the primary index.
- Must coexist with the month-sharded directory layout from `shard-completed-tasks-by-month`.

## Blocked by

- `shard-completed-tasks-by-month` (month-sharded directory layout must exist first so the index can key on the new paths)

## Completion Criteria

A completed-items index backed by a write-ahead log (WAL) provides O(1) history lookups. WAL entries are compacted into the main index on a configurable schedule. Distributed writes (concurrent agents completing tasks in different worktrees) do not conflict. All existing unit tests continue to pass.
