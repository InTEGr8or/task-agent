---
created_at: 2026-07-12T18:19:35-07:00
transform:
  context: task-agent repo (.task-agent/tasks station tree + src/taskagent runtime)
  input_type: station layout v0 — implicit conventions, documented as "observed" in the bundled STATION-MAP.md
  output_type: station layout v1 — the STATION-MAP.md declarations, as ratified/amended by Mark
  done_check: test -f docs/STATION-MAP.md   # v1 predicate; superseded by `taskagent audit --conformance` once that tool exists
---

# Ratify STATION-MAP.md declaring task-agent as a typed file-path station system

**One deliverable:** review, correct, and install the bundled `STATION-MAP.md` (in this task folder) as `docs/STATION-MAP.md`, and add it to the docs index. Conformance *fixes* are NOT in scope — each accepted gap in the map's Conformance Gaps section becomes its own follow-up task.

## Why

task-agent was the first extraction of the file-path-queue idiom from cocli, and is dogfood consumer #2 for the typed file-path-queue transformer library being specified there (cocli task: `design-spec-for-reusable-typed-file-path-queue-transformer-library-extracted-from-cocli`). The Station Map is the instance document: it declares what task-agent's directories, records, and transitions *are* in the shared vocabulary (stations, typed transitions, queue/WAL/index edge roles), and lists where the current implementation deviates. The gap list is the migration backlog — the map generates its own task queue.

This task is also the first **portable task** prototype: its frontmatter declares a typed transform (context, input type, output type, executable done_check) on the system it flows through. The task record describing the migration travels through the very stations it will migrate — if the idiom survives that loop, it generalizes.

## Steps

1. Read the bundled `STATION-MAP.md` (sibling file in this task folder). Its "observed" sections were derived from the actual repo state on 2026-07-12 (`src/taskagent/manager.py`, `models/issue.py`, `audit.py`, and the `.task-agent/tasks/` tree) — verify against current code; the dependency-terminology migration was mid-flight when it was written.
2. Amend any declaration that is wrong or that you decide should be different (the map distinguishes *observed* behavior from *declared* v1 intent — the declared parts are proposals until you ratify them).
3. Decide the flagged judgment calls (marked ⚖️ in the map): AuditLog's role (telemetry vs WAL), `mr/` station semantics, identity strategy for slugs.
4. Move the ratified file to `docs/STATION-MAP.md`; link it from `docs/README.md`.
5. Create one follow-up task per accepted conformance gap (the map's final section is pre-written to be split into task titles).

## Completion Criteria

- `docs/STATION-MAP.md` exists, ratified (done_check passes: `test -f docs/STATION-MAP.md`).
- `docs/README.md` links it.
- Every accepted conformance gap has a corresponding pending task; every rejected gap is deleted from the map or annotated with why it's accepted-as-is.
- The three ⚖️ judgment calls are resolved in the map's text.

## Solution

Ratified all three judgment calls (AuditLog=telemetry, mr/=task-machine station, slug=immutable ID). Installed docs/STATION-MAP.md, linked from docs/README.md. Created 6 follow-up draft tickets for the conformance gaps.

---
**Completed in commit:** `8b13f8b`
