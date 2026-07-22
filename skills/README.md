# Task Agent portable skills

Agent Skills (`SKILL.md`) that teach hosts to use **task-agent** as the mission
queue instead of ephemeral session todos.

These skills wrap the existing **MCP** / **CLI** surface. They do not replace
`ta` or the MCP server.

| Skill | When to load |
|-------|----------------|
| [`next-task`](./next-task/SKILL.md) | Pick, inspect, or start the next piece of work |
| [`complete-task`](./complete-task/SKILL.md) | Finish work and close a task correctly |
| [`mission-workflow`](./mission-workflow/SKILL.md) | Multi-session prioritization and lifecycle |

## Prerequisites

1. Install the `ta` CLI (`uv tool install …` or project `uv run ta`).
2. Register the MCP server so the agent has tools:

```bash
ta init-mcp --claude          # Claude Code
ta init-mcp --copilot         # GitHub Copilot CLI (global)
ta init-mcp --agy             # Antigravity CLI (agy)
ta init-mcp --agent opencode  # OpenCode
ta init-mcp --print           # dump JSON for manual config
```

## Manual install

Skills are plain directories. Copy or symlink this folder (or individual skills)
into the host’s skills path.

### Claude Code

Project-local (recommended for this repo):

```bash
mkdir -p .claude/skills
ln -sfn ../../skills/next-task .claude/skills/next-task
ln -sfn ../../skills/complete-task .claude/skills/complete-task
ln -sfn ../../skills/mission-workflow .claude/skills/mission-workflow
```

User-global (paths vary by Claude Code version; typical pattern):

```bash
mkdir -p ~/.claude/skills
cp -a skills/next-task skills/complete-task skills/mission-workflow ~/.claude/skills/
# or symlink from a clone of this repo
```

Confirm with Claude’s skill / plugin UI, or by asking the agent to follow
“mission workflow” / “next task” guidance.

### Antigravity CLI (`agy`)

Workspace skills (project):

```bash
mkdir -p .agents/skills
cp -a skills/next-task skills/complete-task skills/mission-workflow .agents/skills/
# or: ln -sfn ../../skills/next-task .agents/skills/next-task  (etc.)
```

User / CLI plugin staging often lives under `~/.gemini/antigravity-cli/` (see
current Antigravity docs). Until a full plugin ships, project `.agents/skills/`
is the portable path.

Also register MCP:

```bash
ta init-mcp --agy
# project-only:
ta init-mcp --agy --scope project
```

### Other hosts (Cursor, Copilot, Grok, OpenCode)

Copy the same three skill directories into that host’s skills location, keep
MCP registered, and load **mission-workflow** for default queue behavior.

## Layout

```text
skills/
├── README.md                 # this file
├── next-task/SKILL.md
├── complete-task/SKILL.md
└── mission-workflow/SKILL.md
```

## Related

- Plugin packaging (Claude / Antigravity) — follow-on tasks under
  `investigate-better-integration-with-antigravity-cli-of-claude-cli`
- CLI: `ta next`, `ta list`, `ta start`, `ta done`, `ta init-mcp`
