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

def slugify(text: str) -> str:
    """Convert text to a slug."""
    text = text.lower()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_-]+', '-', text)
    return text.strip('-')

def load_mission(mission_path: Path) -> List[Issue]:
    if not mission_path.exists():
        return []
    
    issues = []
    with mission_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split(USV_DELIM)
            if len(parts) >= 3:
                try:
                    deps = []
                    if len(parts) >= 4 and parts[3]:
                        deps = [d.strip() for d in parts[3].split(",") if d.strip()]
                        
                    issues.append(Issue(
                        slug=parts[0],
                        priority=int(parts[1]),
                        status=parts[2],
                        dependencies=deps
                    ))
                except (ValueError, IndexError):
                    continue
    return issues

def save_mission(mission_path: Path, issues: List[Issue]):
    """Save the list of issues back to mission.usv."""
    mission_path.parent.mkdir(parents=True, exist_ok=True)
    with mission_path.open("w", encoding="utf-8", newline='\r\n') as f:
        for issue in issues:
            f.write(issue.to_usv() + "\r\n")

def find_issue_file(issues_root: Path, slug: str) -> Optional[Path]:
    """Find the issue markdown file by slug in issues_root excluding completed/."""
    if not issues_root.exists():
        return None
        
    search_dirs = [d for d in issues_root.iterdir() if d.is_dir() and d.name != "completed"]
    
    for directory in search_dirs:
        issue_file = directory / f"{slug}.md"
        if issue_file.exists():
            return issue_file
            
    return None

def get_git_commit() -> str:
    """Get the short git commit hash."""
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], 
            stderr=subprocess.DEVNULL,
            text=True
        ).strip()
    except subprocess.CalledProcessError:
        return "unknown"

def get_current_version() -> str:
    """Read the current version from pyproject.toml."""
    try:
        import importlib.metadata
        return importlib.metadata.version("task-agent")
    except Exception:
        return "unknown"

def cmd_next(console: Console, issues_root: Path, mission_path: Path):
    """Show the top issue."""
    issues = load_mission(mission_path)
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

    console.print(Panel(
        f"[bold blue]NEXT ISSUE:[/bold blue] [cyan]{next_issue.slug}[/cyan]\n"
        f"[bold blue]PRIORITY:[/bold blue] {next_issue.priority} | "
        f"[bold blue]STATUS:[/bold blue] {next_issue.status}\n"
        f"{deps_info}"
        f"[bold blue]FILE:[/bold blue] {issue_file}",
        title="Task Agent",
        expand=False
    ))
    
    md = Markdown(content)
    console.print(md)

def cmd_done(console: Console, issues_root: Path, mission_path: Path, slug: Optional[str] = None):
    """Mark an issue as done."""
    issues = load_mission(mission_path)
    if not issues:
        console.print(f"[yellow]No issues found in {mission_path}[/yellow]")
        return

    if slug is None:
        target_issue: Optional[Issue] = issues[0] if issues else None
    else:
        target_issue = next((i for i in issues if i.slug == slug), None)

    if not target_issue:
        if slug:
            console.print(f"[red]Issue with slug '{slug}' not found in mission.usv[/red]")
        sys.exit(1)

    issue_file = find_issue_file(issues_root, target_issue.slug)
    if not issue_file:
        console.print(f"[red]Issue file not found for slug: {target_issue.slug}[/red]")
        sys.exit(1)

    commit_hash = get_git_commit()
    year = datetime.now().year
    completed_dir = issues_root / "completed" / str(year)
    completed_dir.mkdir(parents=True, exist_ok=True)
    
    dest_path = completed_dir / f"{target_issue.slug}.md"
    
    console.print(f"[green]Moving {issue_file} to {dest_path}...[/green]")
    
    with issue_file.open("r", encoding="utf-8") as f:
        content = f.read()
    
    if not content.endswith("\n"):
        content += "\n"
    content += f"\n---\n**Completed in commit:** `{commit_hash}`\n"
    
    with dest_path.open("w", encoding="utf-8") as f:
        f.write(content)
        
    issue_file.unlink()

    new_issues = [i for i in issues if i.slug != target_issue.slug]
    save_mission(mission_path, new_issues)
    console.print(f"[bold green]Issue '{target_issue.slug}' marked as done and removed from mission.usv[/bold green]")

    console.print("[blue]Auto-promoting patch version...[/blue]")
    try:
        cmd_version(console, promote="patch")
    except Exception as e:
        console.print(f"[yellow]Warning: Could not auto-promote version: {e}[/yellow]")

