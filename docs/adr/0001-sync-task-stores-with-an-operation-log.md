# ADR 0001: Sync task stores with an append-only operation log

- Status: Accepted
- Date: 2026-10-29
- Scope: task-agent station stores, their `*-tasks` git remotes, native Windows clients, and handterm `ta`

## Context

A task store is a typed path queue. Stations (`pending/`, `draft/`, `active/`, `completed/`, `deleted/`) hold one directory per slug. `mission.usv` is the priority index. Leases live in `lease.json`. The inbox is same-machine only.

Each durable store is already its own git repo under the machine data root (`TA_DATA_ROOT`, else `$XDG_DATA_HOME/task-agent`, else `~/.local/share/task-agent`). The subject repo stays separate. GitHub sibling repos are the remotes, for example `InTEGr8or/task-agent-tasks` and `bizkite-co/handterm-tasks`. `ta store remote {suggest,create,set,attach}` configures that remote. Mutations commit locally through `_commit_task_store`. They do not push. There is no `ta store pull` and no `ta store clone`.

That layout is the right archive. It is a weak multi-writer database.

- WSL and native Windows use different home directories. `ta store migrate` is refused on native Windows because of that split and because git often materializes symlinks as text files. A PowerShell client cannot replay the WSL migration.
- Two clones of one store on one PC diverge even when a remote exists. This machine's `task-agent-tasks` history had already moved past the GitHub `main` tip.
- The hot files are `mission.usv` and directory renames. Overlapping edits do not merge. `git pull --rebase` before every push stops the worker on the first conflict.
- handterm `ta` already targets `bizkite-co/handterm-tasks` through the GitHub Contents API. It writes a single markdown file, does not update `mission.usv`, and leaves the pending copy in place when it marks a task active. A phone cannot join a rebase.

Workers that must keep working are: WSL `ta`, a Windows client of the same PC, other machines, and handterm on a device that only has HTTPS.

## Decision

Git remains the transport and the history log. The replicated object is an append-only operation log. The station tree and `mission.usv` are a projection of that log.

### Log shape

Ops live inside the store:

```text
.task-agent/ops/<writer-id>/<op-id>.op.json
```

`<writer-id>` is one id per machine, stored at `<data-root>/writer-id` (override with `TA_WRITER_ID`). A writer appends only under its own directory. Sync unions every writer's files. Apply order is `(at, id)` with UTC timestamps. A hybrid logical clock can replace that sort later without moving the files.

Each file is one JSON object:

| Field | Meaning |
| :--- | :--- |
| `v` | Schema version. `1` for this ADR. |
| `id` | Unique, time-prefixed id. |
| `writer` | Machine writer id. |
| `at` | UTC timestamp. |
| `verb` | `create`, `move`, `edges`, `rename`, `lease`, `release`. |
| `slug` | Task slug the verb applies to. |
| `payload` | Verb fields. `create` carries `name` and `station`. `move` carries `station` and `from_station`. `edges` carries `blocked_by` and `subtask_of`. `rename` carries `new_slug`. |

Rules for version 1:

- The first `create` for a slug wins. A second `create` for the same slug is a no-op.
- A later `move` for the same slug wins.
- `edges` replaces the fields it names.
- Task markdown still rides in the same commit as the op while `ta` is the writer. A client with no working tree (handterm) puts the new task body in the `create` payload so a materializer can write the file.
- `ingest` is not an op. Adoption of loose markdown stays a local repair, not a sync verb.

### Same machine

The data root stays on the WSL Linux filesystem (`~/.local/share/task-agent`). Do not point `TA_DATA_ROOT` at `/mnt/c` or `%LOCALAPPDATA%`. That creates a second store on NTFS and splits the registry.

Windows PowerShell sets one variable, from `ta store data-root --windows`:

```text
TA_DATA_ROOT=\\wsl$\Debian\home\<user>\.local\share\task-agent
```

