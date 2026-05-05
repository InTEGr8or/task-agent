# Architecture 🏗️

Task Agent is designed with a "filesystem-as-a-database" philosophy. This ensures that the task queue is highly portable, version-controlled by git, and easily readable by both humans and machines.

## 📂 Data Storage

All task data is stored within the `docs/tasks/` directory.

### 1. The Mission File (`mission.usv`)
The `mission.usv` file is the source of truth for the prioritized queue. It uses **Unit Separator Value (\x1f)** formatting.
- **Location**: Stored in `docs/tasks/.task-agent/mission.usv`
- **Priority**: Determined by the row order in the file.
- **Fields**: Currently stores `slug` and `dependencies`.
- **Syncing**: The file is automatically kept in sync with the filesystem using `ta ingest`.

### 2. Metadata (`datapackage.json`)
We use the **Frictionless Data** standard to describe the schema of `mission.usv`. 
- **Location**: Stored in `docs/tasks/.task-agent/datapackage.json`
- This allows other tools to easily parse our USV format without hardcoded logic.

### 3. Task States (Directories)
Tasks move through subdirectories based on their current status:
- `pending/`: The primary backlog of tasks ready to be started.
- `draft/`: For tasks that are still being defined or aren't ready for work.
- `active/`: Tasks currently assigned to a worker (human or agent).
- `completed/{year}/`: Archived tasks, including metadata about which git commit completed them.

## 📄 Task Formats

Task Agent supports two ways to store task content:

1.  **File-based**: A simple `<slug>.md` file.
2.  **Directory-based**: A `<slug>/README.md` file. This allows you to group multiple related files (like JSON schema samples or images) within the same task container.

## 🔗 Dependencies

Tasks can depend on one or more other tasks using the `**Depends on:** slug1, slug2` syntax within their Markdown descriptions. Task Agent uses this to provide a hierarchical view in `ta list`.

## 🔒 File Protection

Mission files (`mission.usv` and `datapackage.json`) are protected using Linux `chattr` immutable attribute after writes. This prevents accidental modification. The `ta` command automatically handles unlocking/relocking these files when needed.
