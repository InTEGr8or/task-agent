---
created_at: 2026-07-11T13:25:56.517496-07:00
---

# Refactor dependencies relation into blocked-by and subtask-of

Split the historical depends-on relation into blocked-by (ordering) and subtask-of (hierarchy) to prevent reversed/confusing semantics and support clean parenting and cycle checks.

## Completion Criteria

Implementation completed, test suite fully green, and changes committed.

## Solution

Designed and implemented schema version 2 (V2) to split legacy depends-on relationships into blocked-by (for sequential ordering constraints) and subtask-of (for parent-child task hierarchy). Fully preserved backward compatibility with automated parsing of V1 USV columns and bidirectional file parser that accepts Depends on, Blocked by, and Subtask of markdown headers. Also introduced a safety check to refuse completing any task with active/open subtasks.

---
**Completed in commit:** `086ca6f`
