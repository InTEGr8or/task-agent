# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What is Task Agent?

**Task Agent** (`ta`) is a prioritized, file-based task queue designed for autonomous agentic workers. It manages tasks through a mission file (USV format), transitions them through state directories (pending → draft → active → completed), and provides git worktree isolation and task agent sandboxing for autonomous execution.

The system uses a "filesystem-as-database" philosophy: all tasks are stored as Markdown files in `docs/tasks/`, with priority managed by `docs/tasks/.task-agent/mission.usv` (immutable, git-tracked).

## Development Setup

### Environment

- **Python**: 3.12+ (see `pyproject.toml`)
- **Dependency manager**: `uv` (fast, deterministic)
- **Toolchain manager**: `mise` (manages Python, uv, etc.)

```bash
uv sync              # Install dependencies
mise install         # Set up toolchain
```

### Register with Claude Code

To use the Task Agent MCP server in Claude Code:

```bash
ta init-mcp --claude
```

This registers the task-agent MCP server with Claude Code's local configuration. Verify it's working:

```bash
claude mcp list      # Should show task-agent connected ✔
```

### Build & Test

```bash
make build           # Build wheel
make test            # Run all tests (runs lint first)
make lint            # Ruff + mypy checks
make test-e2e        # Agent sandboxing tests (requires sudo)
```

Run a single test:
```bash
uv run pytest tests/test_cli.py::test_slugify
uv run pytest tests/test_manager.py -v
```

### Project Structure

```
src/taskagent/
  cli.py              # Entry point, argparse, subcommand handlers (2700+ lines)
  manager.py          # TaskAgent class: queue operations, git/filesystem
  agent.py            # Task agent Linux user creation, worktree setup
  models/
    issue.py          # Issue dataclass (name, slug, dependencies)
    metric.py         # Metrics tracking
  plugins/
    github.py         # GitHub issue syncing
  discovery.py        # Find task files on disk
  mcp.py              # Model Context Protocol server
  templates.py        # Agent template rendering
  audit.py            # Audit/healing commands
  config.py           # Configuration management

tests/                # pytest tests
  test_cli.py         # CLI command handlers
  test_manager.py     # TaskAgent logic
  test_agent.py       # Agent sandboxing
  e2e/                # End-to-end agent tests

docs/tasks/           # The actual mission files (filesystem-as-db)
  .task-agent/
    mission.usv       # Prioritized queue (Unit Separator Value format, immutable)
    datapackage.json  # Frictionless Data schema
  pending/            # Tasks ready to start
  draft/              # Tasks being defined
  active/             # Tasks being worked on (by agents or humans)
  completed/          # Finished tasks, archived by year
```

## Architecture & Key Concepts

### 1. Mission File (`docs/tasks/.task-agent/mission.usv`)

The source of truth for task priority. Format: `\x1f`-delimited (Unit Separator).

```
Name\x1fSlug\x1fDependencies
My Task\x1fmy-task\x1fdep1,dep2
Another Task\x1fanother-task\x1f
```

- Row order = priority
- Immutable via `chattr +i` (protected from accidental edits)
- Synced via `ta ingest` (reads filesystem, updates mission)
- Tasks move through state directories, not in mission file

### 2. Task State Transitions

Tasks live in subdirectories based on status:

