# ADK Task Worker Sidecar 🤖

This sidecar implements the standard autonomous worker protocol for `task-agent` using the **Google Agent Development Kit (ADK)**.

## Architecture

The worker follows a **Manager-Worker-Validator** pattern:

1.  **Manager**: Reads the task description, analyzes the codebase, and creates a technical plan.
2.  **Worker**: Executes the plan by reading and writing files and running shell commands in the project worktree.
3.  **Validator**: Verifies the implementation by running tests and linters. It provides feedback to the Worker if issues are found.

The loop repeats until the Validator passes or the maximum iteration limit is reached.

## Protocol

### 1. Invocation
The worker is invoked by `ta run <slug>` (or `ta start <slug> --run`). It expects the following environment variables:

- `TA_SLUG`: The unique identifier for the task.
- `TA_FILE`: Absolute path to the task's Markdown description.
- `TA_ROOT`: Absolute path to the project root (usually a git worktree).

### 2. Completion (Merge Request)
Upon successful validation, the worker does **not** call `ta done`. Instead, it writes a "Merge Request" datagram to:
`${TA_ROOT}/docs/tasks/mr/${TA_SLUG}.md`

This datagram contains the final validation summary and becomes the "Solution" explanation when a human or supervisor runs `ta merge ${TA_SLUG}`.

## Requirements

- Python 3.12+
- Google API Key (configured in `.env` or via 1Password).
- `google-adk` package.
- `onepassword-sdk` (optional, for secret management).

## Development

Run locally via `uv`:
```bash
uv run python worker.py
```
