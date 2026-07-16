---
created_at: 2026-06-14T10:03:52-07:00
---

# Fix ta done pre-commit hook timeout killing process before commit finishes

When running ta done <slug>, the complete_issue() method calls subprocess.run(['git', 'commit', ...]) which triggers pre-commit hooks (ruff format check, taskhash, etc.). These hooks can take >30 seconds on large repos, and the timeout kills the entire ta process before the commit completes. The finally block usually saves the agent cleanup, but the commit is left in a partial state.

Symptoms:
- ta done prints "Error: ..." (truncated/obscured by timeout)
- git status shows staged files but no commit made
- The issue stays in active status in mission.usv
- finally block runs and destroys the per-task agent, but worktree remains (orphaned)

Root cause:
The subprocess.run call in manager.py complete_issue() or in cli.py cmd_done() has no explicit timeout, but the overall CLI framework or shell session has a timeout that kills the process group.

Investigation needed:
1. Is the timeout from the CLI framework (click/typer), the shell, or a parent process?
2. Is there a SIGHUP or SIGTERM being sent to the process group?

Possible solutions:
a) Run git commit with --no-verify to skip pre-commit hooks (simplest, but loses hook benefits)
b) Increase the timeout to 300s (band-aid, not a fix)
c) Fork the commit into a background process so the timeout doesn't kill it
d) Split cmd_done into two phases: (1) async commit with progress reporting, (2) agent cleanup
e) Use subprocess.Popen with a longer timeout specific to the git commit call

Preferred approach: Option (a) with a --no-verify flag on ta done that defaults to True (skip hooks). Add --hooks flag to force running pre-commit hooks. This gives the user control while preventing the timeout issue by default. Pre-commit hooks can always be run separately via pre-commit run --all-files.

Implementation:
1. Add --no-verify/--hooks flag to ta done subparser (default: --no-verify=True)
2. Pass should_verify flag through cmd_done -> manager.complete_issue()
3. In complete_issue(), pass --no-verify to git commit when appropriate
4. Add a note to docs/task-agents.md about the trade-off

Completion Criteria:
- --no-verify flag on ta done (default true, skip hooks)
- --hooks flag to force running pre-commit hooks
- complete_issue() passes --no-verify to git commit when appropriate
- finally block still runs agent cleanup
- Documentation of the trade-off
- All existing tests pass

## Solution

Added --no-verify (default) and --hooks options to 'ta done' CLI parser, passed no_verify argument through complete_issue() and _git_commit() to bypass pre-commit hooks during task completion, updated docs/task-agents.md to document the timeout trade-off, and added a unit test.

---
**Completed in commit:** `91a8f9b`
