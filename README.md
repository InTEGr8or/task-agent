# Task Agent 🤖

A prioritized, file-based task queue for autonomous agentic workers. This system uses a "Mission Control" approach to manage multiple agents working on git-tracked improvements across various branches and worktrees.

## 📂 System Architecture

The project follows a specific folder structure to manage the lifecycle of an improvement:

- `docs/issues/`: The core queue.
    - `mission.usv`: A prioritized list of issues using Unit Separator Value (`\x1f`) format. This serves as the source of truth for task priority.
    - `datapackage.json`: Frictionless Data metadata for the `mission.usv` schema.
    - `pending/`: New issues awaiting triage or assignment.
    - `draft/`: Issues currently being refined or planned.
    - `active/`: Issues actively being worked on by an agent.
    - `completed/{year}/`: Successfully implemented and verified improvements.
- `.gwt/`: Git Worktree directory where active branches are checked out for isolated agent execution.

## 🛠️ Tooling: `ta` (Task Agent CLI)

The `ta` tool automates the transition of issues through the queue and manages the underlying git infrastructure.

### Commands

| Command | Action |
| :--- | :--- |
| `ta next` | Displays the top prioritized issue from `mission.usv`. |
| `ta new` | Creates a new issue file and adds it to the queue. |
| `ta done` | Moves issue to `completed/`, removes it from the queue, and auto-commits the result. |
| `ta start <slug>` | Moves issue to `active/`, creates a git branch, and sets up a `.gwt/` worktree. |
| `ta run <slug>` | Invokes the sidecar worker defined at `.ta/worker` to process an active issue. |

## 🚀 Workflow

1. **Prioritize**: Use `ta new -t "Title"` to add a task.
2. **Review**: Run `ta next` to see what is currently at the top of the queue.
3. **Dispatch**: (Planned) Run `ta start <slug>` to prepare the workspace.
4. **Execute**: (Planned) The agent (Gemini CLI) processes the task in its isolated worktree via `ta run <slug>`.
5. **Finalize**: Once verified, `ta done` moves the task to the finished state.

## 🤖 Multi-Agent CLI Portfolio (`multi-agent-registry`)

`task-agent` integrates with [`multi-agent-registry`](https://github.com/InTEGr8or/multi-agent-registry) (`multi_agent_registry`) to automatically detect, configure, and inspect AI agent CLIs across your developer workstation:

- **Supported Agent CLIs**: Claude Code (`claude`), Antigravity CLI (`agy`), OpenCode (`opencode`), Grok Build (`grok`), GitHub Copilot CLI (`copilot`), Cursor (`cursor`), Windsurf (`windsurf`), Aider (`aider`), Continue (`continue`), Cline (`cline`), Roo Code (`roo`).
- **Features**: Automatic CLI detection, MCP configuration generation (`ta init-mcp`), session discovery, recent agent activity tracking (`ta agent recent`), and plugin management.

---

## 💬 Matrix Messaging Integration & Sidecar Daemon

`task-agent` includes a zero-dependency Matrix sidecar bridge daemon ([`sidecars/matrix-bridge/`](file:///home/mstouffer/repos/task-agent/sidecars/matrix-bridge/)) for real-time remote notification and task chat bridging:

- **Global Space & Store Binding**:
  ```bash
  # Configure machine-wide Matrix Space link
  ta store matrix space set 'https://matrix.to/#/!space_id:matrix.org'

  # Configure secret token reference (1Password op://, Linux keyring secret-tool://, or pass://)
  ta store matrix token set 'op://Private/6pcab3dt5sml3sslfh6xffqit4/Saved on account.matrix.org/access-token'
  ```
- **Automated Space & Child Room Provisioning**:
  When launched, the sidecar daemon (`python3 sidecars/matrix-bridge/matrix_bridge.py`) auto-discovers or provisions unencrypted child rooms inside your Space for each repository store and delivers real-time inbox comments.

