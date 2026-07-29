# Task Agent Rule for Antigravity

When managing tasks, planning work, or completing issues:
- Prefer using the **task-agent** MCP server tools (`list_tasks`, `mark_task_active`, `complete_task`, `create_task`) as your primary durable task queue.
- Check active and pending tasks at session start.
- Do not rely solely on host ephemeral todos for multi-session work.
