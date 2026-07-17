---
created_at: 2026-07-15T20:18:05.921967-07:00
subtask_of: station-map-conformance-migration
---

# Complete blocked_by vs subtask_of edge-type migration

Conformance gap 5 from STATION-MAP.md: edge-type conflation cleanup.

## Completion Criteria

All stored prose lines, MCP/CLI docstrings, and completed/ historical records use the correct separated edge types (blocked_by for ordering, subtask_of for hierarchy) with no legacy depends_on references remaining

## Solution

Removed all legacy depends_on references from source code, MCP/CLI docstrings, tests, and completed task files. All edge types now use blocked_by for ordering and subtask_of for hierarchy exclusively.

---
**Completed in commit:** `d007f19`
