# Enhance ta start to trigger sidecar

**Depends on:** implement-merge-request-queue

Modify 'ta start' to optionally invoke 'ta run' after setting up the git worktree. This allows for immediate autonomous execution after environment setup.

## Solution

Added --run flag to 'ta start' to immediately trigger sidecar execution.

---
**Completed in commit:** `164fdf8`
