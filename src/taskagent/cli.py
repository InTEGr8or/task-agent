from typing import List, Optional, Tuple
from pathlib import Path
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
import sys
import argparse
from datetime import datetime
import re
import subprocess
import os
import json
import importlib.metadata
import shutil

from taskagent.models.issue import Issue, USV_DELIM


def get_config_paths(config_dir: Optional[str] = None) -> Tuple[Path, Path]:
    """Get the issues root and mission path based on config or environment."""
    if config_dir:
        issues_root = Path(config_dir)
    else:
        # Check environment variable, then default to docs/issues
        env_dir = os.environ.get("TA_CONFIG_DIR")
        issues_root = Path(env_dir) if env_dir else Path("docs/issues")

    mission_path = issues_root / "mission.usv"
    return issues_root, mission_path


def ensure_issues_dir(issues_root: Path):
    """Ensure the issues directory and its subdirectories exist."""
    for subdir in ["pending", "draft", "active", "completed"]:
        (issues_root / subdir).mkdir(parents=True, exist_ok=True)


def slugify(text: str) -> str:
    """Convert text to a slug."""
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text)
    return text.strip("-")


def find_issue_file(issues_root: Path, slug: str) -> Optional[Path]:
    """Find the issue markdown file by slug.
    Checks for slug.md OR slug/README.md.
    """
    if not issues_root.exists():
        return None

    search_dirs = [
        d for d in issues_root.iterdir() if d.is_dir() and d.name != "completed"
    ]

    for directory in search_dirs:
        # 1. Check for file-based issue: slug.md
        issue_file = directory / f"{slug}.md"
        if issue_file.exists():
            return issue_file

        # 2. Check for directory-based issue: slug/README.md
        issue_dir_file = directory / slug / "README.md"
        if issue_dir_file.exists():
            return issue_dir_file

    return None


