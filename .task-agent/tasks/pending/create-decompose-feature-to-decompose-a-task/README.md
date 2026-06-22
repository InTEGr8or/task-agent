---
created_at: 2026-06-22T12:56:33.548234-07:00
---

# Create decompose feature to decompose a task

The MCP should have a command to decompose a task.

The result, for the MCP, should be to instruct the agent how to create a subtask from each of the subcomponents of the passed-in task. The comand should accept a task slug, or, if there is only one active task, or only one pending task, it should assume that as a default.

The `decompose` task should pass back verbiage about the steps to create the new tasks first and make them dependencies of the current task, and that each subtask must include enough context to be handled by an independant other agent, including instructions to include a completion criteria.

The `ta decompose {slug}` should create a subagent to decompose the task.
