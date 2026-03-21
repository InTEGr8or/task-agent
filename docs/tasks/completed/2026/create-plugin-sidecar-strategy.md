# The "Plugin" Strategy: Technical Design

To keep `task-agent` lightweight and dependency-free while enabling powerful autonomous execution via the Google ADK, we will use a **Subprocess Sidecar** pattern.

## 1. The Interface-First Approach (The Protocol)

The core `ta` tool will not know *how* a task is executed. It only knows how to *trigger* execution.

### `ta run <slug>` logic:
1.  **Locate Task**: Find the issue file (slug.md or slug/README.md).
2.  **Locate Worker**: Look for an executable at `.ta/worker` (could be `.py`, `.sh`, etc.) in the project root.
3.  **Environment Injection**: Invoke the worker as a subprocess, passing metadata via environment variables:
    *   `TA_SLUG`: The issue identifier.
    *   `TA_FILE`: Absolute path to the issue Markdown file.
    *   `TA_ROOT`: Path to the target project.
4.  **Handoff**: The worker reads the Markdown, performs the work, and eventually calls `ta done <slug>` to signal completion.

## 2. Sidecar Internal Architecture (Recommended)

While the core `ta` tool is agnostic to the sidecar's internals, the reference **ADK Sidecar** should implement a robust autonomous loop:

1.  **Manager Agent**: Parses the `TA_FILE`, understands the requirements, and coordinates sub-agents.
2.  **Worker Agent**: Performs the actual code modifications within the git worktree.
3.  **Validator Agent**: Executes verification logic (e.g., `make test`, `make lint`).
4.  **Correction Loop**: If validation fails, the Manager instructs the Worker to fix the issues based on the error logs.
5.  **Finalization**: The Sidecar only calls `ta done` once the Validator Agent provides a "Pass" signal.

## 3. Code Structure

To keep the core repo clean, we will structure it as follows:

```text
/
├── src/taskagent/          # Core CLI (no heavy dependencies)
├── tests/                  # Core tests
└── sidecars/
    └── adk-worker/         # Standalone project using Google ADK
        ├── pyproject.toml  # Defines its own dependencies (google-adk, etc.)
        └── worker.py       # Implements the Manager-Worker-Validator loop
```

### Benefits:
*   **Zero Bloat**: Users who just want a manual queue don't need Google credentials or heavy SDKs.
*   **Flexibility**: The "sidecar" can be written in any language or framework.
*   **Reliability**: The Manager-Validator loop ensures that autonomous work is verified before being marked "Done".

## 4. Implementation Plan

1.  **Infrastructure**: Implement `ta start <slug>` to handle git branch creation and worktree setup.
2.  **Protocol**: Implement `ta run <slug>` in the core CLI to trigger the sidecar at `.ta/worker`.
3.  **Reference Sidecar**: Build the `sidecars/adk-worker/` project using the ADK samples as a guide.

---
**Status:** Design Phase
**Next Step:** Implement `ta start` to create the execution environment.

---
**Completed in commit:** `4ea53a9`
