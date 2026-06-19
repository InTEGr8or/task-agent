---
created_at: 2026-06-18T18:25:56-07:00
---

# Allow editing task dependencies in task-agent CLI and MCP

Agents currently cannot easily update task dependencies once they are set. We need to implement editing capabilities in the CLI (e.g., an update command or flags on existing commands) and ensure the MCP server supports modifying the depends_on field safely (with cycle and task existence checks).

## Completion Criteria

1. Implement command/options in the CLI to update task dependencies (e.g., `ta update <slug> --depends-on <deps>` or similar).
2. Ensure the MCP server's `update_task` tool supports updating dependencies.
3. Validate that dependency target tasks exist and check for cycle detection to prevent dependency loops.
4. Update the task markdown files (the 'Depends on:' metadata block) and mission.usv when dependencies change.
5. Write unit tests covering dependency updates, invalid targets, and cycle detection.

## Solution

Implemented update command in CLI and update_task_dependencies tool in MCP server with cycle detection and validation checks.

---
**Completed in commit:** `ed17a7d`
