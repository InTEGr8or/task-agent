---
name: complete-task
description: >
  Close task-agent work correctly when implementation is finished. Use when the
  user says a task is done, asks to complete/close/finish a task, or after
  acceptance criteria are met. Prefer complete_task / ta done over deleting
  files or only checking off host todos. Include solution notes and optional
  cost metrics (model, tokens, harness).
---

# Complete task (task-agent)

Mark mission-queue work **completed** only when the task’s completion criteria
are actually satisfied.

## When to use

- Implementation finished and verified (tests/lint as required by the task)
- User asks to complete, close, finish, or `ta done` a task
- End of a focused session where the active task is done

## When not to use

- Work is partial — leave **active** or demote; optionally document progress on the task
- Criteria unmet — do not complete “to clean the queue”
- Wrong slug — resolve the correct task first (`search_task` / `list_tasks`)

## Prerequisites

- Task-agent MCP or `ta` CLI
- You know the task **slug** (or unique title fragment)

## Steps

1. **Confirm criteria**
   - Re-read completion criteria via `get_task_details` / task README
   - Verify checklist items (tests, docs, flags) for real
2. **Write a solution summary**
   - What changed, where, how to verify
   - Honest about leftover risk
3. **Complete via task-agent (required)**
   - MCP: `complete_task` with `name` + `solution` (and optional commit `message`)
   - CLI: `ta done <slug>` (with project flags as needed)
4. **Self-report cost metrics when known** (cost optimization)
   - Model name / version, provider
   - Agent harness (e.g. `claude-code`, `antigravity`, `grok`, `opencode`)
   - Input/output tokens and whether **measured** or **estimated**
   - Duration seconds if available
   - MCP `complete_task` optional fields or `ta done --model … --input-tokens …` etc.
5. **Do not**
   - Only tick a host session todo and leave the mission task open
   - Delete the task file by hand
   - Complete parent epics while required subtasks remain open (unless criteria say otherwise)

## Tool map

| Intent | Prefer |
|--------|--------|
| Finish task | `complete_task` / `ta done` |
| Still blocked / wrong state | leave active; `update_task` / docs; or demote |
| Metrics | optional fields on `complete_task` / `ta done` |

## Done with this skill

The task is in **completed/** (or equivalent), with a clear solution note, and the
mission queue no longer lists it as active/pending.
