# Task Agents

A **task agent** is an isolated Linux user that owns a single task's worktree.
It runs worker processes in a sandboxed environment with its own credentials,
SSH keys, git config, and toolchain — completely separate from the human's
session.

```
┌─ ta start my-feature --agent minimal ──────────────────────────┐
│                                                                 │
│  ┌─────────────────┐    ┌───────────────────────────────────┐  │
│  │ 1. git worktree │    │ 2. Create Linux user              │  │
│  │    create       │───▶│    agent-myfeatu-a1b2c3d4         │  │
│  │    .gwt/my-feat │    │    --home-dir .gwt/my-feature     │  │
│  └─────────────────┘    │    --no-create-home               │  │
│                         └──────────────┬────────────────────┘  │
│                                        ▼                       │
│  ┌─────────────────┐    ┌───────────────────────────────────┐  │
│  │ 4. sudoers      │    │ 3. Template dotfiles             │  │
│  │    drop-in      │◀───│    .gitconfig, .ssh/id_ed25519   │  │
│  │    ta run *     │    │    .local/bin/uv, .profile       │  │
│  └─────────────────┘    └───────────────────────────────────┘  │
│                                                                 │
│  ════════════════════════════════════════════════════════════   │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ .gwt/my-feature/                     owned by agent user │  │
│  │   .gitconfig                                               │  │
│  │   .ssh/id_ed25519                                          │  │
│  │   .local/bin/uv                                            │  │
│  │   .profile                                                 │  │
│  │   .ta-agent.json          ← metadata (user + template)    │  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

## Lifecycle

| Step | Command | What happens |
|---|---|---|
| **Create** | `ta start <slug> --agent <template>` | Worktree + Linux user + dotfiles + sudoers |
| **Run** | `ta run <slug>` | Worker runs as the task agent (`sudo -u`) |
| **Destroy** | `ta done <slug>` | Task completed, agent user removed (even if commit fails) |

## Usage

```bash
# Start a new task with a minimal task agent
ta start my-task --agent minimal

# The agent has its own SSH key, git identity, and PATH
ta run my-task

# When done, the agent is automatically cleaned up
ta done my-task -m "Implemented the feature"
```

### What the agent gets

Every task agent — regardless of template — is provisioned with:

- **SSH key** — `~/.ssh/id_ed25519` (generated fresh, no access to human's keys)
- **Git config** — task-specific name/email, `safe.directory` for the worktree
- **`uv`** — symlinked into `~/.local/bin/uv` so workers can use it
- **`.profile`** — `~/.local/bin` added to PATH
- **sudoers** — passwordless `ta` and `ta run *` access

Templates layer additional dotfiles on top (e.g. `~/.aws/config`, `~/.config/gh/hosts.yml`).

### Requirements

- **Linux** with `sudo` access (passwordless `sudo -n true` must succeed)
- The `useradd`, `userdel`, `groupdel`, and `chown` commands
- Git worktrees enabled

## How it works (the gory details)

### User creation

```python
sudo useradd --system \
  --no-create-home \
  --home-dir /repo/.gwt/my-feature \
  --shell /bin/bash \
  agent-myfeatu-a1b2c3d4
```

The agent has **no `/home` directory** — the worktree *is* its home. This avoids
proliferating home directories across the filesystem.

### Worker dispatch

```python
sudo -u agent-myfeatu-a1b2c3d4 bash -l -c \
  "cd .gwt/my-feature && exec env TA_SLUG=... TA_FILE=... TA_ROOT=... <worker>"
```

- `bash -l` sources the agent's `.profile` (so `uv` is on PATH)
- `exec env` passes task environment variables explicitly (nothing inherited)
- `cd` sets the working directory to the worktree

### Cleanup guarantee

```python
try:
    complete_issue(slug)   # moves task, commits
finally:
    destroy_per_task_agent(slug)  # userdel + rm sudoers + rm meta
```

The agent is **always destroyed** in a `finally` block — even if the git
commit fails (e.g. pre-commit hook times out). Run `git worktree prune` and
`git branch -D issue/<slug>` manually if the branch needs cleanup.

## Templates

Templates are stored in `.ta/agents/<name>/meta.toml` in the project root.

| Template | Credentials | Use case |
|---|---|---|
| `minimal` | SSH key only | General development tasks |
| `gh` | SSH key + GitHub CLI (`op://`) | PR creation, issue management |
| `uat-aws` | SSH key + AWS UAT profile (`op://`) | Staging deploys |

Custom templates can be added by creating a new directory under `.ta/agents/`
with a `meta.toml` file. See [templates reference](#) for the full format.

## Agent user naming

Task agent users follow the pattern:

```
agent-{clean-slug}-{hash8}
```

Where `clean-slug` is the task slug trimmed to 15 alphanumeric characters, and
`hash8` is an 8-character SHA-256 hash of `slug:template` to prevent
collisions.

Example: `ta start my-awesome-feature --agent uat-aws`
→ user `agent-myawesomefeatu-a1b2c3d4`
