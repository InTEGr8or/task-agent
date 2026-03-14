from typing import List, Optional, Tuple, Dict, Set
from pathlib import Path
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
import sys
import argparse
import os
import json
import importlib.metadata
import urllib.request
import questionary
import subprocess
import shutil

try:
    import tty
    import termios

    HAS_TERMIOS = True
except ImportError:
    HAS_TERMIOS = False
    try:
        import msvcrt

        HAS_MSVCRT = True
    except ImportError:
        HAS_MSVCRT = False

from rich.live import Live

from taskagent.models.issue import Issue
from taskagent.manager import TaskAgent
from taskagent.discovery import discover


def get_tool_version() -> str:
    """Read the task-agent tool version."""
    try:
        return importlib.metadata.version("task-agent")
    except Exception:
        return "unknown"


def get_latest_pypi_version(timeout: int = 4) -> Optional[str]:
    """Fetch the latest version of task-agent from PyPI."""
    url = "https://pypi.org/pypi/task-agent/json"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            data = json.load(response)
            return data["info"]["version"]
    except Exception:
        return None


def get_project_version() -> Tuple[str, Optional[str]]:
    """Read the current project version from pyproject.toml or package.json."""
    # Check pyproject.toml
    if Path("pyproject.toml").exists():
        try:
            with open("pyproject.toml", "r") as f:
                content = f.read()
                import re

                match = re.search(r'version\s*=\s*"(.*?)"', content)
                if match:
                    return match.group(1), "pyproject.toml"
        except Exception:
            pass

    # Check package.json
    if Path("package.json").exists():
        try:
            with open("package.json", "r") as f:
                data = json.load(f)
                if "version" in data:
                    return data["version"], "package.json"
        except Exception:
            pass

    return "unknown", None


def get_key() -> str:
    """Read a single key or escape sequence from stdin."""
    if HAS_TERMIOS:
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = sys.stdin.read(1)
            if ch == "\x1b":
                # Start of an escape sequence
                # We want to read more if it's an arrow key
                import select

                if select.select([sys.stdin], [], [], 0.1)[0]:
                    ch += sys.stdin.read(2)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        return ch
    elif HAS_MSVCRT:
        # Windows handling
        ch = msvcrt.getch()  # type: ignore
        if ch in (b"\x00", b"\xe0"):
            # Special key (like arrow keys)
            ch2 = msvcrt.getch()  # type: ignore
            # Map common Windows keys to Unix escape sequences for consistency
            if ch2 == b"H":
                return "\x1b[A"  # Up
            if ch2 == b"P":
                return "\x1b[B"  # Down
            return f"\x1b[{ch2.decode('ascii')}"

        # Handle Ctrl keys on Windows (mapped to control characters)
        # Ctrl+K is \x0b, Ctrl+J is \x0a (newline)
        return ch.decode("ascii", errors="ignore")

    return sys.stdin.read(1)


def select_issue(
    console: Console,
    issues: List[Issue],
    slug_part: Optional[str],
    status_filter: Optional[List[str]] = None,
) -> Optional[Issue]:
    """Helper to select an issue based on partial slug and status filter."""
    if not issues:
        return None

    # Apply status filter if provided
    filtered = issues
    if status_filter:
        filtered = [i for i in issues if i.status in status_filter]

    if not filtered:
        return None

    # If no slug_part provided, return top one
    if slug_part is None:
        return filtered[0]

    # Find matches
    matches = [i for i in filtered if i.slug.startswith(slug_part)]

    if not matches:
        return None

    if len(matches) == 1:
        return matches[0]

    # Interactive selection
    choices = [f"{i.slug} ({i.status})" for i in matches]
    selection = questionary.select(
        "Multiple issues match. Select one:", choices=choices, use_jk_keys=True
    ).ask()

    if selection is None:
        return None

    selected_slug = selection.split(" (")[0]
    return next(i for i in matches if i.slug == selected_slug)


def cmd_next(console: Console, manager: TaskAgent):
    """Show the top issue."""
    next_issue = manager.get_next_issue()
    if not next_issue:
        console.print(f"[yellow]No issues found in {manager.mission_path}[/yellow]")
        return

    issue_file = manager.find_issue_file(next_issue.slug)

    if not issue_file:
        console.print(f"[red]Issue file not found for slug: {next_issue.slug}[/red]")
        sys.exit(1)

    with issue_file.open("r", encoding="utf-8") as f:
        content = f.read()

    deps_info = ""
    if next_issue.dependencies:
        deps_info = f"[bold blue]DEPENDS ON:[/bold blue] [yellow]{', '.join(next_issue.dependencies)}[/yellow]\n"

    with console.pager(styles=True):
        console.print(
            Panel(
                f"[bold blue]NEXT ISSUE:[/bold blue] [cyan]{next_issue.slug}[/cyan]\n"
                f"[bold blue]PRIORITY:[/bold blue] {next_issue.priority} | "
                f"[bold blue]STATUS:[/bold blue] {next_issue.status}\n"
                f"{deps_info}"
                f"[bold blue]FILE:[/bold blue] {issue_file}",
                title="Task Agent",
                expand=False,
            )
        )

        md = Markdown(content)
        console.print(md)


