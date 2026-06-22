---
created_at: 2026-06-21T09:52:43.561974-07:00
---

# shard-completed-tasks-by-month-and-index-history

Shard the completed/ directory by month (completed/YYYY/MM/) to avoid folder bloat. Maintain a completed items index with a write-ahead log (WAL) that is compacted to the index to handle distributed updates and speed up history lookup without git conflict issues.

## Completion Criteria

1. Completed tasks are moved to completed/YYYY/MM/.
2. Implement a completed items index and a write-ahead log (WAL) structure to handle distributed updates.
3. Implement a compaction mechanism to compact the WAL into the main index.
4. All existing unit tests continue to pass.