That UNC is the same directory, not a copy. Code repos may stay on `C:\`. `ta store migrate` run from WSL moves an in-repo `.task-agent/tasks` tree into the Linux data root and records both `/mnt/c/...` and `C:\...` as host paths. There is no gate that blocks `ta` until every repo is migrated. Migrate the checkout you are using. Windows does not run `ta store migrate`.

### Other machines and the phone

`ta sync` (not built yet) pulls the `*-tasks` repo, unions the log, rebuilds `mission.usv` and station moves from the projection, and pushes. Ordinary mutations keep appending ops and committing the projection so current agents still read directories.

handterm `ta`, defaulting to the subject repo's sibling `*-tasks` repo (`handterm` unless `--repo` is set), appends one op with the Git Data API. The branch update compare-and-swaps the expected SHA and retries once. It does not edit `mission.usv` itself.

A sequencer HTTP service may later assign order and fan the same log out. The file format does not change if that service appears. GitHub stays a valid relay until then.

## Consequences

- Concurrent creates of different slugs merge by taking both files.
- Two moves of one slug have a defined winner (later op id) instead of a rebase conflict in `mission.usv`.
- The projection can be rebuilt from the log. Until `ta sync` exists, the committed tree is still what `ta next` reads, and the log is written beside it.
- Clock skew can reorder ops across machines. Acceptable for v1 because ids are the only cross-writer order. A logical clock is a follow-on, not a new store.
- Writers must not edit another writer's op directory. Git should not present those files as modify/modify conflicts.
- Existing stores gain ops on the next mutation. Old history is not backfilled.

## Rejected strategies

### Push the materialized tree after every change

Commits already happen. Adding `git push` after `_commit_task_store`, with or without `git pull --rebase`, publishes the projection. The second writer to touch `mission.usv` or rename the same slug loses or stops. handterm's one-file Contents API cannot rebase. Useful only as a one-time backup of a store that has no log yet.

### Two clones on one PC, synced only through GitHub

This is the failure already seen when a centralized store and an ejected copy both stayed writable. Shared `TA_DATA_ROOT` removes the need to sync that pair.

### GitHub Issues as the queue

`ta github sync` is a separate, unfinished, one-way import. Issues have no station paths, no `mission.usv` order, and no leases. Mirroring there would be a third queue.

### GitHub Wiki, Keet, or Matrix as the store

The wiki was rejected as a product path when sibling `*-tasks` repos were chosen. Keet and Matrix rooms configured on a store are notification channels. They are not a file log and not a branch with compare-and-swap.

### CRDT database or hosted SQL sync instead of the file checkout

Automerge, Yjs, ElectricSQL, Turso, and similar systems solve multi-writer sync by replacing the working copy. Agents and `ta` read station directories. The station map is a typed path queue. Putting a list CRDT under the op log is possible later for reorder. Replacing the tree with a hosted database drops the checkout those workers use.

### A bespoke sequencer as the only writer, now

One online API that sequences every transition is a good relay once the phone and several agents are always connected. Offline `ta` would become a client of that service. The op log gets the same ordering rules and still moves through git. The sequencer can be added in front of the log. It is not a reason to pick a different replicated object.

## Implementation status

Accepted and in progress on the task "Sync task stores with an append-only operation log".

| Slice | State |
| :--- | :--- |
| This ADR | Accepted |
| Append ops from store mutations, plus an in-memory reduce | In `src/taskagent/oplog.py` |
| `ta store sync` | Fast-forward or merge, then replay ops onto the tree and push. A successful store commit runs this when the store has `origin` and that git root is the store itself. A store inside a subject checkout is committed locally and not pushed. `TA_NO_AUTO_SYNC=1` skips the sync. A fetch, merge, or push failure keeps the local commit and aborts a half-finished merge. |
| handterm `ta new` | One `create` op plus the task file, via `commit-repo-files` (Git Data API, fast-forward ref update, one retry). The Lambda route has to be deployed before a phone can call it. |
| One-time publish | `ta store sync` pushes when the local store is a fast-forward of GitHub. |