def cmd_done(
    console: Console,
    manager: TaskAgent,
    slug_part: Optional[str] = None,
    commit_message: Optional[str] = None,
    should_commit: bool = True,
    push: bool = False,
):
    """Mark an issue as done."""
    issues = manager.load_mission()
    target_issue = select_issue(console, issues, slug_part)

    if not target_issue:
        if slug_part:
            console.print(f"[red]No issue found matching '{slug_part}'.[/red]")
        else:
            console.print("[yellow]No issues to mark as done.[/yellow]")
        sys.exit(1)

    try:
        _, code_hash = manager.complete_issue(
            target_issue.slug, commit_message, should_commit, push_mission=push
        )
        console.print(
            f"[bold green]Issue '{target_issue.slug}' marked as done and removed from mission.usv[/bold green]"
        )
        if should_commit and code_hash not in ["unknown", "failed"]:
            console.print(
                f"[bold green]Successfully committed work as {code_hash}.[/bold green]"
            )
        if push:
            console.print(
                "[bold green]Mission repository pushed to origin.[/bold green]"
            )
    except Exception as e:
        console.print(f"[red]Error completing issue: {e}[/red]")
        sys.exit(1)

    # Auto-promote patch version
    ver, source = get_project_version()
    if source == "pyproject.toml" and Path("pyproject.toml").exists():
        console.print("[blue]Auto-promoting project patch version...[/blue]")
        try:
            cmd_version(console, promote="patch")
        except Exception as e:
            console.print(
                f"[yellow]Warning: Could not auto-promote version: {e}[/yellow]"
            )


def cmd_push(console: Console, manager: TaskAgent):
    """Push the mission repository."""
    if not manager.mission_root:
        console.print("[red]Mission repository not detected.[/red]")
        return

    console.print(
        f"[blue]Pushing mission repository at {manager.mission_root}...[/blue]"
    )
    try:
        manager.push_mission_repo()
        console.print(
            "[bold green]Successfully pushed mission repository.[/bold green]"
        )
    except Exception as e:
        console.print(f"[red]Failed to push mission repository: {e}[/red]")


def cmd_eject_mission(console: Console, manager: TaskAgent, public: bool = False):
    """Automate the move of docs/issues to a separate repository."""
    source_dir = manager.issues_root
    if source_dir.is_symlink():
        console.print(
            "[yellow]docs/issues is already a symlink. Ejection skipped.[/yellow]"
        )
        return

    if not source_dir.exists():
        console.print(f"[red]Source directory {source_dir} not found.[/red]")
        return

    # Determine names
    project_root = Path.cwd()
    project_name = project_root.name
    target_name = f"{project_name}-issues"
    target_path = project_root.parent / target_name

    if target_path.exists():
        console.print(f"[red]Target path {target_path} already exists. Aborting.[/red]")
        return

    console.print(f"[blue]Ejecting mission to [bold]{target_path}[/bold]...[/blue]")

    try:
        # 1. Verify GH CLI
        subprocess.run(["gh", "--version"], check=True, capture_output=True)

        # 2. Create target and move files
        target_path.mkdir(parents=True)
        for item in source_dir.iterdir():
            shutil.move(str(item), str(target_path / item.name))

        # 3. Git Init and Create Repo
        subprocess.run(["git", "-C", str(target_path), "init"], check=True)

        # Add everything
        subprocess.run(["git", "-C", str(target_path), "add", "."], check=True)
        subprocess.run(
            [
                "git",
                "-C",
                str(target_path),
                "commit",
                "-m",
                "chore: initial mission control commit",
            ],
            check=True,
        )

        # gh repo create
        visibility = "--public" if public else "--private"
        console.print(
            f"[blue]Creating GitHub repository [bold]{target_name}[/bold] ({visibility})...[/blue]"
        )
        subprocess.run(
            [
                "gh",
                "repo",
                "create",
                target_name,
                visibility,
                "--source=.",
                "--remote=origin",
                "--push",
            ],
            cwd=str(target_path),
            check=True,
        )

        # 4. Remove old dir and Symlink
        shutil.rmtree(str(source_dir))

        # Use an absolute symlink for maximum local robustness
        os.symlink(str(target_path.absolute()), str(source_dir))

        # 5. Update .gitignore
        gitignore = project_root / ".gitignore"
        # Calculate relative path for the gitignore entry
        git_rel_path = source_dir.absolute().relative_to(project_root.absolute())
        ignore_line = f"\n{git_rel_path}\n"

        if gitignore.exists():
            content = gitignore.read_text()
            if str(git_rel_path) not in content:
                with gitignore.open("a") as f:
                    f.write(ignore_line)
        else:
            gitignore.write_text(ignore_line)

        # 6. Update .env
        env_file = project_root / ".env"
        env_lines = [
            "\nTA_EJECT_ISSUES=true\n",
            f"TA_EJECTED_ISSUES_PATH={target_path.absolute()}\n",
        ]
        if env_file.exists():
            content = env_file.read_text()
            with env_file.open("a") as f:
                if "TA_EJECT_ISSUES" not in content:
                    f.write(env_lines[0])
                if "TA_EJECTED_ISSUES_PATH" not in content:
                    f.write(env_lines[1])
        else:
            env_file.write_text("".join(env_lines))

        console.print(
            "[bold green]Successfully ejected mission repository![/bold green]"
        )
        console.print(f"Mission Repo: [cyan]{target_path.absolute()}[/cyan]")
        console.print(
            f"Symlink: [cyan]{source_dir}[/cyan] -> [cyan]{target_path.absolute()}[/cyan]"
        )
        console.print("\n[bold green]Environment updated:[/bold green]")
        console.print(f"  - Added [cyan]{git_rel_path}[/cyan] to .gitignore")
        console.print("  - Configured [cyan]TA_EJECTED_ISSUES_PATH[/cyan] in .env")
        console.print("\n[dim]The symlink will now 'auto-heal' in new worktrees.[/dim]")

    except subprocess.CalledProcessError as e:
        console.print(f"[red]Command failed: {e}[/red]")
        if e.stderr:
            console.print(f"[dim]{e.stderr.decode()}[/dim]")
    except Exception as e:
        console.print(f"[red]An error occurred: {e}[/red]")


