---
created_at: 2026-06-21T09:52:43.561974-07:00
---

# shard-completed-tasks-by-month-and-index-history

Shard the completed/ directory by month (completed/YYYY/MM/) to avoid folder bloat. Maintain a completed items index or write-ahead log (such as completed.usv) to speed up history lookup without git conflict issues (e.g. by sorting before prepending or using a write-ahead log structure).

## Completion Criteria

1. Completed tasks are moved to completed/YYYY/MM/. 2. A fast history lookup mechanism is implemented (either index file/write-ahead log or Git log lookup). 3. All existing unit tests continue to pass.
