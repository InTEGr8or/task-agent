from typing import List, Optional
from pathlib import Path
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
import sys
import argparse
from datetime import datetime
import re

from taskagent.models.issue import Issue, USV_DELIM

# Constants
ISSUES_ROOT = Path("docs/issues")
MISSION_PATH = ISSUES_ROOT / "mission.usv"

def slugify(text: str) -> str:
    """Convert text to a slug."""
    text = text.lower()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_-]+', '-', text)
    return text.strip('-')

def load_mission() -> List[Issue]:
    if not MISSION_PATH.exists():
        return []
    
    issues = []
    with MISSION_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split(USV_DELIM)
            if len(parts) >= 3:
                try:
                    issues.append(Issue(
                        slug=parts[0],
                        priority=int(parts[1]),
                        status=parts[2]
                    ))
                except (ValueError, IndexError):
                    continue
    return issues

def save_mission(issues: List[Issue]):
    """Save the list of issues back to mission.usv."""
    with MISSION_PATH.open("w", encoding="utf-8", newline='\r\n') as f:
        for issue in issues:
            f.write(issue.to_usv() + "\r\n")

def find_issue_file(slug: str) -> Optional[Path]:
    """Find the issue markdown file by slug in docs/issues/ excluding completed/."""
    search_dirs = [d for d in ISSUES_ROOT.iterdir() if d.is_dir() and d.name != "completed"]
    
    for directory in search_dirs:
        issue_file = directory / f"{slug}.md"
        if issue_file.exists():
            return issue_file
            
    return None

def cmd_next(console: Console):
    """Show the top issue."""
    issues = load_mission()
    if not issues:
        console.print("[yellow]No issues found in mission.usv[/yellow]")
        return
        
    next_issue = issues[0]
    issue_file = find_issue_file(next_issue.slug)
    
    if not issue_file:
        console.print(f"[red]Issue file not found for slug: {next_issue.slug}[/red]")
        sys.exit(1)
        
    with issue_file.open("r", encoding="utf-8") as f:
        content = f.read()
        
    console.print(Panel(
        f"[bold blue]NEXT ISSUE:[/bold blue] [cyan]{next_issue.slug}[/cyan]\n"
        f"[bold blue]PRIORITY:[/bold blue] {next_issue.priority} | "
        f"[bold blue]STATUS:[/bold blue] {next_issue.status}\n"
        f"[bold blue]FILE:[/bold blue] {issue_file}",
        title="Task Agent",
        expand=False
    ))
    
    md = Markdown(content)
    console.print(md)

def cmd_done(console: Console, slug: Optional[str] = None):
    """Mark an issue as done."""
    issues = load_mission()
    if not issues:
        console.print("[yellow]No issues found in mission.usv[/yellow]")
        return

    if slug is None:
        target_issue: Optional[Issue] = issues[0] if issues else None
    else:
        target_issue = next((i for i in issues if i.slug == slug), None)

    if not target_issue:
        if slug:
            console.print(f"[red]Issue with slug '{slug}' not found in mission.usv[/red]")
        sys.exit(1)

    issue_file = find_issue_file(target_issue.slug)
    if not issue_file:
        console.print(f"[red]Issue file not found for slug: {target_issue.slug}[/red]")
        sys.exit(1)

    year = datetime.now().year
    completed_dir = ISSUES_ROOT / "completed" / str(year)
    completed_dir.mkdir(parents=True, exist_ok=True)
    
    dest_path = completed_dir / f"{target_issue.slug}.md"
    
    console.print(f"[green]Moving {issue_file} to {dest_path}...[/green]")
    issue_file.rename(dest_path)

    new_issues = [i for i in issues if i.slug != target_issue.slug]
    save_mission(new_issues)
    console.print(f"[bold green]Issue '{target_issue.slug}' marked as done and removed from mission.usv[/bold green]")

def cmd_new(console: Console, title: str, body: str, draft: bool):
    """Create a new issue."""
    slug = slugify(title)
    status = "draft" if draft else "pending"
    target_dir = ISSUES_ROOT / status
    target_dir.mkdir(parents=True, exist_ok=True)
    
    issue_file = target_dir / f"{slug}.md"
    if issue_file.exists():
        console.print(f"[red]Error: Issue file already exists: {issue_file}[/red]")
        sys.exit(1)
        
    # Write the markdown file
    with issue_file.open("w", encoding="utf-8") as f:
        f.write(f"# {title}\n\n{body}\n")
    
    # Update mission.usv
    issues = load_mission()
    
    # Determine priority: max + 1
    max_priority = max([i.priority for i in issues], default=0)
    new_priority = max_priority + 1
    
    new_issue = Issue(
        slug=slug,
        priority=new_priority,
        status=status
    )
    
    issues.append(new_issue)
    save_mission(issues)
    
    console.print(f"[bold green]Created new issue: {slug}[/bold green]")
    console.print(f"File: {issue_file}")
    console.print(f"Priority: {new_priority}")

def cmd_list(console: Console):
    """List all issues in mission.usv, sorted by status (pending first) then priority."""
    issues = load_mission()
    if not issues:
        console.print("[yellow]No issues found in mission.usv[/yellow]")
        return

    # Sort: pending first, then by priority
    sorted_issues = sorted(issues, key=lambda x: (x.status != "pending", x.priority))

    table = Table(title="Task Queue")
    table.add_column("Priority", justify="right", style="cyan")
    table.add_column("Status", style="magenta")
    table.add_column("Slug", style="green")
    table.add_column("Location", style="dim")

    for issue in sorted_issues:
        issue_file = find_issue_file(issue.slug)
        location = str(issue_file) if issue_file else "[red]MISSING[/red]"
        
        # Color code status
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
            location
        )

    console.print(table)

def main():
    parser = argparse.ArgumentParser(description="Task Agent CLI")
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

    args = parser.parse_args()
    console = Console()

    if args.command == "next":
        cmd_next(console)
    elif args.command == "list":
        cmd_list(console)
    elif args.command == "done":
        cmd_done(console, args.slug)
    elif args.command == "new":
        cmd_new(console, args.title, args.body, args.draft)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