def cmd_new(
    console: Console,
    manager: TaskAgent,
    title: str,
    body: str,
    draft: bool,
    depends_on: Optional[str] = None,
    as_dir: bool = False,
    completion_criteria: Optional[str] = None,
):
    """Create a new issue."""
    try:
        issue = manager.create_issue(
            title, body, draft, depends_on, as_dir, completion_criteria
        )
        console.print(f"[bold green]Created new issue: {issue.slug}[/bold green]")
        issue_file = manager.find_issue_file(issue.slug)
        console.print(f"File: {issue_file}")
        if issue.dependencies:
            console.print(f"Depends on: {', '.join(issue.dependencies)}")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)


def cmd_list(
    console: Console,
    manager: TaskAgent,
    output_format: str = "table",
):
    """List all issues in mission.usv."""
    issues = manager.sync_mission()
    if not issues:
        if output_format == "json":
            print("[]")
        else:
            console.print(f"[yellow]No issues found in {manager.mission_path}[/yellow]")
        return

    # Build hierarchy for display
    slug_to_issue = {i.slug: i for i in issues}
    children_map: Dict[str, List[str]] = {}
    for i in issues:
        for dep in i.dependencies:
            if dep in slug_to_issue:
                if dep not in children_map:
                    children_map[dep] = []
                children_map[dep].append(i.slug)

    visited: Set[str] = set()
    rows_to_display: List[Tuple[Issue, int]] = []

    def build_rows(issue: Issue, depth: int):
        if issue.slug in visited:
            return
        visited.add(issue.slug)
        rows_to_display.append((issue, depth))
        if issue.slug in children_map:
            child_issues = [slug_to_issue[s] for s in children_map[issue.slug]]
            for child in child_issues:
                build_rows(child, depth + 1)

    for issue in issues:
        has_internal_dep = any(dep in slug_to_issue for dep in issue.dependencies)
        if not has_internal_dep:
            build_rows(issue, 0)

    for issue in issues:
        if issue.slug not in visited:
            build_rows(issue, 0)

    if output_format == "json":
        data = []
        for i, depth in rows_to_display:
            issue_file = manager.find_issue_file(i.slug)
            location = str(issue_file) if issue_file else None
            data.append(
                {
                    "priority": i.priority,
                    "status": i.status,
                    "slug": i.slug,
                    "dependencies": i.dependencies,
                    "location": location,
                    "depth": depth,
                }
            )
        print(json.dumps(data, indent=2))
        return

    if output_format == "text":
        for i, depth in rows_to_display:
            issue_file = manager.find_issue_file(i.slug)
            location = str(issue_file) if issue_file else "MISSING"
            deps = ",".join(i.dependencies)
            indent = "  " * depth
            prefix = "└─ " if depth > 0 else ""
            console.print(
                f"{i.priority:<3} {i.status:<8} {indent}{prefix}{i.slug:<30} {deps:<20} {location}"
            )
        return

    table = Table(title="Task Queue")
    table.add_column("Priority", justify="right", style="cyan")
    table.add_column("Status", style="magenta")
    table.add_column("Slug", style="green")
    table.add_column("Depends On", style="yellow")
    table.add_column("Location", style="dim")

    for issue, depth in rows_to_display:
        issue_file = manager.find_issue_file(issue.slug)
        location = str(issue_file) if issue_file else "[red]MISSING[/red]"

        status_str = issue.status
        if status_str == "pending":
            status_str = f"[bold yellow]{status_str}[/bold yellow]"
        elif status_str == "draft":
            status_str = f"[dim]{status_str}[/dim]"
        elif status_str == "active":
            status_str = f"[bold green]{status_str}[/bold green]"

        indent = "  " * depth
        prefix = "└─ " if depth > 0 else ""
        display_slug = f"{indent}{prefix}{issue.slug}"

        table.add_row(
            str(issue.priority),
            status_str,
            display_slug,
            ", ".join(issue.dependencies),
            location,
        )
    console.print(table)


