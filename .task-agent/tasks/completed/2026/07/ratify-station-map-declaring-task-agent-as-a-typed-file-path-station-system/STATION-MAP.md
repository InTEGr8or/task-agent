# task-agent Station Map

> **Status: DRAFT — bundled with the ratification task; becomes authoritative at `docs/STATION-MAP.md` once ratified.**
>
> This document declares task-agent as an instance of the typed file-path-queue substrate
> ("a typed state machine where the states are portable file paths") whose vocabulary is
> owned by the library design spec in the cocli repo (task:
> `design-spec-for-reusable-typed-file-path-queue-transformer-library-extracted-from-cocli`;
> thesis: cocli `docs/DESCRIPTION.md`). Do not fork terminology here — if a term is missing,
> add it to the spec, then use it.
>
> Sections marked **observed** describe the implementation as found on 2026-07-12.
> Sections marked **declared (v1)** are proposals that become binding when ratified.
> ⚖️ marks judgment calls the ratifier must resolve.

## 1. Record type (observed)

One task = one directory, named by **slug**, containing `README.md`
(Markdown body + YAML frontmatter, currently `created_at` only). The runtime model is
`Issue` (`src/taskagent/models/issue.py`): `name`, `slug`, `blocked_by: List[str]`,
`subtask_of: Optional[str]`, with `priority` and `status` derived at runtime.
Serialization to the index is USV (`\x1f`-delimited).

Edge fields are persisted as **body prose**, regex-extracted (`manager.py` ~582):
`**Blocked by:**` for ordering dependencies, `**Subtask of:**` for hierarchy.

**Declared (v1):** edge fields move to structured frontmatter (`blocked_by:`,
`subtask_of:` YAML lists); prose-line reader extracts values at runtime.
Frontmatter is the schema; prose is presentation.

## 2. Stations (observed)

Root: `.task-agent/tasks/` (symlinked at `docs/tasks/`).

| Station | Record state | Sharding | Notes |
| :--- | :--- | :--- | :--- |
| `draft/` | intention, not yet actionable | flat | |
| `pending/` | actionable, unclaimed | flat | |
| `active/` | claimed by a worker | flat | |
| `completed/` | terminal fact | by year (`2026/`) | month-sharding is a pending task |
| `deleted/` | terminal, rejected | flat | tombstone station |
| `mr/` | ⚖️ undeclared | by year | semantics not written down anywhere |
| `strategy/`, `plan.md` | mission-level records | — | not task records; different type |

**Declared (v1):** every station binds `(path template, record type, serialization)`.
`strategy/` and `plan.md` get their own record-type declarations or an explicit
"out of scope of the task state machine" annotation.
⚖️ `mr/` must be declared: what record type lives there, which transitions feed it,
and whether it is a station of the task machine or a separate machine.

## 3. Transitions (observed)

Typed from-station→to-station moves, all implemented as directory renames:

| Transition | From → To | Notes |
| :--- | :--- | :--- |
| `create` | ∅ → `pending/` (or `draft/` with flag) | assigns slug from title |
| `promote` | `draft/` → `pending/` | cascades along edges |
| `demote` | reverse of promote | |
| `start` / mark-active | `pending/` → `active/` | **this is the claim** |
| `complete` | `active/` → `completed/YYYY/` | terminal |
| `restore` | `completed/` → active tree | |
| delete | → `deleted/` | tombstone, not erasure |

**Declared (v1):** each transition is a pure typed transform on the record
(from-model-to-model); a transition never partially rewrites a record it isn't moving.

## 4. Edge roles: queue / WAL / index (observed + declared)

Roles attach to *consumer edges*, not to directories. Current reading:

- **Queue (future):** `pending/` → worker edge. `start` is the claim; `active/` holds the
  lease; `completed/`, `deleted/` are terminal states. Single-worker today, so the claim
  protocol is trivially safe; multi-agent use makes atomic-rename claiming load-bearing.
- **WAL (past):** `completed/YYYY/` is the fact log of the task machine — append-only,
  year-partitioned segments, source of truth for history. The pending
  month-sharding+WAL+compaction task extends exactly this role.
- **Index (present):** the USV issues index (with `datapackage` field declarations in
  `manager.py`) is a fold over the station tree; blocked-state computation is a derived
  view over `blocked_by` edges. Both must be rebuildable by rescanning stations —
  **stations are the source of truth; the index is disposable.**
- **Event log:** `AuditLog` (`src/taskagent/audit.py`) writes JSONL lifecycle events to
  `.task-agent/logs/YYYY-MM-DD.jsonl`, pruned after 30 days.
  ⚖️ Its role must be declared: **telemetry** (pruning is fine, log is never consulted for
  truth) or **WAL** (then pruning is a bug and it needs a compaction policy instead).
  Recommendation: telemetry — the stations already are the truth; don't create a second one.

## 5. Conformance gaps (the migration backlog)

Each accepted gap becomes one follow-up task. Written as typed defects against the
substrate's invariants:

1. **Identity derived from mutable content.** Slug comes from the *original* title;
   retitling a task changes its display name but not its identity, and lookups by new
   title fail. Invariant: identity is assigned at creation and never derived from
   mutable fields. ⚖️ Fix options: frozen `id` in frontmatter (slug becomes a display
   alias), or content-address at creation. Either way, directory rename on retitle must
   be either supported or explicitly forbidden.
2. **Schema data outside the schema.** `blocked_by`/`subtask_of` live as regex-matched
   prose lines. Move to frontmatter (§1 declared); keep the alias reader through migration.
3. **Non-atomic record updates.** Content updates (`update_task`) rewrite the body and
   silently drop edges — a read-modify-write that loses fields the writer didn't know
   about. Invariant: a record update is a whole-record typed transform; unknown fields
   round-trip. (This is the bug that repeatedly wiped dependencies on the cocli epic.)
4. **Station store excluded from its own durability.** `.task-agent` is gitignored in
   consumer repos, so `commit_tasks` fails and task state stays uncommitted. Declare the
   durability contract: either the station tree is committed (un-ignore) or durability is
   explicitly delegated elsewhere.
5. **Edge-type conflation cleanup.** `blocked_by` (ordering) vs `subtask_of` (hierarchy)
   are now separate in the `Issue` model with a legacy alias — finish the migration:
   stored prose lines, docstrings (`create_task` still describes deps as parent-of
   promotion cascade), and historical records under `completed/`.
6. **Undeclared station.** `mr/` (§2 ⚖️).
7. **Log role undeclared.** `AuditLog` retention vs WAL semantics (§4 ⚖️).
8. **Index rebuildability unproven.** No command exists to rebuild the USV index from a
   station rescan and verify it matches. This is also the seed of the conformance tool:
   `taskagent audit --conformance` = validate station tree against this map + rebuild
   index and diff. That tool, once built, becomes the executable `done_check` for every
   subsequent conformance transform (the portable-task acceptance predicate).

## 6. Relationship to the library spec

task-agent is **dogfood consumer #2** (after cocli). The library spec owns: station/
transition/edge-role vocabulary, the claim protocol, WAL/compaction semantics,
fold/watermark semantics, and schema versioning. This map owns only: which stations
exist here, their record types, and this repo's conformance state. When the library's
Protocol interfaces land, task-agent's `manager.py` should be refactorable to implement
them with no on-disk change — that refactor being cheap is the test that this map is true.
