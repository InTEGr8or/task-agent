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

from taskagent.models.issue import Issue
from taskagent.manager import TaskManager


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


def cmd_next(console: Console, manager: TaskManager):
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
    manager: TaskManager,
    slug_part: Optional[str] = None,
    commit_message: Optional[str] = None,
    should_commit: bool = True,
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
        commit_hash = manager.complete_issue(
            target_issue.slug, commit_message, should_commit
        )
        console.print(
            f"[bold green]Issue '{target_issue.slug}' marked as done and removed from mission.usv[/bold green]"
        )
        if should_commit and commit_hash != "unknown":
            console.print(
                f"[bold green]Successfully committed work as {commit_hash}.[/bold green]"
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


def cmd_new(
    console: Console,
    manager: TaskManager,
    title: str,
    body: str,
    draft: bool,
    depends_on: Optional[str] = None,
    as_dir: bool = False,
):
    """Create a new issue."""
    try:
        issue = manager.create_issue(title, body, draft, depends_on, as_dir)
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
    manager: TaskManager,
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


def cmd_ingest(console: Console, manager: TaskManager):
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


def cmd_promote(console: Console, manager: TaskManager, slug_part: str):
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


def cmd_active(
    console: Console,
    manager: TaskManager,
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


def cmd_start(console: Console, manager: TaskManager, slug_part: Optional[str] = None):
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
    console: Console, manager: TaskManager, slug_part: str, direction: str
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


def cmd_run(console: Console, manager: TaskManager, slug_part: Optional[str] = None):
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


def cmd_version(console: Console, promote: Optional[str] = None, tag: bool = False):
    """Show project version, promote it, or tag it."""
    try:
        v, source = get_project_version()
        if tag:
            tag_name = f"v{v}"
            subprocess.run(["git", "tag", tag_name], check=True)
            console.print(f"[bold green]Tagged commit as {tag_name}[/bold green]")
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


def main():
    if "LESS" not in os.environ:
        os.environ["LESS"] = "RFX"
    parser = argparse.ArgumentParser(description="Task Agent CLI")
    parser.add_argument("-V", "--version", action="store_true")
    parser.add_argument("-C", "--config-dir")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("next")
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

    done_parser = subparsers.add_parser("done")

    done_parser.add_argument("slug", nargs="?")
    done_parser.add_argument("-m", "--message")
    done_parser.add_argument("--no-commit", action="store_true")
    new_parser = subparsers.add_parser("new")
    new_parser.add_argument("title")
    new_parser.add_argument("-b", "--body", default="")
    new_parser.add_argument("-d", "--draft", action="store_true")
    new_parser.add_argument("--dir", action="store_true")
    new_parser.add_argument("--depends-on")
    version_parser = subparsers.add_parser("version")
    v_sub = version_parser.add_subparsers(dest="version_command")
    p_v = v_sub.add_parser("promote")
    p_v.add_argument("part", choices=["major", "minor", "patch"])
    v_sub.add_parser("tag")

    args = parser.parse_args()
    console = Console()
    if args.version:
        console.print(f"task-agent version {get_tool_version()}")
        return

    manager = TaskManager(args.config_dir)

    if args.command == "next":
        cmd_next(console, manager)
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
    elif args.command == "done":
        cmd_done(console, manager, args.slug, args.message, not args.no_commit)
    elif args.command == "new":
        cmd_new(
            console,
            manager,
            args.title,
            args.body,
            args.draft,
            args.depends_on,
            args.dir,
        )
    elif args.command == "version":
        if args.version_command == "promote":
            cmd_version(console, args.part)
        elif args.version_command == "tag":
            cmd_version(console, tag=True)
        else:
            cmd_version(console)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
