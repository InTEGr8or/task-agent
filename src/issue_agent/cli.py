from typing import List, Optional
from pathlib import Path
from pydantic import BaseModel, Field
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
import sys

# Constants
USV_DELIM = '\x1f'
MISSION_PATH = Path("docs/issues/mission.usv")
ISSUES_DIR = Path("docs/issues/pending")

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
                issues.append(Issue(
                    slug=parts[0],
                    priority=int(parts[1]),
                    status=parts[2],
                    branch=parts[3]
                ))
    return issues

def main():
    console = Console()
    
    issues = load_mission()
    if not issues:
        console.print("[red]No issues found in mission.usv[/red]")
        sys.exit(1)
        
    # Top issue is the first one
    next_issue = issues[0]
    
    issue_file = ISSUES_DIR / f"{next_issue.slug}.md"
    if not issue_file.exists():
        console.print(f"[red]Issue file not found: {issue_file}[/red]")
        sys.exit(1)
        
    with issue_file.open("r", encoding="utf-8") as f:
        content = f.read()
        
    # Render the issue
    console.print(Panel(
        f"[bold blue]NEXT ISSUE:[/bold blue] [cyan]{next_issue.slug}[/cyan]\n"
        f"[bold blue]PRIORITY:[/bold blue] {next_issue.priority} | "
        f"[bold blue]BRANCH:[/bold blue] {next_issue.branch}",
        title="Issue Agent",
        expand=False
    ))
    
    md = Markdown(content)
    console.print(md)

if __name__ == "__main__":
    main()