- **pending/**: Backlog, waiting to start
- **draft/**: Being defined, not yet ready
- **active/**: Worker is processing it
- **mr/**: Merge request datagrams from autonomous workers
- **completed/{year}/**: Archived, includes commit hash metadata

### 3. Task Agents (Linux User Sandboxing)

When `ta start <slug> --agent <template>` runs:

1. Git worktree created at `.gwt/<slug>`
2. Linux user spawned: `agent-{slug}-{hash8}` with home = worktree
3. Dotfiles templated (SSH key, git config, credentials)
4. Sudoers drop-in created for passwordless `ta run`
5. Worker runs as that user via `sudo -u agent-...`

Agent cleanup happens in a `finally` block even if commit fails.

### 4. CLI Subcommands (Major)

The `ta` CLI has 30+ subcommands. Key ones for development:

```bash
ta next                      # Show top issue
ta list                      # List all tasks with hierarchy
ta new [-t TITLE] [-b BODY]  # Create task
ta start <slug>              # Create worktree + agent user
ta run <slug>                # Execute worker as task agent
ta done <slug>               # Move to completed/, commit, cleanup
ta tree                      # Show dependency tree
ta ingest                    # Sync filesystem → mission.usv
ta mcp                       # Run MCP server
ta init-mcp [--claude]       # Register with Claude Desktop
```

## Development Patterns

### Adding a New Subcommand

1. Add handler function: `def cmd_mycommand(console, manager, args)` in `cli.py`
2. Register in `main()`: `subparsers.add_parser("mycommand", ...)`
3. Wire up args: `parser.set_defaults(func=cmd_mycommand)`
4. Test in `tests/test_cli.py`

### Modifying Task Logic

Most task operations go through `TaskAgent` class in `manager.py`:

```python
manager = TaskAgent(config_dir=None)  # Auto-finds docs/tasks/.task-agent/
manager.load_mission()                 # Reads mission.usv
manager.list_issues()                  # Enumerate tasks
manager.move_issue(slug, target_dir)   # Transition state
```

### File Protection

Mission files are immutable after writes. Before modifying them:

```python
manager._set_writable(manager.mission_path, writable=True)
# ... edit ...
manager._set_writable(manager.mission_path, writable=False)
```

The `ta` CLI handles this automatically; direct edits are rare.

## Testing Notes

- **Unit tests**: Mock filesystem and git, very fast
- **Integration tests**: Use temporary `tmp_path` fixtures
- **E2E tests** (`tests/e2e/`): Require `sudo` for user creation; much slower
- **Windows compatibility**: Some paths use `shell=(os.name == "nt")` for subprocess

Test files organize by module (`test_cli.py`, `test_manager.py`, etc.). Use `pytest -v` for verbose output.

## Type Checking

The project uses **mypy** for static analysis. Run:

```bash
make lint           # Includes mypy
uv run mypy src    # Just mypy
```

Common issues:
- `Optional[Path]` for methods that may return `None`
- `type: ignore` for external libraries without stubs (rare)

## Dependencies

Key packages (see `pyproject.toml`):

- **pydantic**: Data models (Issue, etc.)
- **rich**: Terminal UI (tables, panels, markdown)
- **mcp**: Model Context Protocol server
- **githubkit**: GitHub API client
- **python-dotenv**: `.env` file support
- **questionary**: Interactive prompts

Dev dependencies:
- **pytest**: Testing framework
- **ruff**: Linting and formatting
- **mypy**: Type checking
- **bump-my-version**: Version bumping
- **pre-commit**: Git hooks

## Release & Versioning

Versions in `pyproject.toml` follow semver. The release workflow is **two commands**:

```bash
ta version promote patch   # or minor/major: bumps version AND amends previous commit
ta version tag             # Creates tag AND pushes to trigger CI publish
```

### How It Works

1. **Commit your work** with a meaningful message (e.g., `feat: add new feature`, `fix: resolve issue`)
2. **`ta version promote patch`**: 
   - Bumps version in `pyproject.toml` and `uv.lock`
   - **Amends previous commit** with `--amend --no-edit` (preserves original message)
   - Version bump is metadata—release notes on PyPI reflect your actual work
3. **`ta version tag`**: 
   - Creates git tag matching the version in code
   - Pushes tag to trigger GitHub Actions publish to PyPI

### Critical: Version-Tag Matching

The tag **must** point to a commit where `pyproject.toml` has the matching version. The amended commit ensures they always stay in sync.

**If publishing fails:**
- Check PyPI version: `ta version` shows "Latest PyPI version"
- Verify with: `git show HEAD:pyproject.toml | grep version`
- If mismatch: delete bad tag (`git tag -d vX.Y.Z`), bump to next version, re-tag

## Common Tasks for Claude

### Running the CLI locally

```bash
uv run python -m taskagent <subcommand> [args]
# or directly if installed
ta <subcommand> [args]
```

### Debugging subprocess calls

The codebase heavily uses `subprocess.run()` with `shell=(os.name == "nt")` for cross-platform. When debugging:

- Check both `stdout` and `stderr` captures
- Verify `check=True` / `check=False` behavior
- Watch for `capture_output=True` vs explicit `stdout=/stderr=`

### Mission file immutability issues

If tests fail with "cannot modify mission.usv":

```bash
sudo chattr -i docs/tasks/.task-agent/mission.usv
# ... run tests ...
# chattr will be re-applied by manager._set_writable()
```

Or grant capability (requires one-time setup):

```bash
sudo setcap cap_linux_immutable+ep $(which ta)
```

### Worktree cleanup

If a worktree is left behind:

```bash
git worktree prune
git branch -D issue/<slug>
rm -rf .gwt/<slug>
```

## Git Workflow

The project uses a single main branch (`master`). For local development:

1. Create a task: `ta new -t "My fix"`
2. Start it: `ta start my-fix`
3. Make changes in `.gwt/my-fix/`
4. Commit normally (git worktree is isolated)
5. Finish: `ta done my-fix` (moves to completed/, commits metadata)

The `ta` tool manages branching automatically. Rarely need manual `git` commands.
