---
created_at: 2026-06-14T10:03:52-07:00
---

### Task spec: agent-sandboxing-via-linux-accounts

**Replaces:** `integrate-gh-cli-alt-accounts`

---

#### 1. Problem

Agents launched via `ta run` inherit the human's shell environment — `direnv`,
`mise`, and cached credentials loaded in the human's session. This means an
agent can accidentally deploy to PROD if PROD credentials happen to be loaded
or cached.

The current `GH_CONFIG_DIR` approach isolates GitHub CLI tokens only. It
doesn't address AWS, Azure, GCP, Kubernetes, or any other PROD credentials.
A proper solution must make the agent **PROD-incompetent by construction**.

---

#### 2. Solution

Run agent processes as a dedicated Linux user. The agent user has its own home
directory with only UAT/non-PROD credentials configured. It physically lacks
the SSH keys, cloud profiles, and tokens needed to access PROD.

```
+--------------------+         +----------------------------+
| Human (mark)       |         | Agent (agent-{template})   |
|                    |         |                            |
| ~/.ssh/id_ed25519  |         | ~/.ssh/agent_ed25519       |
| ~/.config/gh/human |         | ~/.config/gh/agent         |
| ~/.aws/prod        |         | ~/.aws/uat                 |
| PROD credentials   |         | UAT-only credentials       |
+--------------------+         +----------------------------+
         \                              /
          \                            /
           git push to bare remote    /
            \                        /
             \                      /
          +---------------------------+
          |  /srv/git/repo.git        |
          |  (common bare remote)     |
          +---------------------------+
```

**Key invariant:** The agent Linux user's home directory contains only
non-PROD credentials. There is no way for the agent to accidentally deploy to
PROD — it simply doesn't have the keys.

---

#### 3. Phase 1 — Core isolation

**`ta init-agent <name>`** — New command that:

1. Creates a Linux user (`sudo adduser --system agent-<name>`)
2. Generates an SSH key for the agent user
3. Configures `~agent-<name>/.gitconfig` with agent identity
4. Sets up `~agent-<name>/.config/gh/` (optional, prompted)
5. Installs a sudoers drop-in: `human ALL=(agent-<name>) NOPASSWD: /path/to/ta`
6. Outputs a summary of what was created

**`ta run` changes:**

Worker is launched via `sudo -u agent-<name>` rather than directly.
Environment variables (`TA_SLUG`, `TA_FILE`, `TA_ROOT`) are passed explicitly
via `env` on the sudo command line. Working directory is set to the worktree
path via `--chdir`.

```python
# Current
subprocess.run([str(worker)], env=env)

# New
subprocess.run([
    "sudo", "-u", agent_user,
    "--chdir", str(worktree_path),
    "env", f"TA_SLUG={slug}", f"TA_FILE={file}", f"TA_ROOT={root}",
    str(worker)
])
```

**`ta start` changes:**

- After creating the worktree at `.gwt/{slug}/`, sets group permissions:
  - `chown -R :agent-<name> .gwt/{slug}/`
  - `chmod -R g+rwX .gwt/{slug}/`
- If the agent user needs to create the worktree, uses
  `sudo -u agent-<name> git worktree add`

**`~agent-<name>/.gitconfig`:**

```ini
[user]
    name = Agent Name
    email = agent@domain.com
[safe]
    directory = /home/mark/repo/.gwt/*
```

The `safe.directory` entry prevents Git from refusing to operate in the
worktree (owned by human).

**Worktree filesystem layout:**

```
.gwt/{slug}/               # owned by human
  group: agent-<name>       # agent group can read/write
  permissions: 2775         # setgid bit so new files inherit group
```

**`~agent-<name>/.local/bin/uv`:** On init, `uv` is symlinked into the agent
user's `~/.local/bin/` so the agent can run `uv`-based worker scripts without
requiring the human's PATH.

**`~agent-<name>/.profile`:** Created with a PATH entry that adds
`~/.local/bin`, so login shells (`bash -l`) resolve `uv` and future tooling.

**`ta run --agent` invocation:** Uses `bash -l -c` instead of `sh -c` so the
agent's `.profile` is sourced before running the worker:

```python
subprocess.run([
    "sudo", "-u", agent_user,
    "bash", "-l", "-c",
    "cd <worktree> && exec env TA_SLUG=... TA_FILE=... TA_ROOT=... <worker>"
])
```

---

**Subtasks:**

- Phase 2 — Agent templates (`docs/tasks/draft/phase-2-agent-templates/`)
  - **Depends on:** this task
  - Template system for `ta init-agent --template <name>`
- Phase 3 — Per-task isolation (`docs/tasks/draft/phase-3-per-task-isolation/`)
  - **Depends on:** this task, phase-2-agent-templates
  - `ta start --agent <template>` creates a dedicated agent per task

---

#### 6. Design decisions

| Decision | Choice | Rationale |
|---|---|---|
| User creation method | `sudo adduser --system` | Consistent, scriptable, no interactive prompts |
| Agent invocation | `sudo -u agent-<name> bash -l -c "cd <worktree> && exec env ... <worker>"` | Login shell sources profile for PATH; `exec env` passes task env vars explicitly |
| Worktree ownership | Human + group agent | Human can read/write, agent can read/write via group |
| Credential provisioning | `op://` at init time, static files at runtime | No 1Password dependency during agent execution |
| Template storage | `.ta/agents/<name>/` in project repo | Version-controlled, shareable across team |
| Tool discovery | Symlink `uv` into `~agent/.local/bin/` at init time | Agent finds tools without inheriting human PATH |

---

#### 7. Open questions

1. **Default agent.** Should `ta run` (without `--agent`) use a default agent
   user? If so, how is it configured?
2. **Cleanup.** Should there be a `ta destroy-agent <name>` that removes the
   Linux user and cleans up?
3. **Non-Linux.** macOS has no `adduser --system`. Should we skip, or
   implement via `sysadminctl`?
4. **Worktree creation.** Should `ta start` create the worktree as the human
   or the agent? Human is simpler for the initial implementation.
5. **Multiple agents.** Can a single worktree be used by multiple agent users
   simultaneously? (Probably no — single agent per worktree.)

---

#### 8. Files affected

| File | Change |
|---|---|
| `src/taskagent/agent.py` | New module — `init_agent()`, `destroy_agent()`, user management, worktree permissions, profile/tool provisioning |
| `src/taskagent/cli.py` | Add `cmd_init_agent()`, modify `cmd_run()` (sudo + bash -l -c) and `cmd_start()` (chgrp) |
| `src/taskagent/mcp.py` | `run_task`, `complete_task` tools need agent user context (minor) |
| `tests/test_agent.py` | Unit tests for agent module |
| `docs/tasks/active/agent-sandboxing-via-linux-accounts/README.md` | This spec |
| `tests/e2e/test_agent_sandboxing.sh` | End-to-end test script |

---

#### 9. Completion Criteria

**Phase 1 — Core isolation:**

1. `ta init-agent <name>` creates a Linux user with:
   - SSH key in `~agent-<name>/.ssh/`
   - Git config in `~agent-<name>/.gitconfig`
   - `~agent-<name>/.profile` adding `~/.local/bin` to PATH
   - `uv` symlinked into `~agent-<name>/.local/bin/uv`
   - Sudoers drop-in for passwordless ta/worker execution
   - Summary output of what was created
   - Graceful error if sudo is unavailable

2. `ta start --agent <name>` sets worktree permissions (group + ACL) so the
   agent user can read and write the worktree.

3. `ta run` for an active (or pending/draft) task executes the worker via
   `sudo -u <agent>` with environment variables (`TA_SLUG`, `TA_FILE`,
   `TA_ROOT`) passed explicitly on the command line, not inherited.

4. All existing tests continue to pass.

5. New unit tests cover:
   - Sudo invocation arguments and working directory
   - `adduser`/`useradd` invocation arguments
   - Graceful failure when sudo is unavailable
   - Graceful failure when agent user doesn't exist
   - Worktree permission setup

6. New e2e test at `tests/e2e/test_agent_sandboxing.sh` covers:
   - Full lifecycle: `init-agent` → `ta new` → `ta start --agent` →
     `ta run` → verify agent user context → `destroy-agent`
   - E2e test runs in CI on Ubuntu (container or VM)
   - E2e test must pass before the task is accepted

---
**Completed in commit:** `<pending-commit-id>`
