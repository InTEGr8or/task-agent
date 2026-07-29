# task-agent Antigravity Plugin

Antigravity CLI (`agy`) plugin package for `task-agent`.

## Components Included

- **Manifest**: `.gemini-plugin/plugin.json`
- **MCP Server Configuration**: `.mcp.json` auto-spawning `ta mcp`
- **Hooks**: `hooks/session_start.sh` (injects current active task and queue summary on session launch)
- **Rules**: `rules/task_agent.md` (directing agents to prefer durable `task-agent` queues over ephemeral todos)
- **Status Line**: `scripts/statusline.sh`
- **Skills**: Bundled portable skills (`next-task`, `complete-task`, `mission-workflow`)

## Installation

### Via `ta init-plugin`
```bash
ta init-plugin --agy
```

### Manual Installation
Copy or symlink this directory into `~/.gemini/antigravity-cli/plugins/task-agent`:
```bash
mkdir -p ~/.gemini/antigravity-cli/plugins
cp -r plugins/antigravity ~/.gemini/antigravity-cli/plugins/task-agent
```
