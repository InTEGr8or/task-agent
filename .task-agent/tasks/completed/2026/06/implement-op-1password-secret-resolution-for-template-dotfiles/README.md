---
created_at: 2026-06-14T10:03:52-07:00
---

# Implement op:// 1Password secret resolution for template dotfiles

When a template meta.toml declares a dotfile with source = "op://vault/item/field", the materialization code in templates.py currently logs a warning and skips it. This task implements actual resolution via the 1Password CLI (op).

Template dotfiles in .ta/agents/<name>/meta.toml can use these source types:
- inline: <content> — content embedded directly (working)
- file: <path> — relative path to a file in the template directory (working)
- generate: ssh-key — generate SSH key (working)
- op://vault/item/field — 1Password CLI reference (currently skipped)

Requirements:
1. Detect op:// URI in dotfile source field (already done in template loading)
2. Execute op read "op://vault/item/field" via subprocess to resolve the secret
3. Write resolved content to the target path (same as other source types)
4. Handle errors gracefully: op CLI not installed -> log error and skip; not signed in -> skip; secret not found -> skip; never crash for a missing secret
5. Add --op-timeout <seconds> parameter (default 30s) to ta init-agent
6. Document the feature in docs/task-agents.md

The op command runs as the invoking user (not the agent user) since the agent user won't have a 1Password session. Silent skip is acceptable for CI environments where op isn't available.

Completion Criteria:
- templates.py calls op read for op:// sources
- Error handling for missing CLI, no session, missing secret
- --op-timeout CLI parameter on ta init-agent
- Unit tests mocking subprocess.run for op read success/failure
- Documentation in docs/task-agents.md
- All existing tests pass

## Solution

Implemented op:// 1Password secret resolution in templates.py using subprocess.run to call the op read command, catching errors and timeouts gracefully. Added --op-timeout option to ta init-agent and forwarded it. Documented the new feature in docs/task-agents.md and added unit tests.

---
**Completed in commit:** `d6b16ca`
