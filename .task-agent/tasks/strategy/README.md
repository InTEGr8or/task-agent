---
created_at: 2026-06-18T18:25:56-07:00
---

# Strategy

Build `task-agent` into a self-contained, production-grade task lifecycle manager
that enables both human developers and autonomous AI agents to collaboratively
execute prioritized work through a git-native, filesystem-as-database architecture.

## Current Focus:

- Harden the `start → work → done` lifecycle with proper cleanup and isolation
- Make MCP tools reliable enough for agents to self-manage task dependencies
- Establish CLI-based agent workflows (`agy-cli`, `claude`, `opencode`) as first-class sidecar workers

## Guiding Constraints:

- Keep the mission queue (USV) as the single source of truth for priority ordering
- Every feature should work for both human CLI users and MCP-connected agents
- Prefer convention over configuration; minimize required setup steps
