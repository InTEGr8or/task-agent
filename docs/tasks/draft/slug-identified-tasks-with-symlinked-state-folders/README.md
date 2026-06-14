### Task spec: slug-identified tasks with symlinked state folders

---

#### 1. Overview

**Goal:**  
Implement a Git-backed task system where:

- **Identity** = slugified title (e.g. `foo-task`)
- **Canonical content** lives in one stable file per slug
- **State** ∈ `{draft, pending, active, completed}`
- **Exactly one state per slug at any time**
- **Slug collisions are intentional** and should merge into a single Git history
- **Symlinks** provide a filesystem-native view for Vim and other tools

Tech stack: **Python**, `uv`, `pydantic`, `rich`, `python-dotenv`, `hatchling`, `sidecars`.

---

#### 2. Directory layout

Root (inside repo):

```text
tasks/
  store/
    <slug>.md          # canonical task files, tracked by git
    foo-task.md
    bar-task.md

  states/
    draft/
      foo-task         # symlink → ../../store/foo-task.md
    pending/
      bar-task         # symlink → ../../store/bar-task.md
    active/
    completed/
```

**Rules:**

- `tasks/store/<slug>.md` is the **only** canonical file for that slug.
- `tasks/states/<state>/<slug>` is a **symlink** to `../store/<slug>.md`.
- For any given `<slug>`, there is **at most one symlink** across all state folders.

---

#### 3. Invariants

**Identity & history**

- **Invariant I1:** For a given slug `s`, the canonical file path is always:
  - `tasks/store/{s}.md`
- **Invariant I2:** All edits to a task with slug `s` are applied to:
  - `tasks/store/{s}.md`
- **Invariant I3:** Reusing the same slug `s` (even after long gaps) means:
  - You continue editing `tasks/store/{s}.md`
  - Git history for `s` is continuous across all “incarnations”

**State**

- **Invariant S1:** A slug `s` is in **exactly one** of `{draft, pending, active, completed}` at any time.
- **Invariant S2:** State is represented by the **location of the symlink**:
  - `tasks/states/{state}/{s}` → `../../store/{s}.md`
- **Invariant S3:** For a given slug `s`, there is **at most one symlink** in `tasks/states/*/`.

**Git**

- **Invariant G1:** `tasks/store/*.md` are regular files tracked by Git; they hold all content and history.
- **Invariant G2:** `tasks/states/*/<slug>` are symlinks; Git tracks them as symlink blobs (path strings), not as content.
- **Invariant G3:** Vim and other tools open the **target file** (`store/<slug>.md`) when you open a symlink, so Git integrations in Vim show the canonical file’s history.

---

#### 4. Symlink semantics

For slug `foo-task` in `draft`:

```text
tasks/states/draft/foo-task  ->  ../../store/foo-task.md
```

**Behavior:**

- Opening `tasks/states/draft/foo-task` in Vim:
  - Vim resolves the symlink and opens `tasks/store/foo-task.md`.
  - Git plugins in Vim operate on the canonical file.
- `git log tasks/store/foo-task.md`:
  - Shows full history of the task.
- `git log tasks/states/draft/foo-task`:
  - Shows history of the symlink path (rarely needed).

---

#### 5. CLI behavior (Python)

Entry point: `task` (installed via `uv` / `hatchling`).

##### 5.1 Commands

**`task new "<title>" --state draft`**

- Compute slug from title (e.g. `foo-task`).
- If `tasks/store/{slug}.md` does **not** exist:
  - Create file with frontmatter (optional):

    ```markdown
    ---
    slug: foo-task
    title: Foo Task
    created_at: <iso8601>
    ---
    ```

- If it **does** exist:
  - Reuse the same file (continuation of history).
- Ensure no existing symlink for this slug in `tasks/states/*/`.
- Create symlink:

  ```text
  tasks/states/draft/{slug} -> ../../store/{slug}.md
  ```

---

**`task move <slug> <state>`**

- Validate `<state> ∈ {draft, pending, active, completed}`.
- Find existing symlink for `<slug>` in `tasks/states/*/`:
  - If none: error (or optionally create from current canonical file).
  - If more than one: error (invariant violation).
