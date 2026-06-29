---
created_at: 2026-06-28T18:25:43.596479-07:00
---

# Gracefully handle cases where tasks path exists but is not a directory

When docs/tasks or target path is a file/broken symlink, task-agent crashes with a Python traceback (FileExistsError) instead of exiting gracefully. This task handles these situations and prints a user-friendly error message.

## Completion Criteria

Provide a clear RuntimeError and exit code 1 if task/docs path is a file or broken symlink instead of raw tracebacks, verified by tests.

## Solution

Added safety checks in discover() and ensure_issues_dir() to verify target paths exist as directories. If a file or broken symlink exists at these paths, a clean RuntimeError is raised. Wrapped the discover() call in cli.py in a try-except block to output a user-friendly error in red and exit with status code 1 instead of crashing with a FileExistsError traceback. Written unit tests to verify the behavior.

---
**Completed in commit:** `dbe03d9`
