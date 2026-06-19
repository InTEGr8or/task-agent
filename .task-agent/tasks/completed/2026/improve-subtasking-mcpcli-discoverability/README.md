---
created_at: 2026-06-14 10:03
---

# Improve subtasking MCP/CLI discoverability

The dependency-based subtasking system (via pipe-delimited deps in mission.usv) is powerful but not obvious. Improve discoverability by:

1. Add usage examples to MCP tool docstrings (create_task, list_tasks, etc.) showing dependency syntax
2. Add 'ta help subtasks' or include subtask examples in 'ta --help'
3. Consider a 'ta tree' command that visualizes the full dependency DAG
4. Document in --help output that dependencies create parent-child relationships shown with └─ indentation

---
**Completed in commit:** `<pending-commit-id>`