- Remove existing symlink.
- Create new symlink in `tasks/states/{state}/{slug}` → `../../store/{slug}.md`.

---

**`task list [--state <state>]`**

- If `--state` given:
  - List slugs in `tasks/states/{state}/`.
- Else:
  - List all slugs across all states, with their current state.
- Use `rich` to render a table:

  - **Columns:** slug, state, title (from frontmatter if present), last modified time.

---

**`task show <slug>`**

- Open `tasks/store/{slug}.md` (read-only or print to stdout).
- Optionally show current state by scanning `tasks/states/*/{slug}`.

---

#### 6. Data model (Pydantic)

Define a minimal task metadata model (frontmatter or sidecar JSON/YAML):

```python
from pydantic import BaseModel
from datetime import datetime
from typing import Optional, Literal

TaskState = Literal["draft", "pending", "active", "completed"]

class TaskMeta(BaseModel):
    slug: str
    title: str
    created_at: datetime
    updated_at: Optional[datetime] = None
    state: Optional[TaskState] = None  # optional; canonical state is symlink, this is convenience
```

- Metadata can be:
  - Embedded as YAML frontmatter in `store/<slug>.md`, or
  - Stored as `store/<slug>.meta.json` (sidecar file) using `sidecars`.

---

#### 7. Implementation notes

- **Project layout (hatchling)**

  ```toml
  # pyproject.toml (sketch)
  [build-system]
  requires = ["hatchling"]
  build-backend = "hatchling.build"

  [project]
  name = "tasks-cli"
  version = "0.1.0"
  dependencies = [
    "pydantic",
    "rich",
    "python-dotenv",
    "sidecars",
  ]

  [project.scripts]
  task = "tasks_cli.__main__:main"
  ```

- **Environment config (`python-dotenv`)**
  - `.env` can define `TASKS_ROOT=tasks` if you want to make the root configurable.

- **Sidecars**
  - Use `sidecars` to manage metadata files alongside `store/<slug>.md` if you don’t want frontmatter.

- **uv**
  - Use `uv` for fast, reproducible env + execution:
    - `uv run task new "Foo Task" --state draft`

---

#### 8. Git hooks (optional but recommended)

**Pre-commit hook** to enforce invariants:

- Scan `tasks/states/*/` for all slugs.
- Ensure each slug appears in **at most one** state folder.
- If violation found, reject commit with a clear message.

Pseudo-logic:

```bash
#!/usr/bin/env bash
set -euo pipefail

root="tasks/states"
declare -A seen

while IFS= read -r -d '' path; do
  slug="$(basename "$path")"
  state="$(basename "$(dirname "$path")")"
  if [[ -n "${seen[$slug]:-}" ]]; then
    echo "Error: slug '$slug' appears in multiple states: ${seen[$slug]} and $state" >&2
    exit 1
  fi
  seen[$slug]="$state"
done < <(find "$root" -mindepth 2 -maxdepth 2 -type l -print0)

exit 0
```

---

This spec gives you:

- **Slug as identity**
- **Single canonical file per slug**
- **Symlink-based state folders that Vim and tools treat as real files**
- **Continuous Git history across all incarnations of a slug**
- **Enforceable invariants via a small Python CLI and optional Git hooks**

---

#### 9. Evaluation (2026-05-31)

**Verdict: Deferred.** Symlinks are an architectural improvement rather than
a response to current pain. The main benefit (continuous git history via a
stable canonical file) can be achieved more simply: keep the canonical file
at its original location and track state in the USV only (no symlinks needed).

**Key findings:**

- **Dual-format problem is already solved.** `migrate_all_to_folders()` in
  `init_project()` already sweeps flat files into the folder format.
  No ongoing complexity.
- **Folder format already supports attachments.** The `{slug}/README.md`
  layout allows `screenshot.png` alongside the markdown file. Symlinks add
  nothing here.
- **Windows symlink friction is real.** Developer Mode or admin elevation
  required, with no offsetting benefit for this project.
- **Vim/git tooling is the one unique benefit**, but no current workflow
  depends on it.

**Decision:** Revisit only when a specific integration requirement demands it
(e.g., Vim-centric workflow, multi-branch state views). The spec is preserved
as reference for that future decision.
