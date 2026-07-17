---
created_at: 2026-06-14T10:03:52-07:00
blocked_by: agent-sandboxing-via-linux-accounts
---

## Phase 3 — Per-task agent isolation

---

### Objective

`ta start <slug> --agent <template>` creates a dedicated agent user for that
specific task, rather than reusing a shared agent.

```
ta start my-task --agent uat-aws
  → Creates agent-mytask-{hash} user
  → Applies uat-aws template
  → Sets up worktree permissions
  → ta run my-task --agent uses the dedicated user
```

### Key design

- Agent user name incorporates a short hash of the task slug + template name to
  avoid collisions: `agent-{task-slug}-{hash8}`
- `ta destroy-agent` is called implicitly when `ta done` completes the task
- Agent user is created with `--no-create-home` and home is set to worktree
  (avoiding home directory proliferation)
- SSH key is optional per-task; generated if template specifies it

### Completion criteria

1. `ta start <slug> --agent <template>` creates a unique agent user
2. `ta done` destroys the per-task agent user
3. No home directory proliferation — agent uses worktree as home
4. Unit tests for per-task user creation and cleanup
5. E2e test covers: start → run → done → user removed

---
**Completed in commit:** `<pending-commit-id>`