def cmd_ingest(console: Console, manager: TaskAgent):
    """Ingest existing markdown files into mission.usv."""
    num_new, num_removed = manager.ingest_issues()
    console.print(
        f"[bold green]Ingested {num_new} new issues, removed {num_removed} missing ones.[/bold green]"
    )

    # Datapackage sync logic
    datapackage = {
        "name": "mission-control",
        "resources": [
            {
                "name": "mission",
                "path": "mission.usv",
                "format": "csv",
                "delimiter": "\u001f",
                "schema": {
                    "fields": [
                        {"name": "slug", "type": "string"},
                        {"name": "dependencies", "type": "string"},
                    ]
                },
            }
        ],
    }
    dp_path = manager.issues_root / "datapackage.json"
    with dp_path.open("w", encoding="utf-8") as f:
        json.dump(datapackage, f, indent=2)
    console.print(f"[bold green]Updated {dp_path}[/bold green]")


def cmd_promote(console: Console, manager: TaskAgent, slug_part: str):
    """Promote an issue from draft to pending."""
    issues = manager.load_mission()
    target = select_issue(console, issues, slug_part, status_filter=["draft"])
    if not target:
        console.print(f"[red]No draft issue found matching '{slug_part}'.[/red]")
        return
    try:
        manager.promote_issue(target.slug)
        console.print(
            f"[bold green]Issue '{target.slug}' promoted to pending.[/bold green]"
        )
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def cmd_demote(console: Console, manager: TaskAgent, slug_part: str):
    """Demote an issue from pending to draft."""
    issues = manager.load_mission()
    target = select_issue(console, issues, slug_part, status_filter=["pending"])
    if not target:
        console.print(f"[red]No pending issue found matching '{slug_part}'.[/red]")
        return
    try:
        manager.demote_issue(target.slug)
        console.print(
            f"[bold green]Issue '{target.slug}' demoted to draft.[/bold green]"
        )
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def cmd_active(
    console: Console,
    manager: TaskAgent,
    slug_part: Optional[str] = None,
    silent: bool = False,
) -> Optional[Issue]:
    """Move an issue to active status."""
    issues = manager.load_mission()
    target = select_issue(
        console, issues, slug_part, status_filter=["pending", "draft", "active"]
    )
    if not target:
        if slug_part:
            console.print(
                f"[red]No pending/draft issue found matching '{slug_part}'.[/red]"
            )
        else:
            console.print("[yellow]No issues available to mark as active.[/yellow]")
        return None

    try:
        issue = manager.move_to_active(target.slug)
        if not silent:
            console.print(
                f"[bold green]Issue '{issue.slug}' is now active.[/bold green]"
            )
        return issue
    except Exception as e:
        if not silent:
            console.print(f"[red]Error: {e}[/red]")
        return None


def cmd_start(console: Console, manager: TaskAgent, slug_part: Optional[str] = None):
    """Move an issue to active and set up a git worktree."""
    target = cmd_active(console, manager, slug_part, silent=False)
    if not target:
        return

    slug = target.slug
    branch_name = f"issue/{slug}"
    worktree_path = Path(".gwt") / slug

    if worktree_path.exists():
        console.print(
            f"[yellow]Worktree directory already exists: {worktree_path}[/yellow]"
        )
        return

    console.print(
        f"[blue]Creating branch [bold]{branch_name}[/bold] and worktree at [bold]{worktree_path}[/bold]...[/blue]"
    )

    try:
        Path(".gwt").mkdir(exist_ok=True)
        subprocess.run(
            ["git", "worktree", "add", "-b", branch_name, str(worktree_path)],
            check=True,
            capture_output=True,
            text=True,
        )
        console.print(f"[bold green]Successfully started issue '{slug}'.[/bold green]")
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Error: {e.stderr.strip()}[/red]")


def cmd_prioritize(
    console: Console, manager: TaskAgent, slug_part: str, direction: str
):
    """Move an issue up or down in priority."""
    issues = manager.load_mission()
    target = select_issue(console, issues, slug_part)
    if not target:
        console.print(f"[red]No issue found matching '{slug_part}'.[/red]")
        return
    try:
        manager.prioritize_issue(target.slug, direction)
        console.print(f"[bold green]Moved '{target.slug}' {direction}.[/bold green]")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def cmd_self_up(console: Console):
    """Upgrade task-agent tool."""
    console.print("[blue]Upgrading task-agent via uv...[/blue]")
    try:
        subprocess.run(["uv", "tool", "upgrade", "task-agent"], check=True)
        console.print("[bold green]Successfully upgraded task-agent.[/bold green]")
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Error upgrading task-agent: {e}[/red]")
        if os.name == "nt":
            console.print("\n[yellow]Note for Windows users:[/yellow]")
            console.print(
                "If you see 'The process cannot access the file', it means [bold]ta.exe[/bold] is locked."
            )
            console.print(
                "This happens if an MCP session or another terminal is using it."
            )
            console.print(
                "Please [bold]close all chats and other terminals[/bold], then run:"
            )
            console.print("  [cyan]uv tool upgrade task-agent[/cyan]\n")


