# Development ⚙️

This document covers how to set up the development environment, run tests, and release new versions of Task Agent.

## 🛠️ Environment Setup

Task Agent uses **`uv`** for dependency management and **`mise`** for toolchain control.

1.  Install `uv` and `mise`.
2.  Install dependencies and set up the virtual environment:
    ```bash
    uv sync
    ```
3.  Activate the environment:
    ```bash
    mise install
    ```

## 🧪 Testing

We use **`pytest`** for automated testing.

To run the test suite:
```bash
make test
```

## 🧹 Linting

We use **`ruff`** for linting and formatting, and **`mypy`** for type checking.

To run all checks:
```bash
make lint
```

## 🚀 Workflow

We use `task-agent` to manage our own development.

1.  **Start a task**:
    ```bash
    ta start <slug>
    ```
    This creates a dedicated git branch and worktree in `.gwt/<slug>`.
2.  **Run autonomous sidecars**:
    ```bash
    ta run <slug>
    ```
    This invokes the sidecar worker (at `.ta/worker`) to process the task.

## ✅ Completing Tasks

Always use **`ta done`** to complete a task.

```bash
ta done <slug>
```

**Why use `ta done`?**
-   **Auto-move**: Automatically moves the issue to `completed/{year}/`.
-   **Auto-commit**: Creates a git commit with a standard message (e.g., `feat: complete <slug>`).
-   **Traceability**: Automatically records the commit hash directly into the completed issue file for future reference.
-   **Versioning**: Does not auto-bump. When ready to publish: `ta version release patch`.

## 📦 Releasing

Releases are automated via GitHub Actions when a version tag is pushed.

**Preferred (atomic):**
```bash
ta version release patch   # or minor / major
```

This bumps the version, commits it (amends only if HEAD is unpushed/untagged; otherwise `chore(release): vX.Y.Z`), tags `vX.Y.Z`, pushes the branch, then pushes the tag.

**Two-step:**
```bash
ta version promote patch
ta version tag             # pushes branch then tag (use --no-push for local only)
```

## 🤖 Continuous Integration

Every push to `master` triggers the following:
- `ruff` checks and formatting validation.
- `mypy` type checking.
- Automated tests via `pytest`.
