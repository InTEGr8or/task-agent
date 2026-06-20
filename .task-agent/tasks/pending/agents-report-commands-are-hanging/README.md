---
created_at: 2026-06-19T11:10:33.219725-07:00
---

# Agents report commands are hanging

I am getting reports like this:

> It looks like the tool use was rejected rather than hanging. This is similar to the earlier issue we had where task-agent's auto-commit failed because the working tree was already clean (we had committed manually).

How can we improve the reliability of the command that might involve git commits on repos that might have commit hooks?
