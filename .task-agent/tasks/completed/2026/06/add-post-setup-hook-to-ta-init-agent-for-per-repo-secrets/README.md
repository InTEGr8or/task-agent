---
created_at: 2026-06-14T10:03:52-07:00
---

# Add --post-setup hook to ta init-agent for per-repo secrets

Add a --post-setup <script> flag to ta init-agent that runs an arbitrary script or command after the agent user is fully created (useradd, sudoers, SSH key, template dotfiles). This enables injecting per-repo secrets (GPG keys, npm tokens, custom SSH configs) that aren't in the template.

Context:
Currently agent setup creates a Linux user, generates SSH keys, materializes template dotfiles, and configures sudoers. But there's no hook for post-creation customization. Teams need a way to inject repo-specific secrets that shouldn't live in the shared template.

Requirements:
1. Add --post-setup <script> argument to ta init-agent subparser
2. After agent.init_agent() succeeds, execute the script via subprocess
3. The script receives the agent username as the first argument (or via AGENT_USER env var)
4. The script is invoked as the agent user (sudo -u agent_user <script>) so it has access to the agent's home directory
5. Report stdout/stderr from the script for transparency
6. If the script exits non-zero, print a warning but don't crash the init
7. Also add --post-setup to ta start for per-task agents (runs after init_per_task_agent)
8. Document in docs/task-agents.md with examples

Examples of post-setup scripts:
- op read "op://team/gpg/private-key" | gpg --import
- echo "//npm.pkg.github.com/:_authToken=TOKEN" > ~/.npmrc
- curl -s https://internal-ca.example.com/ca.crt > ~/.local/share/ca-certificates/internal.crt

Implementation notes:
- For shared agents (ta init-agent): run from cmd_init_agent in cli.py
- For per-task agents (ta start --agent): run from cmd_start in cli.py after init_per_task_agent
- Use sudo -u <user> -E to preserve selected env vars if needed
- The script path can be absolute or relative to cwd

Completion Criteria:
- --post-setup arg on ta init-agent subparser
- Script executes as agent user after full setup
- Script receives AGENT_USER env var
- Non-zero exit warns but doesn't crash
- --post-setup also works with ta start --agent
- Unit tests mocking subprocess.run for post-setup success/failure
- Documentation with examples in docs/task-agents.md
- All existing tests pass

---
**Completed in commit:** `<pending-commit-id>`