def load_mission(issues_root: Path, mission_path: Path) -> List[Issue]:
    if not mission_path.exists():
        return []

    issues = []
    with mission_path.open("r", encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            parts = line.split(USV_DELIM)
            if len(parts) >= 1:
                try:
                    slug = parts[0]
                    deps = []
                    if len(parts) >= 2 and parts[1]:
                        deps = [d.strip() for d in parts[1].split(",") if d.strip()]

                    # Determine status from file location
                    issue_file = find_issue_file(issues_root, slug)
                    status = "unknown"
                    if issue_file:
                        # If it's slug/README.md, status is parent of parent
                        if issue_file.name == "README.md":
                            status = issue_file.parent.parent.name
                        else:
                            status = issue_file.parent.name

                    issues.append(
                        Issue(slug=slug, dependencies=deps, priority=i, status=status)
                    )
                except (ValueError, IndexError):
                    continue
    return issues


def save_mission(mission_path: Path, issues: List[Issue]):
    """Save the list of issues back to mission.usv."""
    mission_path.parent.mkdir(parents=True, exist_ok=True)
    with mission_path.open("w", encoding="utf-8", newline="\n") as f:
        for issue in issues:
            f.write(issue.to_usv() + "\n")


def get_git_commit() -> str:
    """Get the short git commit hash."""
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except subprocess.CalledProcessError:
        return "unknown"


def get_tool_version() -> str:
    """Read the task-agent tool version."""
    try:
        return importlib.metadata.version("task-agent")
    except Exception:
        return "unknown"


def get_project_version() -> Tuple[str, Optional[str]]:
    """Read the current project version from pyproject.toml or package.json."""
    # Check pyproject.toml
    if Path("pyproject.toml").exists():
        try:
            with open("pyproject.toml", "r") as f:
                content = f.read()
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


def cmd_next(console: Console, issues_root: Path, mission_path: Path):
    """Show the top issue."""
    issues = load_mission(issues_root, mission_path)
    if not issues:
        console.print(f"[yellow]No issues found in {mission_path}[/yellow]")
        return

    next_issue = issues[0]
    issue_file = find_issue_file(issues_root, next_issue.slug)

    if not issue_file:
        console.print(f"[red]Issue file not found for slug: {next_issue.slug}[/red]")
        sys.exit(1)

    with issue_file.open("r", encoding="utf-8") as f:
        content = f.read()

    deps_info = ""
    if next_issue.dependencies:
        deps_info = f"[bold blue]DEPENDS ON:[/bold blue] [yellow]{', '.join(next_issue.dependencies)}[/yellow]\n"

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
    console: Console, issues_root: Path, mission_path: Path, slug: Optional[str] = None
):
    """Mark an issue as done."""
    issues = load_mission(issues_root, mission_path)
    if not issues:
        console.print(f"[yellow]No issues found in {mission_path}[/yellow]")
        return

    if slug is None:
        target_issue: Optional[Issue] = issues[0] if issues else None
    else:
        target_issue = next((i for i in issues if i.slug == slug), None)

    if not target_issue:
        if slug:
            console.print(
                f"[red]Issue with slug '{slug}' not found in mission.usv[/red]"
            )
        sys.exit(1)

    issue_file = find_issue_file(issues_root, target_issue.slug)
    if not issue_file:
        console.print(f"[red]Issue file not found for slug: {target_issue.slug}[/red]")
        sys.exit(1)

    # Detect if directory-based
    is_dir_based = issue_file.name == "README.md"
    source_to_move = issue_file.parent if is_dir_based else issue_file

    commit_hash = get_git_commit()
    year = datetime.now().year
    completed_dir = issues_root / "completed" / str(year)
    completed_dir.mkdir(parents=True, exist_ok=True)

    dest_path = completed_dir / source_to_move.name

    console.print(f"[green]Moving {source_to_move} to {dest_path}...[/green]")

    # If it's a file, we can append the commit hash easily.
    # If it's a directory, we append it to the README.md.
    with issue_file.open("r", encoding="utf-8") as f:
        content = f.read()

    if not content.endswith("\n"):
        content += "\n"
    content += f"\n---\n**Completed in commit:** `{commit_hash}`\n"

    if is_dir_based:
        # Move directory then write updated README
        if dest_path.exists():
            shutil.rmtree(dest_path)
        shutil.move(str(source_to_move), str(dest_path))
        with (dest_path / "README.md").open("w", encoding="utf-8") as f:
            f.write(content)
    else:
        # Just write to destination and unlink source
        with dest_path.open("w", encoding="utf-8") as f:
            f.write(content)
        issue_file.unlink()

    new_issues = [i for i in issues if i.slug != target_issue.slug]
    save_mission(mission_path, new_issues)
    console.print(
        f"[bold green]Issue '{target_issue.slug}' marked as done and removed from mission.usv[/bold green]"
    )

    # Auto-promote patch version if we are in a repo that supports it
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
    issues_root: Path,
    mission_path: Path,
    title: str,
    body: str,
    draft: bool,
    depends_on: Optional[str] = None,
    as_dir: bool = False,
):
    """Create a new issue."""
    slug = slugify(title)
    status = "draft" if draft else "pending"
    target_dir = issues_root / status
    target_dir.mkdir(parents=True, exist_ok=True)

    if as_dir:
        issue_container = target_dir / slug
        issue_container.mkdir(parents=True, exist_ok=True)
        issue_file = issue_container / "README.md"
    else:
        issue_file = target_dir / f"{slug}.md"

    if issue_file.exists():
        console.print(f"[red]Error: Issue file already exists: {issue_file}[/red]")
        sys.exit(1)

    deps = []
    if depends_on:
        deps = [d.strip() for d in depends_on.split(",") if d.strip()]

    # Write the markdown file
    with issue_file.open("w", encoding="utf-8") as f:
        f.write(f"# {title}\n\n")
        if deps:
            f.write(f"**Depends on:** {', '.join(deps)}\n\n")
        f.write(f"{body}\n")

    # Update mission.usv
    issues = load_mission(issues_root, mission_path)

    new_issue = Issue(
        slug=slug, dependencies=deps, status=status, priority=len(issues) + 1
    )

    issues.append(new_issue)
    save_mission(mission_path, issues)

    console.print(f"[bold green]Created new issue: {slug}[/bold green]")
    console.print(f"File: {issue_file}")
    if deps:
        console.print(f"Depends on: {', '.join(deps)}")