def cmd_run(console: Console, manager: TaskAgent, slug_part: Optional[str] = None):
    """Run the sidecar worker for an issue."""
    issues = manager.load_mission()
    target = select_issue(console, issues, slug_part, status_filter=["active"])
    if not target:
        if slug_part:
            console.print(f"[red]No active issue found matching '{slug_part}'.[/red]")
        else:
            console.print("[yellow]No active issues found to run.[/yellow]")
        return

    issue_file = manager.find_issue_file(target.slug)
    worker_executable = Path(".ta") / "worker"
    if not worker_executable.exists():
        console.print(f"[red]Sidecar worker not found at {worker_executable}[/red]")
        console.print("[blue]Run 'ta init-worker' to set up a reference worker.[/blue]")
        return

    env = os.environ.copy()
    env["TA_SLUG"] = target.slug
    env["TA_FILE"] = str(issue_file.absolute()) if issue_file else ""
    env["TA_ROOT"] = str(Path.cwd().absolute())

    try:
        subprocess.run([str(worker_executable.absolute())], env=env, check=True)
        console.print(
            f"[bold green]Worker for '{target.slug}' finished successfully.[/bold green]"
        )
    except Exception as e:
        console.print(f"[red]Worker failed: {e}[/red]")


def cmd_init_worker(console: Console, template: str = "adk"):
    """Scaffold a sidecar worker in the current project."""
    target_ta_dir = Path(".ta")
    target_sidecar_dir = target_ta_dir / "sidecars" / f"{template}-worker"

    if target_sidecar_dir.exists():
        console.print(
            f"[yellow]Sidecar worker already exists at {target_sidecar_dir}.[/yellow]"
        )
        return

    pkg_root = Path(__file__).parent.parent.parent
    source_dir = pkg_root / "sidecars" / f"{template}-worker"
    if not source_dir.exists():
        import importlib.resources

        try:
            traversable_root = importlib.resources.files("taskagent")
            source_dir = (
                Path(str(traversable_root)).parent / "sidecars" / f"{template}-worker"
            )
        except Exception:
            pass

    if not source_dir.exists():
        console.print(f"[red]Error: Template '{template}' not found.[/red]")
        return

    target_sidecar_dir.mkdir(parents=True, exist_ok=True)
    for item in source_dir.iterdir():
        if item.is_file():
            shutil.copy(str(item), str(target_sidecar_dir / item.name))

    worker_script = target_ta_dir / "worker"
    script_content = f"#!/usr/bin/env bash\nuv run --project {target_sidecar_dir} python {target_sidecar_dir}/worker.py\n"
    worker_script.write_text(script_content, encoding="utf-8")
    worker_script.chmod(0o755)
    console.print(
        f"[bold green]Successfully initialized {template} worker![/bold green]"
    )


def cmd_mcp():
    """Launch the Model Context Protocol server."""
    from taskagent.mcp import run_mcp_server

    run_mcp_server()


def cmd_init_mcp(console: Console, scope: str = "project"):
    """Register the Task Agent as an MCP server in Gemini CLI."""
    console.print(
        f"[blue]Registering Task Agent as an MCP server ({scope} scope)...[/blue]"
    )

    # We assume 'ta' is in the path.
    command = [
        "gemini",
        "mcp",
        "add",
        "task-agent",
        "ta",
        "mcp",
        "--trust",
        "--scope",
        scope,
    ]

    try:
        subprocess.run(command, check=True)
        console.print(
            "[bold green]Successfully registered Task Agent MCP server![/bold green]"
        )
        console.print(
            f"You can now use task-related tools in any Gemini CLI session within this {scope}."
        )
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Failed to register MCP server: {e}[/red]")
        console.print(
            "[yellow]Ensure you have 'gemini-cli' installed and 'ta' in your PATH.[/yellow]"
        )


