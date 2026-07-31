---
name: next
description: >
  Get the next item from the task-agent MCP mission queue and start working on it.
---

# Next Task (/next)

Fetch the top unblocked pending item from the **task-agent** mission queue, mark it active, and retrieve its details to start work immediately.

## Workflow

1. **Check Existing Active Work**:
   - Call MCP tool `list_active_tasks` (or run `ta active`).
   - If a task is already active, fetch its context with `get_task_details` and present it to the user.

2. **Discover Next Task**:
   - If no active task exists, call MCP tool `list_tasks` (or run `ta next`).
   - Select the highest-priority, unblocked pending task in the queue.

3. **Start Task**:
   - Call MCP tool `mark_task_active` with the selected task slug (or run `ta active <slug>`).
   - Call MCP tool `get_task_details` for the task to load its full requirements, completion criteria, and secondary documents.

4. **Execute**:
   - Summarize the activated task for the user and begin implementation immediately.
