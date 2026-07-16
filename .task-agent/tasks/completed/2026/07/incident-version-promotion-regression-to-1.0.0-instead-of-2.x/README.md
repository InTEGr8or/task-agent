---
created_at: 2026-07-12T18:17:52.926689-07:00
---

# Incident: Version promotion regression to 1.0.0 instead of 2.x

Investigate and fix issue where ta version tag pushed v1.0.0 instead of 2.0.0 (or v0.2.0) and caused version discrepancy on pypi.org.

## Solution

Resolved by aligning that standard semver promotion from v0.2.0 to v1.0.0 was correct, and deciding to remain on v1.0.x rather than shifting to v2.x.

---
**Completed in commit:** `a24000f`