def cmd_new(console: Console, issues_root: Path, mission_path: Path, title: str, body: str, draft: bool, depends_on: Optional[str] = None):
    """Create a new issue."""
    slug = slugify(title)
    status = "draft" if draft else "pending"
    target_dir = issues_root / status
    target_dir.mkdir(parents=True, exist_ok=True)
    
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
    issues = load_mission(mission_path)
    
    max_priority = max([i.priority for i in issues], default=0)
    new_priority = max_priority + 1
    
    new_issue = Issue(
        slug=slug,
        priority=new_priority,
        status=status,
        dependencies=deps
    )
    
    issues.append(new_issue)
    save_mission(mission_path, issues)
    
    console.print(f"[bold green]Created new issue: {slug}[/bold green]")
    console.print(f"File: {issue_file}")
    console.print(f"Priority: {new_priority}")
    if deps:
        console.print(f"Depends on: {', '.join(deps)}")

def cmd_list(console: Console, issues_root: Path, mission_path: Path):
    """List all issues in mission.usv, sorted by status (pending first) then priority."""
    issues = load_mission(mission_path)
    if not issues:
        console.print(f"[yellow]No issues found in {mission_path}[/yellow]")
        return

    sorted_issues = sorted(issues, key=lambda x: (x.status != "pending", x.priority))

    table = Table(title="Task Queue")
    table.add_column("Priority", justify="right", style="cyan")
    table.add_column("Status", style="magenta")
    table.add_column("Slug", style="green")
    table.add_column("Depends On", style="yellow")
    table.add_column("Location", style="dim")

    for issue in sorted_issues:
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
            location
        )

    console.print(table)

def cmd_version(console: Console, promote: Optional[str] = None, tag: bool = False):
    """Show version, promote it, or tag it."""
    try:
        if tag:
            v = get_current_version()
            tag_name = f"v{v}"
            console.print(f"[blue]Tagging current commit as {tag_name}...[/blue]")
            subprocess.run(["git", "tag", tag_name], check=True)
            console.print(f"[bold green]Tagged commit as {tag_name}[/bold green]")
            return

        if promote:
            if promote not in ["major", "minor", "patch"]:
                console.print(f"[red]Invalid version part: {promote}. Use major, minor, or patch.[/red]")
                return
            
            console.print(f"[blue]Promoting {promote} version...[/blue]")
            if not Path("pyproject.toml").exists():
                console.print("[red]Error: pyproject.toml not found. Version promotion only works within the task-agent repository.[/red]")
                return

            subprocess.run(["uv", "run", "bump-my-version", "bump", promote, "--no-commit", "--no-tag"], check=True)
            
            new_v = get_current_version()
            console.print(f"[bold green]Promoted to version {new_v}[/bold green]")
        else:
            v = get_current_version()
            console.print(f"[bold blue]Current Version:[/bold blue] [cyan]{v}[/cyan]")
            console.print("\nSubcommands:")
            console.print("  [bold]ta version promote [major|minor|patch][/bold]")
            console.print("  [bold]ta version tag[/bold]")

    except Exception as e:
        console.print(f"[red]Error managing version: {e}[/red]")

def main():
    parser = argparse.ArgumentParser(description="Task Agent CLI")
    parser.add_argument("-C", "--config-dir", help="Path to the issues directory (default: docs/issues or TA_CONFIG_DIR)")
    subparsers = parser.add_subparsers(dest="command")

    # next
    subparsers.add_parser("next", help="Show the top issue")
    
    # list
    subparsers.add_parser("list", help="List all issues")
    
    # done
    done_parser = subparsers.add_parser("done", help="Mark an issue as done")
    done_parser.add_argument("slug", nargs="?", help="Slug of the issue to mark as done (defaults to top issue)")

    # new
    new_parser = subparsers.add_parser("new", help="Create a new issue")
    new_parser.add_argument("-t", "--title", required=True, help="Title of the issue")
    new_parser.add_argument("-b", "--body", default="", help="Body of the issue")
    new_parser.add_argument("-d", "--draft", action="store_true", help="Create as a draft")
    new_parser.add_argument("--depends-on", help="Comma separated list of issue slugs this issue depends on")

    # version
    version_parser = subparsers.add_parser("version", help="Show or promote version")
    version_subparsers = version_parser.add_subparsers(dest="version_command")
    promote_parser = version_subparsers.add_parser("promote", help="Promote semantic version")
    promote_parser.add_argument("part", choices=["major", "minor", "patch"], help="Part of the version to promote")
    version_subparsers.add_parser("tag", help="Tag current commit with current version")

    args = parser.parse_args()
    console = Console()
    
    issues_root, mission_path = get_config_paths(args.config_dir)

    if args.command == "next":
        cmd_next(console, issues_root, mission_path)
    elif args.command == "list":
        cmd_list(console, issues_root, mission_path)
    elif args.command == "done":
        cmd_done(console, issues_root, mission_path, args.slug)
    elif args.command == "new":
        cmd_new(console, issues_root, mission_path, args.title, args.body, args.draft, args.depends_on)
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