def cmd_version(
    console: Console,
    promote: Optional[str] = None,
    tag: bool = False,
    push: bool = False,
):
    """Show project version, promote it, or tag it."""
    try:
        v, source = get_project_version()
        if tag:
            if v == "unknown":
                console.print(
                    "[red]Error: Could not determine project version to tag.[/red]"
                )
                return
            tag_name = f"v{v}"
            console.print(f"[blue]Tagging current commit as {tag_name}...[/blue]")
            subprocess.run(["git", "tag", tag_name], check=True)
            console.print(f"[bold green]Tagged commit as {tag_name}[/bold green]")

            if push:
                console.print(f"[blue]Pushing tag {tag_name} to origin...[/blue]")
                subprocess.run(["git", "push", "origin", tag_name], check=True)
                console.print(
                    f"[bold green]Successfully pushed {tag_name}[/bold green]"
                )
            return

        elif promote:
            if source == "pyproject.toml":
                subprocess.run(
                    [
                        "uv",
                        "run",
                        "bump-my-version",
                        "bump",
                        promote,
                        "--no-commit",
                        "--no-tag",
                    ],
                    check=True,
                )
                if Path("uv.lock").exists():
                    subprocess.run(["uv", "lock"], check=True)
            elif source == "package.json":
                subprocess.run(
                    ["npm", "version", promote, "--no-git-tag-version"], check=True
                )
            new_v, _ = get_project_version()
            console.print(f"[bold green]Promoted to version {new_v}[/bold green]")
        else:
            console.print(
                f"[bold blue]Project Version ({source}):[/bold blue] [cyan]{v}[/cyan]"
            )
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def cmd_restore(
    console: Console, manager: TaskAgent, slug_part: str, to_status: str = "pending"
):
    """Restore a completed issue."""
    try:
        # Search including completed to find the full slug
        issue_file = manager.find_issue_file(slug_part, include_completed=True)
        if not issue_file:
            console.print(f"[red]No issue found matching '{slug_part}'.[/red]")
            return

        # Determine slug from file name or parent dir
        is_dir_based = issue_file.name == "README.md"
        slug = issue_file.parent.name if is_dir_based else issue_file.stem

        issue = manager.restore_issue(slug, to_status=to_status)
        console.print(
            f"[bold green]Issue '{issue.slug}' restored to {to_status}.[/bold green]"
        )
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def cmd_triage(
    console: Console, manager: TaskAgent, search_query: Optional[str] = None
):
    """Interactively reorder and promote tasks."""
    # We might want to triage COMPLETED issues too
    show_completed = False

    def get_display_issues(search: Optional[str] = None, completed: bool = False):
        if completed:
            # Load completed issues from disk since they aren't in mission.usv
            all_issues = []
            completed_root = manager.issues_root / "completed"
            if completed_root.exists():
                for year_dir in sorted(completed_root.iterdir(), reverse=True):
                    if year_dir.is_dir():
                        # File-based
                        for f in sorted(year_dir.glob("*.md")):
                            slug = f.stem
                            all_issues.append(
                                Issue(slug=slug, status="completed", priority=0)
                            )
                        # Directory-based
                        for d in sorted(year_dir.glob("*/README.md")):
                            slug = d.parent.name
                            all_issues.append(
                                Issue(slug=slug, status="completed", priority=0)
                            )
            issues = all_issues
        else:
            issues = manager.sync_mission()

        if search:
            issues = [i for i in issues if search.lower() in i.slug.lower()]
        return issues

    issues = get_display_issues(search_query, show_completed)
    if not issues and not search_query:
        console.print("[yellow]No issues to triage.[/yellow]")
        return

    cursor = 0
    with Live(auto_refresh=False, console=console, screen=True) as live:
        while True:
            # Render
            title = "[bold blue]Triage Mode[/bold blue]"
            if show_completed:
                title = "[bold magenta]Triage Mode (COMPLETED)[/bold magenta]"
            if search_query:
                title += f" [dim](Search: {search_query})[/dim]"

            table = Table(
                title=title,
                box=None,
                show_header=True,
                padding=(0, 2),
            )
            table.add_column("Pos", justify="right", style="dim")
            table.add_column("Status", width=10)
            table.add_column("Slug")

            for i, issue in enumerate(issues):
                style = "bold cyan" if i == cursor else "white"
                if i == cursor:
                    display_slug = f"> [reverse]{issue.slug}[/reverse]"
                else:
                    display_slug = f"  {issue.slug}"

                status_style = "white"
                if issue.status == "active":
                    status_style = "bold green"
                elif issue.status == "pending":
                    status_style = "bold yellow"
                elif issue.status == "draft":
                    status_style = "dim"
                elif issue.status == "completed":
                    status_style = "bold blue"

                table.add_row(
                    str(i + 1) if not show_completed else "-",
                    f"[{status_style}]{issue.status.upper()}[/{status_style}]",
                    display_slug,
                    style=style,
                )

            help_text = "[dim]j/k: move cursor | ctrl+k/j: priority | p: promote | d: demote | c: completed | /: search | q: exit[/dim]"
            if show_completed:
                help_text = "[dim]j/k: move cursor | r: restore to pending | c: toggle completed | /: search | q: exit[/dim]"

            live.update(
                Panel(table, subtitle=help_text, border_style="blue"), refresh=True
            )

            # Input
            key = get_key()

            if key in ["q", "\x1b"]:  # q, esc
                break
            elif key == "\r":  # enter (return)
                break
            elif key == "/":
                live.stop()
                search_query = questionary.text("Search slug:").ask()
                issues = get_display_issues(search_query, show_completed)
                cursor = 0
                live.start()
            elif key == "c":
                show_completed = not show_completed
                issues = get_display_issues(search_query, show_completed)
                cursor = 0
            elif key in ["k", "\x1b[A"]:  # up
                cursor = max(0, cursor - 1)
            elif key in ["j", "\x1b[B"]:  # down
                cursor = min(len(issues) - 1, cursor + 1)
            elif key == "\x0b" and not show_completed:  # ctrl+k
                slug = issues[cursor].slug
                try:
                    manager.prioritize_issue(slug, "up")
                    issues = get_display_issues(search_query, show_completed)
                    cursor = max(0, cursor - 1)
                except Exception:
                    pass
            elif key == "\x0a" and not show_completed:  # ctrl+j (often \n)
                slug = issues[cursor].slug
                try:
                    manager.prioritize_issue(slug, "down")
                    issues = get_display_issues(search_query, show_completed)
                    cursor = min(len(issues) - 1, cursor + 1)
                except Exception:
                    pass
            elif key == "p" and not show_completed:  # promote
                issue = issues[cursor]
                if issue.status == "draft":
                    try:
                        manager.promote_issue(issue.slug)
                        issues = get_display_issues(search_query, show_completed)
                    except Exception:
                        pass
            elif key == "d" and not show_completed:  # demote
                issue = issues[cursor]
                if issue.status == "pending":
                    try:
                        manager.demote_issue(issue.slug)
                        issues = get_display_issues(search_query, show_completed)
                    except Exception:
                        pass
            elif key == "r" and show_completed:  # restore
                target = issues[cursor]
                try:
                    manager.restore_issue(target.slug, to_status="pending")
                    issues = get_display_issues(search_query, show_completed)
                    cursor = min(len(issues) - 1, cursor)
                except Exception:
                    pass


