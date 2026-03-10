from typing import List, Optional
from pathlib import Path
from pydantic import BaseModel
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
import sys

# Constants
USV_DELIM = '\x1f'
ISSUES_ROOT = Path("docs/issues")
MISSION_PATH = ISSUES_ROOT / "mission.usv"

class Issue(BaseModel):
    slug: str
    priority: int
    status: str
    branch: str

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
            if len(parts) >= 4:
                try:
                    issues.append(Issue(
                        slug=parts[0],
                        priority=int(parts[1]),
                        status=parts[2],
                        branch=parts[3]
                    ))
                except (ValueError, IndexError):
                    continue
    return issues

def find_issue_file(slug: str) -> Optional[Path]:
    """Find the issue markdown file by slug in docs/issues/ excluding completed/."""
    # We check subdirectories like pending/, draft/, active/
    # but explicitly skip completed/
    search_dirs = [d for d in ISSUES_ROOT.iterdir() if d.is_dir() and d.name != "completed"]
    
    for directory in search_dirs:
        # Check if the file exists in this directory
        issue_file = directory / f"{slug}.md"
        if issue_file.exists():
            return issue_file
            
    return None

def main():
    console = Console()
    
    issues = load_mission()
    if not issues:
        console.print("[red]No issues found in mission.usv[/red]")
        sys.exit(1)
        
    # Top issue is the first one
    next_issue = issues[0]
    
    issue_file = find_issue_file(next_issue.slug)
    if not issue_file:
        console.print(f"[red]Issue file not found for slug: {next_issue.slug}[/red]")
        console.print(f"[yellow]Searched in subdirectories of {ISSUES_ROOT} (excluding 'completed/')[/yellow]")
        sys.exit(1)
        
    with issue_file.open("r", encoding="utf-8") as f:
        content = f.read()
        
    # Render the issue
    console.print(Panel(
        f"[bold blue]NEXT ISSUE:[/bold blue] [cyan]{next_issue.slug}[/cyan]\n"
        f"[bold blue]PRIORITY:[/bold blue] {next_issue.priority} | "
        f"[bold blue]STATUS:[/bold blue] {next_issue.status} | "
        f"[bold blue]BRANCH:[/bold blue] {next_issue.branch}\n"
        f"[bold blue]FILE:[/bold blue] {issue_file}",
        title="Issue Agent",
        expand=False
    ))
    
    md = Markdown(content)
    console.print(md)

if __name__ == "__main__":
    main()
