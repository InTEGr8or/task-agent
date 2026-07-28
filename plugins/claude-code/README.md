# Task Agent Claude Code Plugin

A loadable [Claude Code](https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/overview) plugin package for **task-agent**.

This plugin packages:
- **MCP Server Configuration** (`.mcp.json`) spawning `ta mcp`
- **SessionStart Hook** (`hooks/session_start.sh`) injecting current active task and backlog status at session start
- **Statusline Helper Script** (`scripts/statusline.sh`) for custom TUI status display
- **Portable Agent Skills** (`skills/next-task`, `skills/complete-task`, `skills/mission-workflow`)

---

## Installation

### Local Install (Developer / Monorepo)

From within your project or after cloning `task-agent`:

```bash
# In Claude Code chat / CLI:
/plugin install /path/to/task-agent/plugins/claude-code
```

Or copy/symlink to user plugins directory:

```bash
mkdir -p ~/.claude/plugins
cp -a plugins/claude-code ~/.claude/plugins/task-agent
```

### Verification

1. Start a new Claude Code session. The `SessionStart` hook will execute and display the `task-agent` status block.
2. Run `/plugin list` in Claude Code to verify `task-agent` plugin is enabled.
3. Test tool availability via MCP (e.g. `list_tasks`, `mark_task_active`, `complete_task`).

---

## Plugin Layout

```text
plugins/claude-code/
├── .claude-plugin/
│   └── plugin.json           # Plugin metadata manifest
├── .mcp.json                 # MCP server auto-launch config
├── hooks/
│   ├── hooks.json            # Hook event triggers (SessionStart)
│   └── session_start.sh      # Queue status context injector
├── scripts/
│   └── statusline.sh         # Helper script for status line status
└── skills/
    ├── next-task/SKILL.md    # Pick/start task skill
    ├── complete-task/SKILL.md # Complete task with criteria & solution skill
    └── mission-workflow/SKILL.md # Durable queue workflow skill
```