def display_overview(console: Console, manager: TaskAgent):
    """Display a rich overview of the task agent state and available commands."""
    v = get_tool_version()
    repo_info = ""
    if manager.is_dual_repo and manager.mission_root:
        repo_info = (
            f" [bold magenta](Dual-Repo: {manager.mission_root.name})[/bold magenta]"
        )

    console.print(
        Panel(
            f"[bold core]Task Agent[/bold core] [dim]v{v}[/dim]{repo_info}",
            expand=False,
        )
    )

    # Task Summary
    issues = manager.load_mission()
    active = [i for i in issues if i.status == "active"]
    pending = [i for i in issues if i.status == "pending"]
    draft = [i for i in issues if i.status == "draft"]

    stats_table = Table.grid(padding=(0, 2))
    stats_table.add_row(
        f"[bold green]Active:[/bold green] {len(active)}",
        f"[bold yellow]Pending:[/bold yellow] {len(pending)}",
        f"[bold dim]Draft:[/bold dim] {len(draft)}",
    )
    console.print(stats_table)
    console.print()

    # Commands Table
    table = Table(
        title="Available Commands", box=None, show_header=False, padding=(0, 2)
    )
    table.add_column("Command", style="cyan", no_wrap=True)
    table.add_column("Description", style="white")

    commands = [
        ("next", "Show the highest priority task"),
        ("triage", "Interactively reorder and promote tasks"),
        ("list", "List all tasks in the queue (try --json or --text)"),
        ("new", "Create a new task"),
        ("start", "Start a task (creates branch & worktree)"),
        ("done", "Complete a task (moves file & commits)"),
        ("push", "Push the mission repository to origin"),
        ("eject-mission", "Move mission queue to a separate repository"),
        ("", ""),  # Spacer
        ("active", "Mark a task as active without starting a worktree"),
        ("promote", "Promote a draft task to pending"),
        ("demote", "Demote a pending task back to draft"),
        ("up/down", "Adjust task priority"),
        ("ingest", "Scan disk for new markdown tasks"),
        ("", ""),  # Spacer
        ("init-worker", "Scaffold an autonomous sidecar worker"),
        ("init-mcp", "Register Task Agent with Gemini CLI"),
        ("mcp", "Run the MCP server"),
        ("version", "Manage project versioning"),
    ]

    for cmd, desc in commands:
        table.add_row(cmd, desc)

    console.print(table)
    console.print(
        "\n[dim]Run [bold]ta <command> --help[/bold] for detailed options.[/dim]"
    )


