---
created_at: 2026-06-14T10:03:52-07:00
---

We did some work in a prior task `add-configuration-file-support-for-github-plugin`. This task will probably obviate those changes and those files should be cleaned up after implementing this task.

We want to assign different GH CLI accounts to different Git Worktree directories, when we create worktrees. 

We should be able to do this with `direnv` and `mise` and by using the `GH_CONFIG_DIR` environment variable.

# GitHub CLI & Git Identity Switching Strategy

This document describes a clean, deterministic strategy for switching between
**human** and **agent** identities using:

- `GH_CONFIG_DIR` for GitHub CLI authentication
- Git worktrees for branch‑scoped environments
- `direnv` / `mise` for automatic environment activation
- Per‑worktree Git identity or environment variables

The goal is to ensure that each identity (human or agent) has completely isolated:
- GitHub CLI authentication
- Git commit author/committer identity
- SSH keys (optional)
- Environment configuration

---

## 1. Overview

GitHub CLI (`gh`) supports a configuration override via:

`GH_CONFIG_DIR=/path/to/config`


This directory contains:
- `hosts.yml` (OAuth tokens)
- `state.yml` (session metadata)

By switching `GH_CONFIG_DIR` per worktree, you switch GitHub accounts cleanly and
without global side effects.

Git identity (name/email) is **not** stored in `hosts.yml`.  
It must be set via Git config or environment variables.

---

## 2. Directory Layout

Recommended structure:

```
~/.config/gh/
    default/     # human account
    agent/       # automation account

repo/
    .git/
    worktrees/
        main/   # configged for human account
        uat/    # configged for agent account
        {task-name}/    # configged for agent account
```


Each worktree activates its own identity via `.envrc`.

---

## 3. Human Identity (Default)

Human identity uses the default GitHub CLI config:

`GH_CONFIG_DIR="$HOME/.config/gh/default"`


## 4. Config Switcher

This repo currently has an example `./agent.env` with these contents:

```
GH_CONFIG_DIR="$HOME/.config/gh/agent"

GIT_AUTHOR_NAME="Bizkite Agent"
GIT_AUTHOR_EMAIL="agent@bizkite.net"
GIT_COMMITTER_NAME="Bizkite Agent"
GIT_COMMITTER_EMAIL="agent@bizkite.net"
```

The `./.envrc` contains:

```
source_env agent.env
```

We can use different `.envrc` in each worktree to assign the different GH account.

---
**Completed in commit:** `<pending-commit-id>`