def cmd_list(console: Console, issues_root: Path, mission_path: Path):
    """List all issues in mission.usv."""
    issues = load_mission(issues_root, mission_path)
    if not issues:
        console.print(f"[yellow]No issues found in {mission_path}[/yellow]")
        return

    table = Table(title="Task Queue")
    table.add_column("Priority", justify="right", style="cyan")
    table.add_column("Status", style="magenta")
    table.add_column("Slug", style="green")
    table.add_column("Depends On", style="yellow")
    table.add_column("Location", style="dim")

    for issue in issues:
        issue_file = find_issue_file(issues_root, issue.slug)
        location = str(issue_file) if issue_file else "[red]MISSING[/red]"

        status_str = issue.status
        if status_str == "pending":
            status_str = f"[bold yellow]{status_str}[/bold yellow]"
        elif status_str == "draft":
            status_str = f"[dim]{status_str}[/dim]"
        elif status_str == "active":
            status_str = f"[bold green]{status_str}[/bold green]"

        table.add_row(
            str(issue.priority),
            status_str,
            issue.slug,
            ", ".join(issue.dependencies),
            location,
        )

    console.print(table)


def cmd_ingest(console: Console, issues_root: Path, mission_path: Path):
    """Ingest existing markdown files into mission.usv."""
    ensure_issues_dir(issues_root)

    # 1. Load existing issues (preserving order)
    existing_issues = load_mission(issues_root, mission_path)
    existing_slugs = {i.slug for i in existing_issues}

    # 2. Identify removed issues (those in USV but missing from disk)
    present_issues = [i for i in existing_issues if i.status != "unknown"]

    # 3. Scan disk for new files
    new_issues = []
    for status in ["pending", "draft", "active"]:
        status_dir = issues_root / status
        if not status_dir.exists():
            continue

        # File-based
        for issue_file in sorted(status_dir.glob("*.md")):
            slug = issue_file.stem
            if slug not in existing_slugs:
                deps = extract_deps(issue_file)
                new_issues.append(Issue(slug=slug, dependencies=deps, status=status))
                existing_slugs.add(slug)

        # Directory-based
        for readme_file in sorted(status_dir.glob("*/README.md")):
            slug = readme_file.parent.name
            if slug not in existing_slugs:
                deps = extract_deps(readme_file)
                new_issues.append(Issue(slug=slug, dependencies=deps, status=status))
                existing_slugs.add(slug)

    # 4. Combine: Existing ordered items + newly found items at the end
    final_issues = present_issues + new_issues

    # 5. Save mission.usv
    save_mission(mission_path, final_issues)
    console.print(
        f"[bold green]Ingested {len(new_issues)} new issues, removed {len(existing_issues) - len(present_issues)} missing ones.[/bold green]"
    )

    # 6. Create/Update datapackage.json
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

    dp_path = issues_root / "datapackage.json"
    with dp_path.open("w", encoding="utf-8") as f:
        json.dump(datapackage, f, indent=2)
    console.print(f"[bold green]Updated {dp_path}[/bold green]")


def extract_deps(file_path: Path) -> List[str]:
    """Helper to extract dependencies from a markdown file."""
    try:
        with file_path.open("r", encoding="utf-8") as f:
            content = f.read()
            match = re.search(r"\*\*Depends on:\*\*\s*(.*)", content)
            if match:
                return [d.strip() for d in match.group(1).split(",") if d.strip()]
    except Exception:
        pass
    return []


