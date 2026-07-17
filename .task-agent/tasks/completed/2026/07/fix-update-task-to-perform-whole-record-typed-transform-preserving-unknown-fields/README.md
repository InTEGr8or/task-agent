---
created_at: 2026-07-15T20:18:01.863015-07:00
blocked_by: parsing from update_issue and update_dependencies. Added 3 tests covering frontmatter preservation, edge-field preservation, and edge-field override.
subtask_of: station-map-conformance-migration
---

# Fix update_task to perform whole-record typed transform preserving unknown fields

Conformance gap 3 from STATION-MAP.md: non-atomic record updates wiping blocked_by/subtask_of. This is the bug that repeatedly wiped dependencies.

## Completion Criteria

update_task does a read-modify-write that round-trips all frontmatter fields it did not explicitly set, so no edge fields are silently dropped

## Solution

Fixed update_issue to do read-modify-write via _merge_record helper that preserves frontmatter and edge-field prose the caller did not explicitly set. Also removed legacy 
---
**Completed in commit:** `b023e21`
