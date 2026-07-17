---
created_at: 2026-03-22T13:51:44-07:00
blocked_by: implement-merge-request-queue
---

# Enhance ta start to trigger sidecar

Modify 'ta start' to optionally invoke 'ta run' after setting up the git worktree. This allows for immediate autonomous execution after environment setup.

## Solution

Added --run flag to 'ta start' to immediately trigger sidecar execution.

---
**Completed in commit:** `164fdf8`
