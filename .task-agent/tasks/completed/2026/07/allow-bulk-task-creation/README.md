---
created_at: 2026-07-14T10:05:52.264389-07:00
---

# Allow bulk task creation

A bulk-create feature would be a massive
  efficiency booster for agent workflows.

  When agents transition from a planning/design phase (like analyzing a matrix) to
  execution, they frequently need to "fan out" into 10–20 independent tickets.

  ### Why a Bulk API is Better:

  1. Single Tool Call Payload: Instead of writing a Python script or making 18
  sequential tool calls, the agent could emit a single JSON array of task
  definitions directly to the MCP tool:
    {
      "tasks": [
        {"title": "Extract view.py", "depends_on": "...", "body": "..."},
        {"title": "Extract data.py", "depends_on": "...", "body": "..."}
      ]
    }

  2. Atomic Writes: The MCP server can write all these files to the filesystem in
  a single synchronous pass on the host, ensuring the task database remains
  consistent.
  3. No Script Sandbox Overhead: It removes the need for the agent to write and
  execute untrusted helper scripts, which could be blocked by restrictive sandbox
  permissions in some developer environments.

  ### Design Options:

  • Option A: Polymorphic  create_task : Update the schema of the existing
  create_task  tool to accept either a single task object or an array of task
  objects.                                                                          ▄
  • Option B: Dedicated  create_tasks  (Plural): Add a dedicated bulk endpoint to   ▀
  keep the schema simple and self-documenting.

## Solution

Implemented dedicated create_tasks MCP tool taking a list of task dictionaries, and updated ta new CLI subcommand with --bulk to read JSON task list from a file or stdin.

---
**Completed in commit:** `5255c40`
