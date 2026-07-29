---
name: mission-workflow
description: >
  Default multi-session workflow for task-agent: prefer the mission queue over
  host built-in todos, pick next work, implement, complete with criteria, and
  keep hierarchy (subtask_of) and blockers (blocked_by) honest. Use at session
  start, when planning work, when the user mentions tasks/queue/mission, or
  whenever prioritizing engineering work in a task-agent project.
---

# Mission workflow (task-agent)

**task-agent** is the durable task system for this project. Host todos (Claude /
Copilot / Grok / agy session lists) are ephemeral — use them only for
within-turn scratch, not for multi-session priorities.

## When to use

- Start of a coding session in a repo that uses task-agent
- User talks about priorities, backlog, “the queue,” or “mission”
- Before large work: ensure there is a tracked task
- After finishing work: close the queue item properly

## Core rules

1. **Mission queue is source of truth** — status lives in task-agent (pending / draft / active / completed), not only in chat memory.
2. **Prefer MCP tools** for list/create/update/complete; use `ta` CLI when MCP is unavailable.
3. **One clear active focus** — don’t start unrelated actives without intent.
4. **Respect graph edges**
   - `subtask_of` = hierarchy (nesting / parent epic)
   - `blocked_by` = ordering constraints (do not start until blockers complete)
5. **Completion requires criteria** — see **complete-task** skill; always leave a solution note.
6. **Decompose, don’t balloon** — large work becomes nested subtasks with criteria and LOE when useful.

## Session loop

```text
orient (strategy + active + next)
  → implement on one task
  → verify criteria
  → complete_task / ta done (+ metrics if known)
  → pick next or stop
```

### Orient

- `get_strategy` — project constraints
- `list_active_tasks` / `list_tasks` — what is in flight
- If idle: pick next unblocked pending ( **next-task** skill )

### Create work

- `create_task` / `create_tasks` with **completion_criteria**
- Nest with `subtask_of`; order with `blocked_by`
- Use `draft=true` when the idea is not ready to schedule

### Implement

- Keep changes scoped to the active task’s criteria
- Attach investigation notes with `add_task_document` when findings should live with the task

### Complete

- Follow **complete-task** skill
- Report model/tokens/harness when available (cost optimization)

## Anti-patterns

| Avoid | Prefer |
|-------|--------|
| Host-only todo for multi-hour work | `create_task` + active |
| Completing without criteria | Fix criteria or keep active |
| Ignoring `blocked_by` | Work blockers first |
| Orphan chat plans | Task body + secondary docs |
| Silent abandon of active tasks | Complete, demote, or document blocker |

## Related skills

- **next-task** — select and start work
- **complete-task** — close work with solution + metrics

## Install

See [skills/README.md](../README.md) for Claude Code, Antigravity, and other hosts.
