---
created_at: 2026-06-14 10:03
---

## Phase 2 — Agent templates

**Depends on:** agent-sandboxing-via-linux-accounts

---

### Objective

Extend `ta init-agent` to accept a named template that provisions cloud/Git
credentials and SSH keys into the agent user's home directory at init time.

### Key design

```
.ta/agents/
  uat-aws/
    meta.toml             # agent name, description
    dotfiles/
      .gitconfig
      .aws/config
      .aws/credentials     # materialized from op://
      .ssh/id_ed25519
      .config/gh/hosts.yml # materialized from op://
    hooks/
      pre-init.sh
      post-init.sh
```

**`ta init-agent <name> --template <template>`** reads the template dir,
materializes dotfiles (inline content or `op://` 1Password pointers), runs
hooks, and chowns everything to the agent user.

### Built-in templates to ship

- `gh` — GitHub-only (clone issues, open PRs)
- `uat-aws` — AWS UAT deployment
- `minimal` — git identity + SSH, no cloud

### Files to modify/create

| File | Change |
|---|---|
| `src/taskagent/templates.py` | New module: `load_template()`, `materialize_dotfiles()`, `run_hooks()` |
| `src/taskagent/cli.py` | `cmd_init_agent`: `--template` flag, dispatch to template logic |
| `src/taskagent/agent.py` | `init_agent()`: optionally skip default resources when template provides them |
| `.ta/agents/minimal/meta.toml` | Built-in minimal template |
| `.ta/agents/gh/meta.toml` | Built-in GH template |
| `.ta/agents/uat-aws/meta.toml` | Built-in UAT AWS template |
| `tests/test_templates.py` | Unit tests |
| `tests/e2e/test_agent_sandboxing.sh` | Add template-based init to e2e |

### Completion criteria

1. `ta init-agent <name> --template minimal` creates user + SSH + gitconfig
2. `ta init-agent <name> --template gh` creates user + SSH + gitconfig + GH config
3. Template dotfiles support `source = "inline"` and `source = "op://..."` 
4. `op://` materialization runs `op run` at init time (requires 1Password CLI)
5. Hooks (`pre-init.sh`, `post-init.sh`) run with the template dir as CWD
6. Error if template directory doesn't exist
7. Error if `op` CLI is missing when template uses `op://` sources

---
**Completed in commit:** `<pending-commit-id>`
