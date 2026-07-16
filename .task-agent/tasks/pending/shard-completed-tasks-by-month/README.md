---
created_at: 2026-06-21T09:52:43.561674-07:00
---

# shard-completed-tasks-by-month

Shard the completed/ directory by month (completed/YYYY/MM/) to avoid folder
bloat. This is the directory-move-only portion of the original ticket; the
WAL-backed history index has been split into
completed-items-index-with-wal-for-fast-history-lookup.

## Why now

97 completed tasks sit flat in completed/2026/ today. The upcoming station
inspector (build-station-inspector-cli-borrowing-burr-telemetry-ux) renders
per-station counts and oldest-item age; month-sharding lets the inspector stop
recursing at the month level instead of scanning every completed file.

## Scope

1. ta done (and the underlying complete_issue) moves completed tasks to
   completed/YYYY/MM/ instead of completed/YYYY/.
2. A one-time migration walks existing completed/YYYY/ trees and relocates
   each task to completed/YYYY/MM/ based on its created_at (or completion
   commit date if created_at is absent).
3. find_issue_file (and any other code that searches completed/) is updated
   to recurse into month subdirectories.
4. Extend ingest_issues()._migrate_file_headers to walk completed/ so that
   legacy Depends-on lines in historical records across the ~5-10 external
   repos are migrated to Blocked-by on the next ta ingest. This closes
   the historical-migration hole cleanly and keeps the inspector's display
   consistent.

## Constraints

- The WAL/index portion is deferred to
  completed-items-index-with-wal-for-fast-history-lookup.
- Migration is safe and idempotent: re-running it should be a no-op.
- No new persistent state (just directory moves).

## Completion Criteria

1. Completed tasks are moved to completed/YYYY/MM/.
2. Existing flat completed/YYYY/ trees are migrated on first ta ingest
   after upgrade.
3. ingest_issues() walks completed/ and runs _migrate_file_headers over
   historical files.
4. find_issue_file and related searches recurse into month subdirectories.
5. All existing unit tests continue to pass.