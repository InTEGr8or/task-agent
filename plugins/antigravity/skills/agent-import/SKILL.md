---
name: agent-import
description: >
  Import session tasks and todo items from external AI agent task runners
  (Antigravity CLI, Claude Code, generic task lists) into task-agent as working-task
  documents. Use when the user asks to import tasks, sync agent session state, or
  preserve ephemeral session todos into task-agent.
---

# Agent Import (task-agent)

Import tasks from agent-native task runners (such as Antigravity CLI TaskManager, Claude Code Todo/Task state, or generic task lists) directly into `task-agent`.

## When to use

- User asks to import agent tasks or sync session todo lists
- Preserving ephemeral agent session todos into durable `task-agent` storage
- Session start: bringing external agent session tasks into the current `working-task`

## When not to use

- Manually adding a single new task — use `create_task` / `ta new` instead
- Completing a task — use `complete_task` / `ta done` instead

## Prerequisites

- `task-agent` MCP server connected, or shell access to `ta` CLI
- An active `working-task` set (or pass explicit `--slug <slug>`)

## Steps

1. **Identify working-task**
   - MCP: `list_active_tasks` or specify `slug`
   - CLI: `ta active`
2. **Execute Agent Import**
   - MCP: `import_agent_tasks(slug=..., agent_type="...")`
   - CLI: `ta agent import [--slug <slug>] [--agent <type>] [--file <path>]`
3. **Verify document creation**
   - Check created `imports/{agent}_tasks.json` in working-task directory.

## Tool map

| Intent | Prefer |
|--------|--------|
| Import agent tasks | `import_agent_tasks` / `ta agent import` |
| Targeted import | `import_agent_tasks(slug="my-slug")` |
| Custom file import | `ta agent import --file <path>` |