def cmd_version(console: Console, promote: Optional[str] = None, tag: bool = False):
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
            return

        if promote:
            if promote not in ["major", "minor", "patch"]:
                console.print(
                    f"[red]Invalid version part: {promote}. Use major, minor, or patch.[/red]"
                )
                return

            console.print(f"[blue]Promoting {promote} version...[/blue]")

            if source == "pyproject.toml":
                # Check for bump-my-version in pyproject.toml
                with open("pyproject.toml", "r") as f:
                    if "tool.bumpversion" in f.read():
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
                        # Sync uv.lock
                        if Path("uv.lock").exists():
                            console.print("[blue]Syncing uv.lock...[/blue]")
                            subprocess.run(["uv", "lock"], check=True)
                    else:
                        console.print(
                            "[yellow]Warning: pyproject.toml found but [tool.bumpversion] is not configured.[/yellow]"
                        )
                        return
            elif source == "package.json":
                # Use npm version
                subprocess.run(
                    ["npm", "version", promote, "--no-git-tag-version"], check=True
                )
            else:
                console.print(
                    "[red]Error: Could not find a version file to promote (pyproject.toml or package.json).[/red]"
                )
                return

            new_v, _ = get_project_version()
            console.print(f"[bold green]Promoted to version {new_v}[/bold green]")
        else:
            if source:
                console.print(
                    f"[bold blue]Project Version ({source}):[/bold blue] [cyan]{v}[/cyan]"
                )
                console.print("\nSubcommands:")
                console.print("  [bold]ta version promote [major|minor|patch][/bold]")
                console.print("  [bold]ta version tag[/bold]")
            else:
                console.print(
                    "[yellow]No project version file found (pyproject.toml or package.json).[/yellow]"
                )

    except Exception as e:
        console.print(f"[red]Error managing version: {e}[/red]")


def main():
    parser = argparse.ArgumentParser(description="Task Agent CLI")
    parser.add_argument(
        "-V", "--version", action="store_true", help="Show task-agent tool version"
    )
    parser.add_argument(
        "-C",
        "--config-dir",
        help="Path to the issues directory (default: docs/issues or TA_CONFIG_DIR)",
    )
    subparsers = parser.add_subparsers(dest="command")

    # next
    subparsers.add_parser("next", help="Show the top issue")

    # list
    subparsers.add_parser("list", help="List all issues")

    # ingest
    subparsers.add_parser(
        "ingest", help="Ingest existing markdown files into mission.usv"
    )

    # done
    done_parser = subparsers.add_parser("done", help="Mark an issue as done")
    done_parser.add_argument(
        "slug",
        nargs="?",
        help="Slug of the issue to mark as done (defaults to top issue)",
    )

    # new
    new_parser = subparsers.add_parser("new", help="Create a new issue")
    new_parser.add_argument("-t", "--title", required=True, help="Title of the issue")
    new_parser.add_argument("-b", "--body", default="", help="Body of the issue")
    new_parser.add_argument(
        "-d", "--draft", action="store_true", help="Create as a draft"
    )
    new_parser.add_argument(
        "--dir", action="store_true", help="Create as a directory-based issue"
    )
    new_parser.add_argument(
        "--depends-on", help="Comma separated list of issue slugs this issue depends on"
    )

    # version
    version_parser = subparsers.add_parser(
        "version", help="Show or promote project version"
    )
    version_subparsers = version_parser.add_subparsers(dest="version_command")
    promote_parser = version_subparsers.add_parser(
        "promote", help="Promote semantic version"
    )
    promote_parser.add_argument(
        "part",
        choices=["major", "minor", "patch"],
        help="Part of the version to promote",
    )
    version_subparsers.add_parser("tag", help="Tag current commit with current version")

    args = parser.parse_args()
    console = Console()

    if args.version:
        console.print(f"task-agent version {get_tool_version()}")
        return

    issues_root, mission_path = get_config_paths(args.config_dir)

    if args.command == "next":
        cmd_next(console, issues_root, mission_path)
    elif args.command == "list":
        cmd_list(console, issues_root, mission_path)
    elif args.command == "ingest":
        cmd_ingest(console, issues_root, mission_path)
    elif args.command == "done":
        cmd_done(console, issues_root, mission_path, args.slug)
    elif args.command == "new":
        cmd_new(
            console,
            issues_root,
            mission_path,
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