def main():
    if "LESS" not in os.environ:
        os.environ["LESS"] = "RFX"
    parser = argparse.ArgumentParser(description="Task Agent CLI")
    parser.add_argument("-V", "--version", action="store_true")
    parser.add_argument("-C", "--config-dir")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("next")
    triage_parser = subparsers.add_parser(
        "triage", help="Interactively reorder and promote tasks"
    )
    triage_parser.add_argument(
        "search", nargs="?", help="Optional search query to filter by slug"
    )

    restore_parser = subparsers.add_parser("restore", help="Restore a completed issue")
    restore_parser.add_argument("slug", help="Slug (or partial slug) of the issue")
    restore_parser.add_argument(
        "-s",
        "--status",
        choices=["pending", "draft", "active"],
        default="pending",
        help="Target status (default: pending)",
    )

    list_parser = subparsers.add_parser("list")
    list_parser.add_argument("--json", action="store_true")
    list_parser.add_argument("--text", action="store_true")
    subparsers.add_parser("ingest")
    subparsers.add_parser("self-up")
    up_parser = subparsers.add_parser("up")
    up_parser.add_argument("slug")
    down_parser = subparsers.add_parser("down")
    down_parser.add_argument("slug")
    promote_parser = subparsers.add_parser("promote")
    promote_parser.add_argument("slug")
    demote_parser = subparsers.add_parser("demote")
    demote_parser.add_argument("slug")
    active_parser = subparsers.add_parser("active")
    active_parser.add_argument("slug", nargs="?")
    start_parser = subparsers.add_parser("start")
    start_parser.add_argument("slug", nargs="?")
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("slug", nargs="?")
    init_parser = subparsers.add_parser("init-worker")
    init_parser.add_argument("--template", default="adk")

    # mcp
    subparsers.add_parser("mcp", help="Run the Model Context Protocol server")

    # init-mcp
    init_mcp_parser = subparsers.add_parser(
        "init-mcp", help="Register as an MCP server in Gemini CLI"
    )
    init_mcp_parser.add_argument(
        "--scope",
        choices=["project", "user"],
        default="project",
        help="Registration scope (default: project)",
    )

    # push
    subparsers.add_parser("push", help="Push the mission repository to origin")

    # eject-mission
    eject_parser = subparsers.add_parser(
        "eject-mission", help="Move mission queue to a separate repository"
    )
    eject_parser.add_argument(
        "--public", action="store_true", help="Make the new mission repo public"
    )

    done_parser = subparsers.add_parser("done")
    done_parser.add_argument("slug", nargs="?")
    done_parser.add_argument("-m", "--message")
    done_parser.add_argument("--no-commit", action="store_true")
    done_parser.add_argument(
        "--push", action="store_true", help="Push the mission repo after completion"
    )

    new_parser = subparsers.add_parser("new")
    new_parser.add_argument("title")
    new_parser.add_argument("-b", "--body", default="")
    new_parser.add_argument("-c", "--criteria", help="Completion criteria")
    new_parser.add_argument("-d", "--draft", action="store_true")
    new_parser.add_argument("--dir", action="store_true")
    new_parser.add_argument("--depends-on")
    version_parser = subparsers.add_parser("version")
    v_sub = version_parser.add_subparsers(dest="version_command")
    p_v = v_sub.add_parser("promote")
    p_v.add_argument("part", choices=["major", "minor", "patch"])
    tag_parser = v_sub.add_parser("tag")
    tag_parser.add_argument(
        "--push", action="store_true", help="Push the tag to origin"
    )

    args = parser.parse_args()
    console = Console()
    if args.version:
        console.print(f"task-agent version {get_tool_version()}")
        return

    manager = discover(Path(args.config_dir) if args.config_dir else None)

    if args.command == "next":
        cmd_next(console, manager)
    elif args.command == "triage":
        cmd_triage(console, manager, search_query=args.search)
    elif args.command == "restore":
        cmd_restore(console, manager, args.slug, to_status=args.status)
    elif args.command == "list":
        fmt = "table"
        if args.json:
            fmt = "json"
        elif args.text:
            fmt = "text"
        cmd_list(console, manager, fmt)
    elif args.command == "ingest":
        cmd_ingest(console, manager)
    elif args.command == "self-up":
        cmd_self_up(console)
    elif args.command == "up":
        cmd_prioritize(console, manager, args.slug, "up")
    elif args.command == "down":
        cmd_prioritize(console, manager, args.slug, "down")
    elif args.command == "promote":
        cmd_promote(console, manager, args.slug)
    elif args.command == "demote":
        cmd_demote(console, manager, args.slug)
    elif args.command == "active":
        cmd_active(console, manager, args.slug)
    elif args.command == "start":
        cmd_start(console, manager, args.slug)
    elif args.command == "run":
        cmd_run(console, manager, args.slug)
    elif args.command == "init-worker":
        cmd_init_worker(console, args.template)
    elif args.command == "mcp":
        cmd_mcp()
    elif args.command == "init-mcp":
        cmd_init_mcp(console, scope=args.scope)
    elif args.command == "push":
        cmd_push(console, manager)
    elif args.command == "eject-mission":
        cmd_eject_mission(console, manager, public=args.public)
    elif args.command == "done":
        cmd_done(
            console,
            manager,
            args.slug,
            args.message,
            not args.no_commit,
            args.push,
        )
    elif args.command == "new":
        cmd_new(
            console,
            manager,
            args.title,
            args.body,
            args.draft,
            args.depends_on,
            args.dir,
            args.criteria,
        )
    elif args.command == "version":
        if args.version_command == "promote":
            cmd_version(console, args.part)
        elif args.version_command == "tag":
            cmd_version(console, tag=True, push=args.push)
        else:
            cmd_version(console)
    else:
        display_overview(console, manager)


if __name__ == "__main__":
    main()
