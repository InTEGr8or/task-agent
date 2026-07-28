---
name: next-task
description: >
  Pick and start work from the task-agent mission queue. Use when the user asks
  what to do next, for the top priority task, to start a task, list the queue,
  show active work, or choose among pending tasks. Prefer task-agent MCP/CLI over
  host built-in todos for multi-session work.
---

# Next task (task-agent)

Use the **task-agent** mission queue as the source of truth for *what to work on*.

## When to use

- “What should I work on?” / “What’s next?”
- “List tasks” / “Show the queue” / “What’s active?”
- Starting implementation on a named or top pending task
- Session start: establish current active work and the top of the backlog

## When not to use

- Pure chat / questions that do not change or consume queue work
- Creating a brand-new idea with no intent to track it (optional: still create a draft)

## Prerequisites

- Task-agent MCP server connected (`task_agent` / `task-agent`), **or** shell access to `ta`
- Prefer MCP tools when available; fall back to CLI

## Steps

1. **Orient**
   - MCP: `list_active_tasks` (or `list_tasks`) and/or strategy via `get_strategy`
   - CLI: `ta list` / `ta active`
2. **If something is already active**
   - Prefer finishing or explicitly switching — do not silently start a second active task
   - Load details: `get_task_details` / `ta show <slug>`
3. **If nothing active — pick next**
   - MCP: highest-priority unblocked pending work from `list_tasks` (respect `blocked_by` / nesting)
   - CLI: `ta next`
   - Skip tasks blocked by incomplete dependencies
4. **Understand the task**
   - Read completion criteria and body (`get_task_details`, secondary docs via `list_task_documents` / `get_task_details`)
   - Note `subtask_of` and `blocked_by`
5. **Start when ready to implement**
   - Mark active: MCP `mark_task_active` or CLI `ta start <slug>` / `ta active <slug>` (use project conventions for worktrees)
6. **Do not** invent a parallel host-only todo list for the same work

## Tool map (typical MCP names)

| Intent | Prefer |
|--------|--------|
| Full queue | `list_tasks` |
| Active only | `list_active_tasks` |
| Top / next | `list_tasks` + priority order, or CLI `ta next` |
| Details | `get_task_details` |
| Strategy | `get_strategy` |
| Start | `mark_task_active` |

Exact tool names may vary slightly by MCP build; use the connected server’s schema.

## Done with this skill

You have a single clear task slug, its criteria, and (if implementing) it is **active**.
Continue implementation; close work with the **complete-task** skill.
