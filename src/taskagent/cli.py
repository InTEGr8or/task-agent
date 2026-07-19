from typing import List, Optional, Tuple, Dict, Set
from pathlib import Path
from datetime import datetime
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
import sys

from taskagent.theme import DEFAULT as theme

# Removed invalid NO_BORDER definition
import argparse
import os
import json
import re
import importlib.metadata
import urllib.request
import questionary
import subprocess
import shlex
import shutil
import pyperclip  # type: ignore

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
from taskagent.discovery import discover, get_task_agent_project_root
from taskagent import agent


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


def display_version_info(console: Console):
    """Display running and PyPI version information."""
    # 1. Get running tool version
    tool_v = get_tool_version()
    console.print(f"[bold blue]Running version:[/bold blue] {tool_v}")

    # 2. Check PyPI
    latest_v = get_latest_pypi_version()
    if latest_v:
        if latest_v != tool_v:
            console.print(f"[bold yellow]Latest PyPI version:[/bold yellow] {latest_v}")
            console.print("[dim]Run [bold]ta self-up[/bold] to upgrade.[/dim]")
        else:
            console.print(f"[dim]Latest PyPI version:[/dim] {latest_v} (up to date)")

    # 3. Optional: show local project version if available
    try:
        v, source = get_project_version()
        if v != "unknown":
            console.print(f"[dim]Local project version:[/dim] {v} (from {source})")
    except Exception:
        pass


def get_committed_version() -> Tuple[str, Optional[str]]:
    """Read the version from HEAD (committed code), not working tree."""
    files_to_check = [
        ("pyproject.toml", r'version\s*=\s*"(.*?)"'),
        ("package.json", None),  # Special handling below
        ("Cargo.toml", r'^version\s*=\s*"(.*?)"'),
    ]

    for filename, pattern in files_to_check:
        try:
            result = subprocess.run(
                ["git", "show", f"HEAD:{filename}"],
                capture_output=True,
                text=True,
                check=False,
                shell=(os.name == "nt"),
            )
            if result.returncode == 0:
                if filename == "package.json":
                    try:
                        data = json.loads(result.stdout)
                        if "version" in data:
                            return data["version"], "package.json"
                    except Exception:
                        pass
                elif pattern:
                    match = re.search(pattern, result.stdout, re.MULTILINE)
                    if match:
                        return match.group(1), filename
        except Exception:
            pass

    return "unknown", None


def get_project_version(root: Optional[Path] = None) -> Tuple[str, Optional[str]]:
    """Read the current project version from various project files (working tree)."""
    root = root or Path.cwd()

    # Check pyproject.toml
    pyproject = root / "pyproject.toml"
    if pyproject.exists():
        try:
            with pyproject.open("r") as f:
                content = f.read()
                match = re.search(r'version\s*=\s*"(.*?)"', content)
                if match:
                    return match.group(1), "pyproject.toml"
        except Exception:
            pass

    # Check package.json
    package_json = root / "package.json"
    if package_json.exists():
        try:
            with package_json.open("r") as f:
                data = json.load(f)
                if "version" in data:
                    return data["version"], "package.json"
        except Exception:
            pass

    # Check Cargo.toml (Rust)
    cargo = root / "Cargo.toml"
    if cargo.exists():
        try:
            with cargo.open("r") as f:
                content = f.read()
                match = re.search(r'^version\s*=\s*"(.*?)"', content, re.MULTILINE)
                if match:
                    return match.group(1), "Cargo.toml"
        except Exception:
            pass

    # Check *.csproj (.NET)
    for csproj in root.glob("*.csproj"):
        try:
            with csproj.open("r") as f:
                content = f.read()
                match = re.search(r"<Version>(.*?)</Version>", content)
                if match:
                    return match.group(1), csproj.name
        except Exception:
            pass

    # Check pom.xml (Java/Maven)
    pom = root / "pom.xml"
    if pom.exists():
        try:
            with pom.open("r") as f:
                content = f.read()
                match = re.search(r"<version>(.*?)</version>", content)
                if match:
                    return match.group(1), "pom.xml"
        except Exception:
            pass

    # Check build.gradle (Java/Gradle)
    gradle_kts = root / "build.gradle.kts"
    gradle = root / "build.gradle"
    gradle_file = None
    if gradle_kts.exists():
        gradle_file = gradle_kts
    elif gradle.exists():
        gradle_file = gradle

    if gradle_file:
        try:
            with gradle_file.open("r") as f:
                content = f.read()
                match = re.search(r'version\s*=\s*["\'](.*?)["\']', content)
                if match:
                    return match.group(1), gradle_file.name
        except Exception:
            pass

    return "unknown", None


def get_key() -> str:
    """Read a single key or escape sequence from stdin."""
    if HAS_TERMIOS and sys.stdin.isatty():
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


def get_editor() -> str:
    """Get the default editor, checking in order: EDITOR env, nvim, vim."""
    editor = os.environ.get("EDITOR")
    if editor:
        return editor
    if shutil.which("nvim"):
        return "nvim"
    return "vim"


def select_issue(
    console: Console,
    issues: List[Issue],
    slug_part: Optional[str],
    status_filter: Optional[List[str]] = None,
) -> Optional[Issue]:
    """Helper to select an issue based on partial slug/title and status filter."""
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

    # Find matches by slug prefix, exact title, or title substring (retitled tasks)
    q = slug_part.lower()
    q_slug = TaskAgent.slugify(slug_part)
    matches = [
        i
        for i in filtered
        if i.slug.startswith(slug_part)
        or i.slug.startswith(q_slug)
        or i.name.lower() == q
        or q in i.name.lower()
        or TaskAgent.slugify(i.name) == q_slug
        or TaskAgent.slugify(i.name).startswith(q_slug)
    ]
    # De-dupe while preserving order
    seen = set()
    unique_matches = []
    for i in matches:
        if i.slug not in seen:
            seen.add(i.slug)
            unique_matches.append(i)
    matches = unique_matches

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


def render_issue(
    console: Console,
    issue: Issue,
    issue_file: Path,
    issues: Optional[List[Issue]] = None,
):
    """Render an issue's details to the console, using a pager if necessary."""
    with issue_file.open("r", encoding="utf-8") as f:
        content = f.read()

    deps_info = ""
    if issue.subtask_of:
        deps_info += (
            f"[bold blue]SUBTASK OF:[/bold blue] [yellow]{issue.subtask_of}[/yellow]\n"
        )

    # Collect blockers: both explicit blocked_by and derived open subtasks
    blockers = list(issue.blocked_by)
    if issues:
        open_subtasks = [
            i.slug
            for i in issues
            if i.subtask_of == issue.slug and i.status != "completed"
        ]
        blockers.extend(open_subtasks)

    if blockers:
        deps_info += f"[bold blue]BLOCKED BY:[/bold blue] [yellow]{', '.join(blockers)}[/yellow]\n"

    panel = Panel(
        f"[bold blue]ISSUE:[/bold blue] [cyan]{issue.name}[/cyan]\n"
        f"[bold blue]SLUG:[/bold blue] {issue.slug} | "
        f"[bold blue]PRIORITY:[/bold blue] {issue.priority} | "
        f"[bold blue]STATUS:[/bold blue] {issue.status}\n"
        f"[bold blue]FILE:[/bold blue]\n{issue_file}\n"
        f"{deps_info}",
        box=theme.panel_box,
    )

    md = Markdown(content)

    # Estimate lines: Panel (~6) + Markdown content + some buffer
    total_lines = 8 + content.count("\n")
    terminal_height = console.size.height

    if total_lines > terminal_height:
        with console.pager(styles=True):
            console.print(panel)
            console.print(md)
    else:
        console.print(panel)
        console.print(md)


def get_created_date(manager: TaskAgent, slug: str) -> str:
    """Get the creation/modification date of a task file."""
    try:
        issue_file = manager.find_issue_file(slug, include_completed=True)
        if issue_file and issue_file.exists():
            try:
                content = issue_file.read_text(encoding="utf-8")
                if content.startswith("---"):
                    parts = content.split("---", 2)
                    if len(parts) >= 3:
                        frontmatter = parts[1]
                        for line in frontmatter.splitlines():
                            if line.strip().startswith("created_at:"):
                                raw_val = line.split(":", 1)[1].strip()
                                try:
                                    dt = datetime.fromisoformat(raw_val)
                                    return dt.strftime("%Y-%m-%d %H:%M")
                                except ValueError:
                                    for fmt in (
                                        "%Y-%m-%d %H:%M",
                                        "%Y-%m-%d %H:%M:%S",
                                        "%Y-%m-%d",
                                    ):
                                        try:
                                            dt = datetime.strptime(raw_val, fmt)
                                            return dt.strftime("%Y-%m-%d %H:%M")
                                        except ValueError:
                                            pass
                                    return raw_val
            except Exception:
                pass
            stat = issue_file.stat()
            birthtime = getattr(stat, "st_birthtime", None)
            t = birthtime if birthtime is not None else stat.st_mtime
            return datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M")
    except Exception:
        pass
    return "unknown"


def maybe_show_strategy(console: Console, manager: TaskAgent) -> bool:
    """Show the project strategy panel if the cooldown has elapsed.

    Returns True if the strategy was displayed.
    """
    if not manager.should_show_strategy():
        return False

    content = manager.get_strategy()
    if not content:
        return False

    # Strip the H1 header if present — we use it as the panel title instead
    lines = content.split("\n")
    title = "Strategy"
    body_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("# ") and title == "Strategy":
            title = stripped.lstrip("# ").strip()
            continue
        # Skip HTML comments (the hint comment)
        if stripped.startswith("<!--") and stripped.endswith("-->"):
            continue
        body_lines.append(line)

    body = "\n".join(body_lines).strip()
    if not body or body == "_Define the current strategic direction for this project._":
        return False

    meta = manager.get_strategy_meta()
    last_shown = meta.get("last_shown_at", "never")
    if last_shown != "never":
        try:
            from datetime import datetime as dt

            last_dt = dt.fromisoformat(last_shown)
            elapsed = (dt.now() - last_dt).total_seconds()
            if elapsed < 3600:
                age = f"{int(elapsed / 60)}m ago"
            elif elapsed < 86400:
                age = f"{int(elapsed / 3600)}h ago"
            else:
                age = f"{int(elapsed / 86400)}d ago"
            subtitle = f"last shown {age} · ta strategy"
        except Exception:
            subtitle = "ta strategy"
    else:
        subtitle = "ta strategy"

    # Print the title, body (with custom theme), and subtitle
    console.print(f"[bold blue]📐 {title}[/bold blue]")

    from rich.theme import Theme

    strategy_theme = Theme(
        {
            "markdown.paragraph": "green",
            "markdown.item": "green",
            "markdown.h1": "bold blue",
            "markdown.h2": "bold blue",
            "markdown.h3": "bold blue",
            "markdown.h4": "bold blue",
            "markdown.h5": "bold blue",
            "markdown.h6": "bold blue",
        }
    )

    with console.use_theme(strategy_theme):
        console.print(Markdown(body))

    console.print(f"[dim]{subtitle}[/dim]")
    console.print()
    manager.update_strategy_last_shown()
    return True


def cmd_strategy(
    console: Console,
    manager: TaskAgent,
    action: Optional[str] = None,
):
    """View, edit, or initialize the project strategy."""
    if action == "init":
        path = manager.init_strategy()
        console.print(f"[bold green]Strategy initialized:[/bold green] {path}")
        console.print("[dim]Edit it with: ta strategy edit[/dim]")
        return

    if action == "edit":
        path = manager.init_strategy()
        editor = get_editor()
        subprocess.run([editor, str(path)])
        console.print("[bold green]Strategy updated.[/bold green]")
        return

    # Default: view
    content = manager.get_strategy()
    if not content:
        console.print(
            "[yellow]No strategy defined yet.[/yellow]\n"
            "[dim]Run [bold]ta strategy init[/bold] to create one.[/dim]"
        )
        return

    lines = content.split("\n")
    title = "Strategy"
    body_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("# ") and title == "Strategy":
            title = stripped.lstrip("# ").strip()
            continue
        if stripped.startswith("<!--") and stripped.endswith("-->"):
            continue
        body_lines.append(line)

    body = "\n".join(body_lines).strip()

    meta = manager.get_strategy_meta()
    last_shown = meta.get("last_shown_at", "never")

    # Print the title, body (with custom theme), and subtitle
    console.print(f"[bold blue]📐 {title}[/bold blue]")

    from rich.theme import Theme

    strategy_theme = Theme(
        {
            "markdown.paragraph": "green",
            "markdown.item": "green",
            "markdown.h1": "bold blue",
            "markdown.h2": "bold blue",
            "markdown.h3": "bold blue",
            "markdown.h4": "bold blue",
            "markdown.h5": "bold blue",
            "markdown.h6": "bold blue",
        }
    )

    if body:
        with console.use_theme(strategy_theme):
            console.print(Markdown(body))
    else:
        console.print("[dim]Empty strategy — edit it with: ta strategy edit[/dim]")

    console.print(f"[dim]last shown: {last_shown} · ta strategy edit[/dim]")


def cmd_next(console: Console, manager: TaskAgent):
    """Show the top issue."""
    maybe_show_strategy(console, manager)
    next_issue = manager.get_next_issue()
    if not next_issue:
        console.print(f"[yellow]No issues found in {manager.mission_path}[/yellow]")
        return

    issue_file = manager.find_issue_file(next_issue.slug)

    if not issue_file:
        console.print(f"[red]Issue file not found for slug: {next_issue.slug}[/red]")
        sys.exit(1)

    issues = manager.load_mission()
    render_issue(console, next_issue, issue_file, issues)


def cmd_search(console: Console, manager: TaskAgent, pattern: str):
    """Search for issues by slug pattern (case-insensitive fuzzy match)."""
    import re

    # Normalize pattern: remove dashes, punctuation, lowercase
    def normalize(s: str) -> str:
        return re.sub(r"[^a-zA-Z0-9]", "", s).lower()

    def fuzzy_match(slug: str, pattern: str) -> bool:
        slug_clean = normalize(slug)
        pat_clean = normalize(pattern)
        return pat_clean in slug_clean or slug_clean.startswith(pat_clean)

    pat_norm = normalize(pattern)
    if not pat_norm:
        console.print("[yellow]No pattern provided.[/yellow]")
        return

    matches: List[Issue] = []

    # Search mission issues
    issues = manager.load_mission()
    for i in issues:
        if fuzzy_match(i.slug, pat_norm):
            matches.append(i)

    # Always search completed tasks too
    for f, slug in manager.walk_completed():
        if fuzzy_match(slug, pat_norm):
            name = manager.extract_title(f)
            matches.append(Issue(name=name, slug=slug, status="completed", priority=0))

    if not matches:
        console.print(f"[yellow]No issues match pattern '{pattern}'.[/yellow]")
        return

    if len(matches) == 1:
        issue = matches[0]
        issue_file = manager.find_issue_file(
            issue.slug, include_completed=(issue.status == "completed")
        )
        if not issue_file:
            console.print(f"[red]Issue file not found for {issue.slug}[/red]")
            return

        render_issue(console, issue, issue_file, issues)
        console.print("[dim]Press 'e' to edit, 'q' to exit.[/dim]")
        try:
            key = get_key()
        except Exception:
            key = "q"
        if key == "e" and issue_file:
            editor = get_editor()
            subprocess.run([editor, str(issue_file)])
            manager.init_project()
        return

    cursor = 0

    with Live(auto_refresh=False, console=console, screen=True) as live:
        while True:
            table = Table(
                title=f"[bold blue]Search Results: '{pattern}'[/bold blue]",
                box=theme.table_box,
                show_header=True,
                header_style=theme.header_style,
                padding=theme.table_padding,
            )
            table.add_column("#", justify="right", style="dim", width=4)
            table.add_column("Status", width=10)
            table.add_column("Slug", style="cyan")

            for idx, issue in enumerate(matches):
                style = "bold cyan" if idx == cursor else "white"
                prefix = "> " if idx == cursor else "  "
                status_style = (
                    "bold green"
                    if issue.status == "active"
                    else ("bold yellow" if issue.status == "pending" else "dim")
                )
                table.add_row(
                    str(idx + 1),
                    f"[{status_style}]{issue.status.upper()}[/{status_style}]",
                    f"{prefix}{issue.slug}",
                    style=style,
                )

            help_text = "[dim]l: view | e: edit | q: exit[/dim]"

            live.update(
                Panel(table, subtitle=help_text, box=theme.panel_box), refresh=True
            )

            try:
                key = get_key()
            except Exception:
                key = "q"

            if key in ["q", "\x1b"]:
                break
            elif key in ["k", "\x1b[A"]:
                cursor = max(0, cursor - 1)
            elif key in ["j", "\x1b[B"]:
                cursor = min(len(matches) - 1, cursor + 1)
            elif key == "l":
                live.stop()
                issue = matches[cursor]
                issue_file = manager.find_issue_file(
                    issue.slug, include_completed=(issue.status == "completed")
                )
                if issue_file:
                    render_issue(console, issue, issue_file, issues)
                    console.print(
                        "[dim]Press 'e' to edit, 'q' to return to list.[/dim]"
                    )
                    try:
                        inner_key = get_key()
                    except Exception:
                        inner_key = "q"
                    if inner_key == "e":
                        editor = get_editor()
                        subprocess.run([editor, str(issue_file)])
                        manager.init_project()
                        issues = manager.load_mission()
                        matches = [i for i in issues if fuzzy_match(i.slug, pat_norm)]
                        # Also re-search completed
                        new_matches: List[Issue] = list(matches)
                        for f, slug in manager.walk_completed():
                            if fuzzy_match(slug, pat_norm) and not any(
                                m.slug == slug for m in new_matches
                            ):
                                name = manager.extract_title(f)
                                new_matches.append(
                                    Issue(
                                        name=name,
                                        slug=slug,
                                        status="completed",
                                        priority=0,
                                    )
                                )
                        matches = new_matches
                        if cursor >= len(matches):
                            cursor = max(0, len(matches) - 1)
                else:
                    console.print(f"[red]Issue file not found for {issue.slug}[/red]")
                live.start()
            elif key == "e":
                live.stop()
                issue = matches[cursor]
                issue_file = manager.find_issue_file(issue.slug)
                if issue_file:
                    editor = get_editor()
                    subprocess.run([editor, str(issue_file)])
                    manager.init_project()
                    issues = manager.load_mission()
                    matches = [i for i in issues if i.slug.startswith(pattern)]
                    if cursor >= len(matches):
                        cursor = max(0, len(matches) - 1)
                live.start()


def cmd_history(console: Console, manager: TaskAgent, limit: int = 20):
    """Show completed tasks in reverse chronological order."""
    all_completed = manager.walk_completed()

    if not all_completed:
        console.print("[yellow]No completed tasks found.[/yellow]")
        return

    def get_mtime_iso(path: Path) -> str:
        try:
            content = path.read_text(encoding="utf-8")
            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    frontmatter = parts[1]
                    for line in frontmatter.splitlines():
                        if line.strip().startswith("created_at:"):
                            raw_val = line.split(":", 1)[1].strip()
                            try:
                                dt = datetime.fromisoformat(raw_val)
                                return dt.strftime("%Y-%m-%d %H:%M")
                            except ValueError:
                                for fmt in (
                                    "%Y-%m-%d %H:%M",
                                    "%Y-%m-%d %H:%M:%S",
                                    "%Y-%m-%d",
                                ):
                                    try:
                                        dt = datetime.strptime(raw_val, fmt)
                                        return dt.strftime("%Y-%m-%d %H:%M")
                                    except ValueError:
                                        pass
                                return raw_val
        except Exception:
            pass
        try:
            return datetime.fromtimestamp(path.stat().st_mtime).strftime(
                "%Y-%m-%d %H:%M"
            )
        except Exception:
            return ""

    all_completed.sort(key=lambda x: get_mtime_iso(x[0]), reverse=True)

    cursor = 0
    window_size = console.height - 8

    with Live(auto_refresh=False, console=console, screen=True) as live:
        while True:
            start_idx = max(
                0, min(cursor - window_size // 2, len(all_completed) - window_size)
            )
            if len(all_completed) <= window_size:
                start_idx = 0
                display_items = all_completed
            else:
                display_items = all_completed[start_idx : start_idx + window_size]

            table = Table(
                title="[bold blue]History[/bold blue]",
                box=theme.table_box,
                show_header=True,
                header_style=theme.header_style,
                padding=theme.table_padding,
            )
            table.add_column("#", justify="right", style="dim", width=4)
            table.add_column("Date", style="dim", width=16)
            table.add_column("Slug", style="cyan")

            for idx, (file, slug) in enumerate(display_items):
                absolute_idx = start_idx + idx
                style = "bold cyan" if absolute_idx == cursor else "white"
                prefix = "> " if absolute_idx == cursor else "  "
                date_str = get_mtime_iso(file)
                table.add_row(
                    str(absolute_idx + 1), date_str, f"{prefix}{slug}", style=style
                )

            help_text = "[dim]v/l: view | c: copy slug | q: exit[/dim]"

            live.update(
                Panel(table, subtitle=help_text, box=theme.panel_box), refresh=True
            )

            try:
                key = get_key()
            except Exception:
                key = "q"

            if key in ["q", "\x1b"]:
                break
            elif key in ["k", "\x1b[A"]:
                cursor = max(0, cursor - 1)
            elif key in ["j", "\x1b[B"]:
                cursor = min(len(all_completed), cursor + 1)
            elif key in ["v", "l"]:
                live.stop()
                file, slug = all_completed[cursor]
                issue = Issue(name=slug, slug=slug, status="completed", priority=0)
                render_issue(console, issue, file)
                try:
                    get_key()
                except Exception:
                    pass
                live.start()
            elif key in ["c"]:
                # Copy slug to clipboard
                _, slug = all_completed[cursor]
                try:
                    pyperclip.copy(slug)
                    console.print(f"[green]Copied slug to clipboard: {slug}[/green]")
                except Exception as e:
                    console.print(f"[yellow]Failed to copy to clipboard: {e}[/yellow]")


def cmd_recover_history(console: Console, manager: TaskAgent):
    """Recover deleted task files from Git history and populate/restore task creation dates into YAML frontmatter."""
    console.print("[blue]Checking Git history for deleted task files...[/blue]")
    try:
        out = subprocess.check_output(
            [
                "git",
                "log",
                "--all",
                "--pretty=format:",
                "--name-only",
                "--diff-filter=D",
            ],
            stderr=subprocess.DEVNULL,
            text=True,
        )
        deleted_paths = sorted(
            list(set(line.strip() for line in out.splitlines() if line.strip()))
        )
    except Exception as e:
        console.print(f"[red]Failed to query git history: {e}[/red]")
        sys.exit(1)

    existing_slugs = set()
    for root, dirs, files in os.walk(manager.issues_root):
        for f in files:
            if f.endswith(".md"):
                file_path = Path(root) / f
                if f == "README.md":
                    slug = file_path.parent.name
                else:
                    slug = file_path.stem
                if slug != "tasks":
                    existing_slugs.add(slug)

    try:
        for issue in manager.load_mission():
            existing_slugs.add(issue.slug)
    except Exception:
        pass

    def get_slug_from_path(path_str: str) -> str:
        p = Path(path_str)
        if p.name == "README.md":
            return p.parent.name
        return p.stem

    def get_deleted_file_content(path: str) -> Optional[str]:
        try:
            commits = (
                subprocess.check_output(
                    ["git", "log", "--all", "--format=%H", "--", path],
                    stderr=subprocess.DEVNULL,
                    text=True,
                )
                .strip()
                .splitlines()
            )
            for commit in commits:
                try:
                    res = subprocess.check_output(
                        ["git", "show", f"{commit}:{path}"],
                        stderr=subprocess.DEVNULL,
                        text=True,
                    )
                    if res:
                        return res
                except Exception:
                    pass
        except Exception:
            pass
        return None

    restored_count = 0
    for path_str in deleted_paths:
        parts = Path(path_str).parts
        if not (("tasks" in parts or "issues" in parts) and path_str.endswith(".md")):
            continue
        if parts[-1] in ["plan.md", "README.md"] and (
            len(parts) <= 2 or parts[-2] in ["tasks", "issues"]
        ):
            continue

        slug = get_slug_from_path(path_str)
        if slug in existing_slugs or slug == "tasks":
            continue

        content = get_deleted_file_content(path_str)
        if not content:
            continue

        status = "pending"
        year = None
        for part in ["completed", "pending", "draft", "active"]:
            if part in parts:
                status = part
                idx = parts.index(part)
                if part == "completed" and idx + 1 < len(parts):
                    next_part = parts[idx + 1]
                    if next_part.isdigit() and len(next_part) == 4:
                        year = next_part
                break

        if status == "completed":
            year_str = year or str(datetime.now().year)
            target_file = (
                manager.issues_root / "completed" / year_str / slug / "README.md"
            )
        else:
            target_file = manager.issues_root / status / slug / "README.md"

        try:
            target_file.parent.mkdir(parents=True, exist_ok=True)
            target_file.write_text(content, encoding="utf-8")
            console.print(f"[green]Restored: {slug} (status: {status})[/green]")
            existing_slugs.add(slug)
            restored_count += 1
        except Exception as e:
            console.print(f"[red]Failed to restore {slug}: {e}[/red]")

    console.print(
        f"[bold green]Restored {restored_count} task(s) from git history.[/bold green]"
    )

    # 2. Run folder migration for any loose files in workspace
    migrated_count = manager.migrate_all_to_folders()
    if migrated_count > 0:
        console.print(
            f"[green]Migrated {migrated_count} file-based task(s) to folder format.[/green]"
        )

    # 3. Recover dates and write/update frontmatter
    console.print("[blue]Recovering task creation dates into frontmatter...[/blue]")
    updated_dates_count = 0
    for root, dirs, files in os.walk(manager.issues_root):
        root_path = Path(root)
        try:
            rel_parts = root_path.relative_to(manager.issues_root).parts
            if ".task-agent" in rel_parts:
                continue
        except ValueError:
            pass

        for file in files:
            if file != "README.md":
                continue

            readme_path = root_path / "README.md"
            slug = root_path.name
            if slug == "tasks":
                continue

            # Query git log with wildcard pathspecs matching the slug in issues or tasks directories
            earliest_date = None
            pathspecs = [
                f"*tasks*/{slug}/README.md",
                f"*tasks*/{slug}.md",
                f"*issues*/{slug}/README.md",
                f"*issues*/{slug}.md",
            ]
            try:
                out = subprocess.check_output(
                    ["git", "log", "--all", "--format=%aI", "--reverse", "--"]
                    + pathspecs,
                    stderr=subprocess.DEVNULL,
                    text=True,
                ).strip()
                if out:
                    earliest_date = out.splitlines()[0]
            except Exception:
                pass

            if not earliest_date:
                # Fallback to file creation/modification date
                try:
                    stat = readme_path.stat()
                    birthtime = getattr(stat, "st_birthtime", None)
                    t = birthtime if birthtime is not None else stat.st_mtime
                    earliest_date = datetime.fromtimestamp(t).astimezone().isoformat()
                except Exception:
                    earliest_date = datetime.now().astimezone().isoformat()

            content = readme_path.read_text(encoding="utf-8")
            if content.startswith("---"):
                content_parts = content.split("---", 2)
                if len(content_parts) >= 3:
                    frontmatter = content_parts[1]
                    lines = frontmatter.splitlines()
                    has_created_at = False
                    for i, line in enumerate(lines):
                        if line.strip().startswith("created_at:"):
                            lines[i] = f"created_at: {earliest_date}"
                            has_created_at = True
                            break
                    if not has_created_at:
                        lines.append(f"created_at: {earliest_date}")
                    new_frontmatter = "\n".join(lines) + "\n"
                    new_content = f"---{new_frontmatter}---{content_parts[2]}"
                else:
                    new_content = f"---\ncreated_at: {earliest_date}\n---\n\n" + content
            else:
                new_content = f"---\ncreated_at: {earliest_date}\n---\n\n" + content

            readme_path.write_text(new_content, encoding="utf-8")
            updated_dates_count += 1

    console.print(
        f"[bold green]Updated {updated_dates_count} task(s) with creation dates.[/bold green]"
    )

    # Run project initialization to sync the restored files with mission.usv
    manager.init_project()


def cmd_report(console: Console, manager: TaskAgent, slug: str):
    """View metadata/logs for a task."""
    issue_file = manager.find_issue_file(slug, include_completed=True)
    if not issue_file:
        console.print(f"[red]Issue not found: {slug}[/red]")
        return

    meta_file = issue_file.parent / "meta.json"
    if not meta_file.exists():
        console.print(f"[yellow]No metadata found for {slug}[/yellow]")
        return

    with meta_file.open("r", encoding="utf-8") as f:
        meta = json.load(f)

    console.print(f"[bold blue]Task Report: {slug}[/bold blue]")
    console.print(
        Panel(json.dumps(meta, indent=2), title="Metadata", box=theme.panel_box)
    )

    trace_path = issue_file.parent / meta.get("reasoning_trace", "logs/trace.log")
    if trace_path.exists():
        console.print(f"[bold blue]Reasoning Trace ({trace_path.name}):[/bold blue]")
        console.print(
            Panel(trace_path.read_text(encoding="utf-8"), box=theme.panel_box)
        )
    else:
        console.print("[yellow]Reasoning trace not found.[/yellow]")


def cmd_mcp_api(console: Console):
    """Display the MCP API (tools and docstrings)."""
    mcp_file = Path(__file__).parent / "mcp.py"
    if not mcp_file.exists():
        console.print("[red]Could not find mcp.py[/red]")
        return

    content = mcp_file.read_text(encoding="utf-8")

    # Regex to extract @mcp.tool() decorated functions and their docstrings
    pattern = re.compile(
        r"@mcp\.tool\(\)\ndef\s+(\w+)\(.*?\)\s*->.*?:?\n\s+[\"']{3}(.*?)[\"']{3}",
        re.DOTALL,
    )

    console.print("[bold blue]Available MCP Tools:[/bold blue]\n")
    for match in pattern.finditer(content):
        tool_name = match.group(1)
        docstring = match.group(2).strip()
        console.print(f"[bold cyan]{tool_name}[/bold cyan]")
        console.print(f"  {docstring}\n")


def cmd_soft_delete(console: Console, manager: TaskAgent, slug: str):
    """Soft-delete a task: archive it without committing."""
    try:
        issue = manager.soft_delete_issue(slug)
        console.print(
            f"[bold yellow]Task '{issue.slug}' soft-deleted.[/bold yellow] "
            f"Archived to [bold]docs/tasks/deleted/[/bold]. "
            f"Use [bold]git checkout docs/tasks/deleted/{issue.slug}[/bold] and "
            f"[bold]ta restore {issue.slug}[/bold] to bring it back."
        )
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)


def detect_current_slug_from_git() -> Optional[str]:
    """Detect the current task slug from the current git branch name."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        branch = result.stdout.strip()
        if branch.startswith("issue/"):
            return branch[len("issue/") :]
    except Exception:
        pass
    return None


def find_worktree_path_for_slug(slug: str) -> Optional[Path]:
    """Find the registered worktree path for a given task slug."""
    try:
        result = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            capture_output=True,
            text=True,
            check=True,
        )
        current_worktree = None
        for line in result.stdout.splitlines():
            if line.startswith("worktree "):
                current_worktree = Path(line[len("worktree ") :].strip())
            elif line.startswith("branch refs/heads/issue/"):
                branch_slug = line[len("branch refs/heads/issue/") :].strip()
                if branch_slug == slug:
                    return current_worktree
    except Exception:
        pass
    # Fallback to local .gwt/slug if it exists
    p = Path(".gwt") / slug
    if p.exists():
        return p
    return None


def cmd_done(
    console: Console,
    manager: TaskAgent,
    slug: Optional[str] = None,
    commit_message: Optional[str] = None,
    should_commit: bool = True,
    push_mission: bool = False,
    solution: Optional[str] = None,
    no_verify: bool = True,
):
    """Mark an issue as done."""
    if not slug:
        slug = detect_current_slug_from_git()
        if not slug:
            console.print(
                "[red]Error: Please specify the task slug or run this command from within the task's worktree/branch.[/red]"
            )
            sys.exit(1)

    worktree_path = find_worktree_path_for_slug(slug)
    abs_worktree = (
        worktree_path.resolve() if worktree_path and worktree_path.exists() else None
    )
    is_cwd_inside_worktree = False
    if abs_worktree:
        try:
            is_cwd_inside_worktree = Path.cwd().resolve().is_relative_to(abs_worktree)
        except Exception:
            pass

    try:
        issue, commit_hash = manager.complete_issue(
            slug,
            commit_message=commit_message,
            should_commit=should_commit,
            push_mission=push_mission,
            solution_explanation=solution,
            no_verify=no_verify,
        )
        console.print(
            f"[bold green]Issue '{issue.slug}' marked as done and "
            f"removed from mission.usv[/bold green]"
        )
        if commit_hash:
            console.print(f"Commit: {commit_hash}")

        promote_version(console, manager)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)
    finally:
        # Destroy per-task agent even if commit fails
        agent.destroy_per_task_agent(slug)

    # Perform git worktree and branch cleanup after successful completion
    if worktree_path and worktree_path.exists():
        if is_cwd_inside_worktree:
            console.print(
                f"[yellow]Note: Worktree at '{worktree_path}' and branch 'issue/{slug}' were not removed because your shell is currently inside the worktree directory.[/yellow]"
            )
            console.print(
                "[yellow]To clean up, please change directory to the main repository directory and run:[/yellow]"
            )
            console.print("  [bold]git worktree prune[/bold]")
            console.print(f"  [bold]git branch -D issue/{slug}[/bold]")
        else:
            console.print(f"[blue]Cleaning up git worktree for '{slug}'...[/blue]")
            try:
                # Remove worktree
                subprocess.run(
                    ["git", "worktree", "remove", str(worktree_path)],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                console.print(
                    f"[green]Successfully removed worktree at '{worktree_path}'.[/green]"
                )

                # Delete branch
                branch_name = f"issue/{slug}"
                console.print(f"[blue]Deleting local branch '{branch_name}'...[/blue]")
                subprocess.run(
                    ["git", "branch", "-d", branch_name],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                console.print(
                    f"[green]Successfully deleted branch '{branch_name}'.[/green]"
                )
            except subprocess.CalledProcessError as e:
                console.print(
                    f"[yellow]Warning: Cleanup failed. {e.stderr.strip()}[/yellow]"
                )
                console.print(
                    f"[yellow]You can clean up manually by running: git worktree remove --force {worktree_path} && git branch -D issue/{slug}[/yellow]"
                )
    else:
        # If worktree doesn't exist, we still try to delete the branch if it exists
        branch_name = f"issue/{slug}"
        try:
            result = subprocess.run(
                ["git", "show-ref", "--verify", f"refs/heads/{branch_name}"],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                console.print(f"[blue]Deleting local branch '{branch_name}'...[/blue]")
                subprocess.run(
                    ["git", "branch", "-d", branch_name],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                console.print(
                    f"[green]Successfully deleted branch '{branch_name}'.[/green]"
                )
        except subprocess.CalledProcessError as e:
            console.print(
                f"[yellow]Warning: Could not delete branch '{branch_name}' safely: {e.stderr.strip()}[/yellow]"
            )
            console.print(
                f"[yellow]Run 'git branch -D {branch_name}' to force delete it.[/yellow]"
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


def cmd_commit(
    console: Console,
    manager: TaskAgent,
    message: Optional[str] = None,
    should_push: bool = True,
):
    """Commit and optionally push changes in the tasks/ directory."""
    import subprocess

    # Determine the tasks directory and git root
    tasks_dir = manager.issues_root
    if not tasks_dir or not tasks_dir.exists():
        console.print("[red]Tasks directory not found.[/red]")
        return

    git_root = manager.mission_root
    if not git_root:
        console.print("[red]No git repository found for tasks directory.[/red]")
        return

    # Generate default commit message if not provided
    if not message:
        message = f"Update tasks - {datetime.now().strftime('%Y-%m-%d %H:%M')}"

    console.print(f"[blue]Committing changes in {tasks_dir}...[/blue]")

    try:
        # Add all changes in tasks directory
        resolved_tasks_dir = tasks_dir.resolve()
        subprocess.run(
            ["git", "-C", str(git_root), "add", str(resolved_tasks_dir / ".")],
            check=True,
            capture_output=True,
            text=True,
            shell=(os.name == "nt"),
        )

        # Check if there are changes to commit
        result = subprocess.run(
            ["git", "-C", str(git_root), "diff", "--cached", "--quiet"],
            capture_output=True,
            text=True,
            shell=(os.name == "nt"),
        )

        if result.returncode == 0:
            console.print("[yellow]No changes to commit in tasks/ directory.[/yellow]")
            return

        # Commit
        subprocess.run(
            ["git", "-C", str(git_root), "commit", "--no-verify", "-m", message],
            check=True,
            capture_output=True,
            text=True,
            shell=(os.name == "nt"),
        )
        console.print(f"[bold green]Committed: {message}[/bold green]")

        # Push if requested
        if should_push:
            if manager.mission_root:
                console.print("[blue]Pushing to remote...[/blue]")
                manager.push_mission_repo()
                console.print("[bold green]Successfully pushed.[/bold green]")
            else:
                console.print(
                    "[yellow]No mission repository configured, skipping push.[/yellow]"
                )

    except subprocess.CalledProcessError as e:
        console.print(f"[red]Error: {e.stderr}[/red]")
    except Exception as e:
        console.print(f"[red]Unexpected error: {e}[/red]")


def cmd_commit_tasks(
    console: Console,
    message: Optional[str] = None,
    should_push: bool = True,
):
    """Commit and optionally push changes in the task-agent's own tasks/ directory.

    Always targets the task-agent project's ``docs/tasks/`` regardless of the
    current working directory.
    """
    import subprocess
    from datetime import datetime

    project_root = get_task_agent_project_root()
    tasks_dir = project_root / "docs" / "tasks"

    if not tasks_dir.exists():
        console.print("[red]Task-agent tasks directory not found.[/red]")
        return

    git_result = subprocess.run(
        ["git", "-C", str(project_root), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        shell=(os.name == "nt"),
    )
    if git_result.returncode != 0:
        console.print("[red]No git repository found for task-agent project.[/red]")
        return

    git_root = Path(git_result.stdout.strip())

    if not message:
        message = f"Update tasks - {datetime.now().strftime('%Y-%m-%d %H:%M')}"

    console.print(
        f"[blue]Committing changes in {tasks_dir} (task-agent own tasks)...[/blue]"
    )

    try:
        resolved_tasks_dir = tasks_dir.resolve()
        subprocess.run(
            ["git", "-C", str(git_root), "add", str(resolved_tasks_dir / ".")],
            check=True,
            capture_output=True,
            text=True,
            shell=(os.name == "nt"),
        )

        result = subprocess.run(
            ["git", "-C", str(git_root), "diff", "--cached", "--quiet"],
            capture_output=True,
            text=True,
            shell=(os.name == "nt"),
        )

        if result.returncode == 0:
            console.print("[yellow]No changes to commit in tasks/ directory.[/yellow]")
            return

        subprocess.run(
            ["git", "-C", str(git_root), "commit", "--no-verify", "-m", message],
            check=True,
            capture_output=True,
            text=True,
            shell=(os.name == "nt"),
        )
        console.print(f"[bold green]Committed: {message}[/bold green]")

        if should_push:
            console.print("[blue]Pushing to remote...[/blue]")
            subprocess.run(
                ["git", "-C", str(git_root), "push"],
                check=True,
                capture_output=True,
                text=True,
                shell=(os.name == "nt"),
            )
            console.print("[bold green]Successfully pushed.[/bold green]")

    except subprocess.CalledProcessError as e:
        console.print(f"[red]Error: {e.stderr}[/red]")
    except Exception as e:
        console.print(f"[red]Unexpected error: {e}[/red]")


def cmd_store(console: Console, args) -> None:
    """Machine data-root / moniker / registry / migrate commands."""
    from taskagent.store_registry import (
        MachineRegistry,
        get_data_root,
        inspect_host,
        migrate_store,
        resolve_moniker_for_host,
    )

    sub = getattr(args, "store_command", None)
    if not sub:
        console.print(
            "[yellow]Usage: ta store "
            "{data-root|moniker|list|inspect|rebuild-index|migrate|remote}[/yellow]"
        )
        return

    if sub == "data-root":
        console.print(str(get_data_root()))
        return

    if sub == "moniker":
        host = Path(args.path).resolve() if getattr(args, "path", None) else Path.cwd()
        moniker, origin = resolve_moniker_for_host(host)
        console.print(moniker)
        if origin:
            console.print(f"[dim]origin: {origin}[/dim]")
        return

    if sub == "list":
        reg = MachineRegistry()
        entries = reg.list_entries()
        if not entries:
            console.print(
                f"[dim]No registered stores under {get_data_root()} "
                f"(registry empty or missing).[/dim]"
            )
            return
        table = Table(title="Machine task stores", box=None, show_header=True)
        table.add_column("Moniker", style="cyan")
        table.add_column("Store path")
        table.add_column("Remote", style="dim")
        table.add_column("Host paths", style="dim")
        for e in entries:
            table.add_row(
                e.moniker,
                e.store_path,
                e.remote or "—",
                ", ".join(e.host_paths) if e.host_paths else "—",
            )
        console.print(table)
        return

    if sub == "inspect":
        host = Path(args.path).resolve() if getattr(args, "path", None) else Path.cwd()
        report = inspect_host(host)
        if getattr(args, "json", False):
            console.print_json(data=report)
            return
        console.print(f"[bold]Host[/bold]:          {report['host_path']}")
        console.print(f"[bold]Moniker[/bold]:       {report['moniker']}")
        console.print(f"[bold]Origin[/bold]:        {report['origin'] or '—'}")
        console.print(f"[bold]Data root[/bold]:     {report['data_root']}")
        console.print(
            f"[bold]Canonical store[/bold]: {report['canonical_store_path']} "
            f"({'exists' if report['canonical_store_exists'] else 'missing'})"
        )
        console.print(
            f"[bold]Migrated[/bold]:      {'yes' if report['migrated'] else 'no'}"
        )
        console.print(
            f"[bold]Legacy store[/bold]:  {report['legacy_store_path'] or '—'}"
        )
        if report["legacy_kind"]:
            console.print(
                f"[bold]Legacy kind[/bold]:   {report['legacy_kind']}"
                + (
                    f" (remote: {report['legacy_remote']})"
                    if report["legacy_remote"]
                    else ""
                )
            )
        if report["registry_entry"]:
            console.print(f"[bold]Registry[/bold]:      {report['registry_entry']}")
        else:
            console.print("[bold]Registry[/bold]:      (not registered)")
        if report.get("pointers_ok"):
            console.print("[bold]Pointers[/bold]:      ok (.task-agent/tasks → store)")
        console.print("\n[dim]Read-only inspect; no files were modified.[/dim]")
        return

    if sub == "rebuild-index":
        reg = MachineRegistry()
        rebuilt = reg.rebuild_from_stores()
        console.print(
            f"[green]Rebuilt registry from {reg.stores_dir} "
            f"({len(rebuilt)} store(s)).[/green]"
        )
        console.print(f"[dim]Wrote {reg.registry_path}[/dim]")
        return

    if sub == "remote":
        from taskagent.store_registry import (
            inspect_host,
            set_store_remote,
            suggest_store_remotes,
            _list_git_remotes,
        )

        rcmd = getattr(args, "remote_command", None)
        host = Path(args.path).resolve() if getattr(args, "path", None) else Path.cwd()
        report = inspect_host(host)
        store_path = Path(
            report["canonical_store_path"]
            if report.get("canonical_store_exists")
            else (report.get("legacy_store_path") or report["canonical_store_path"])
        )

        if rcmd == "show":
            if not store_path.is_dir():
                console.print(f"[red]No store at {store_path}[/red]")
                raise SystemExit(1)
            remotes = _list_git_remotes(store_path)
            if not remotes:
                console.print(f"[dim]No remotes configured on {store_path}[/dim]")
            else:
                for rname, rurl in remotes.items():
                    console.print(f"[cyan]{rname}[/cyan]\t{rurl}")
            return

        if rcmd == "suggest":
            suggestions = suggest_store_remotes(
                host, moniker=report.get("moniker"), origin_url=report.get("origin")
            )
            if not suggestions:
                console.print(
                    "[dim]No provider suggestions "
                    f"(origin={report.get('origin') or '—'}). "
                    "Pass a URL to [bold]ta store remote set[/bold].[/dim]"
                )
                return
            table = Table(title="Suggested task-store remotes", box=None)
            table.add_column("Provider", style="cyan")
            table.add_column("Label")
            table.add_column("URL")
            table.add_column("Notes", style="dim")
            for s in suggestions:
                table.add_row(s.provider, s.label, s.url, s.notes)
            console.print(table)
            console.print("\n[dim]Apply with: ta store remote set <url>[/dim]")
            return

        if rcmd == "set":
            raw_url = getattr(args, "url", None)
            if not raw_url or not isinstance(raw_url, str):
                console.print("[red]Usage: ta store remote set <url>[/red]")
                raise SystemExit(1)
            if not store_path.is_dir():
                console.print(
                    f"[red]Store does not exist yet: {store_path}[/red]\n"
                    "[dim]Run [bold]ta store migrate[/bold] first.[/dim]"
                )
                raise SystemExit(1)
            remote_name = getattr(args, "name", None) or "origin"
            if not isinstance(remote_name, str):
                remote_name = "origin"
            try:
                info = set_store_remote(
                    store_path,
                    raw_url,
                    remote_name=remote_name,
                    moniker=report.get("moniker"),
                )
            except Exception as e:
                console.print(f"[red]Failed to set remote:[/red] {e}")
                raise SystemExit(1)
            console.print(
                f"[green]Remote {info['remote_name']} {info['action']}:[/green] {info['url']}"
            )
            console.print(f"[dim]Store: {info['store_path']}[/dim]")
            return

        console.print("[yellow]Usage: ta store remote {show|suggest|set}[/yellow]")
        return

    if sub == "migrate":
        host = Path(args.path).resolve() if getattr(args, "path", None) else Path.cwd()
        dry_run = bool(getattr(args, "dry_run", False))
        result = migrate_store(host, dry_run=dry_run)
        plan = result.plan
        if getattr(args, "json", False):
            console.print_json(data=result.to_dict())
            if not result.success:
                raise SystemExit(1)
            return

        console.print(f"[bold]Host[/bold]:     {plan.host_path}")
        console.print(f"[bold]Moniker[/bold]:  {plan.moniker}")
        console.print(f"[bold]Kind[/bold]:     {plan.kind or '—'}")
        console.print(f"[bold]Source[/bold]:   {plan.source or '—'}")
        console.print(f"[bold]Dest[/bold]:     {plan.destination}")
        if plan.remotes_before:
            console.print(f"[bold]Remotes[/bold]:  {plan.remotes_before}")
        if plan.warnings:
            for w in plan.warnings:
                console.print(f"[yellow]Warning:[/yellow] {w}")
        if plan.errors:
            for err in plan.errors:
                console.print(f"[red]Error:[/red] {err}")
        console.print("\n[bold]Steps:[/bold]")
        for s in plan.steps:
            console.print(f"  • {s}")
        if result.applied_steps and not dry_run:
            console.print("\n[bold]Applied:[/bold]")
            for s in result.applied_steps:
                console.print(f"  ✓ {s}")

        if result.success:
            style = "green" if not dry_run else "cyan"
            label = "Dry-run OK" if dry_run else "Success"
            console.print(f"\n[{style}]{label}:[/{style}] {result.message}")
        else:
            console.print(f"\n[red]Failed:[/red] {result.message}")
            raise SystemExit(1)
        return

    console.print(f"[red]Unknown store command: {sub}[/red]")


def cmd_eject_mission(console: Console, manager: TaskAgent, public: bool = False):
    """Deprecated: move docs/tasks to a separate in-repo eject location.

    Prefer ``ta store migrate`` to centralize under the machine data root.
    This command remains for compatibility and still ejects into
    ``.task-agent/tasks`` (then you can migrate).
    """
    console.print(
        "[yellow]Deprecated:[/yellow] [bold]ta eject-mission[/bold] is superseded by "
        "[bold]ta store migrate[/bold] (machine data root).\n"
        "[dim]Continuing with legacy in-repo eject for compatibility…[/dim]\n"
    )
    source_dir = manager.issues_root
    if source_dir.is_symlink():
        console.print(
            "[yellow]docs/tasks is already a symlink. "
            "If it points at a legacy path, run [bold]ta store migrate[/bold].[/yellow]"
        )
        return

    if not source_dir.exists():
        console.print(f"[red]Source directory {source_dir} not found.[/red]")
        return

    # Determine names
    project_root = Path.cwd()
    target_path = project_root / ".task-agent" / "tasks"

    if target_path.exists():
        console.print(f"[red]Target path {target_path} already exists. Aborting.[/red]")
        return

    console.print(f"[blue]Ejecting mission to [bold]{target_path}[/bold]...[/blue]")

    try:
        # 1. Verify GH CLI
        subprocess.run(
            ["gh", "--version"],
            check=True,
            capture_output=True,
            shell=(os.name == "nt"),
        )

        # 2. Create target and move files
        target_path.mkdir(parents=True)
        for item in source_dir.iterdir():
            shutil.move(str(item), str(target_path / item.name))

        # 3. Git Init and Create Repo
        subprocess.run(
            ["git", "-C", str(target_path), "init"], check=True, shell=(os.name == "nt")
        )

        # Calculate relative path for git operations and gitignore
        project_root = Path.cwd()
        git_rel_path = source_dir.absolute().relative_to(project_root.absolute())

        # Add everything to new repo
        subprocess.run(
            ["git", "-C", str(target_path), "add", "."],
            check=True,
            shell=(os.name == "nt"),
        )
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
            shell=(os.name == "nt"),
        )

        # gh repo create
        visibility = "--public" if public else "--private"
        console.print(
            f"[blue]Creating GitHub repository [bold]{target_path.name}[/bold] ({visibility})...[/blue]"
        )
        subprocess.run(
            [
                "gh",
                "repo",
                "create",
                target_path.name,
                visibility,
                "--source=.",
                "--remote=origin",
                "--push",
            ],
            cwd=str(target_path),
            check=True,
            shell=(os.name == "nt"),
        )

        # 4. Remove old dir and Symlink
        # First remove from git if tracked
        subprocess.run(
            ["git", "rm", "-r", "--cached", str(git_rel_path)],
            check=False,
            capture_output=True,
            shell=(os.name == "nt"),
        )
        shutil.rmtree(str(source_dir))

        # Use an absolute symlink for maximum local robustness
        os.symlink(str(target_path.absolute()), str(source_dir))

        # 5. Update .gitignore
        gitignore = project_root / ".gitignore"
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
            "\nTA_EJECT_TASKS=true\n",
            f"TA_EJECTED_TASKS_PATH={target_path.absolute()}\n",
        ]
        if env_file.exists():
            content = env_file.read_text()
            with env_file.open("a") as f:
                if "TA_EJECT_TASKS" not in content:
                    f.write(env_lines[0])
                if "TA_EJECTED_TASKS_PATH" not in content:
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
        console.print("  - Configured [cyan]TA_EJECTED_TASKS_PATH[/cyan] in .env")
        console.print("\n[dim]The symlink will now 'auto-heal' in new worktrees.[/dim]")

    except subprocess.CalledProcessError as e:
        console.print(f"[red]Command failed: {e}[/red]")
        if e.stderr:
            console.print(f"[dim]{e.stderr.decode()}[/dim]")
    except Exception as e:
        console.print(f"[red]An error occurred: {e}[/red]")


def cmd_mr_list(console: Console, manager: TaskAgent):
    """List pending merge requests from workers."""
    mr_dir = manager.issues_root / "mr"
    if not mr_dir.exists():
        console.print("[yellow]Merge request directory not found.[/yellow]")
        return

    mrs = list(mr_dir.glob("*.md")) + list(mr_dir.glob("*.json"))
    if not mrs:
        console.print("[blue]No pending merge requests.[/blue]")
        return

    table = Table(
        title="Pending Merge Requests",
        box=theme.table_box,
        header_style=theme.header_style,
        padding=theme.table_padding,
    )
    table.add_column("Slug", style="cyan")
    table.add_column("File", style="dim")

    for mr in mrs:
        table.add_row(mr.stem, str(mr.name))

    console.print(table)


def cmd_merge(
    console: Console,
    manager: TaskAgent,
    slug_part: str,
    message: Optional[str] = None,
    push: bool = False,
):
    """Finalize a task using a merge request datagram."""
    mr_dir = manager.issues_root / "mr"
    # Find the MR file
    matches = list(mr_dir.glob(f"{slug_part}*"))
    if not matches:
        console.print(f"[red]No merge request found for '{slug_part}'.[/red]")
        return

    if len(matches) > 1:
        console.print(f"[yellow]Multiple MRs match '{slug_part}':[/yellow]")
        for m in matches:
            console.print(f"  - {m.name}")
        return

    mr_file = matches[0]
    slug = mr_file.stem
    solution = mr_file.read_text(encoding="utf-8")

    console.print(f"[blue]Merging task [bold]{slug}[/bold]...[/blue]")

    try:
        _, code_hash = manager.complete_issue(
            slug,
            commit_message=message,
            should_commit=True,
            push_mission=push,
            solution_explanation=solution,
        )
        # Remove the MR file after successful merge
        mr_file.unlink()
        console.print(f"[bold green]Successfully merged '{slug}'.[/bold green]")
        if code_hash not in ["unknown", "failed"]:
            console.print(f"[dim]Committed as {code_hash}.[/dim]")
    except Exception as e:
        console.print(f"[red]Merge failed: {e}[/red]")


def cmd_new(
    console: Console,
    manager: TaskAgent,
    title: Optional[str],
    body: str,
    draft: bool,
    as_dir: bool = True,
    completion_criteria: Optional[str] = None,
    interactive: bool = False,
    blocked_by: Optional[str] = None,
    subtask_of: Optional[str] = None,
    bulk: Optional[str] = None,
):
    """Create a new issue."""
    if bulk:
        try:
            if bulk == "-":
                raw_data = sys.stdin.read()
            else:
                raw_data = Path(bulk).read_text(encoding="utf-8")

            tasks = json.loads(raw_data)
            if not isinstance(tasks, list):
                raise ValueError("Bulk JSON must be a list/array of task objects.")

            for idx, t in enumerate(tasks):
                t_title = t.get("title")
                t_criteria = t.get("completion_criteria")
                if not t_title:
                    console.print(
                        f"[red]Error at task {idx}: 'title' is required.[/red]"
                    )
                    continue
                if not t_criteria:
                    console.print(
                        f"[red]Error at task '{t_title}' (index {idx}): 'completion_criteria' is required.[/red]"
                    )
                    continue

                t_body = t.get("body", "")
                t_draft = t.get("draft", draft)
                t_blocked_by = t.get("blocked_by")
                t_subtask_of = t.get("subtask_of")
                t_as_dir = t.get("as_dir", as_dir)

                issue = manager.create_issue(
                    title=t_title,
                    body=t_body,
                    draft=t_draft,
                    as_dir=t_as_dir,
                    completion_criteria=t_criteria,
                    blocked_by=t_blocked_by,
                    subtask_of=t_subtask_of,
                )
                console.print(
                    f"[bold green]Created new issue: {issue.slug}[/bold green]"
                )
                issue_file = manager.find_issue_file(issue.slug)
                console.print(f"File: {issue_file}")
                if issue.subtask_of:
                    console.print(f"Subtask of: {issue.subtask_of}")
            return
        except Exception as e:
            console.print(f"[red]Error processing bulk tasks: {e}[/red]")
            sys.exit(1)

    if interactive:
        editor = get_editor()
        slug = manager.slugify(title or "new-task")
        temp_dir = manager.issues_root / "draft" / slug
        temp_dir.mkdir(parents=True, exist_ok=True)
        temp_file = temp_dir / "README.md"

        # Resolve relations for the template
        final_blocked_by = blocked_by or ""
        final_subtask_of = subtask_of or ""

        created_at = datetime.now().astimezone().isoformat()
        template = f"""---
created_at: {created_at}
---

# {title or "New Task"}

**Subtask of:** {final_subtask_of}
**Blocked by:** {final_blocked_by}

## Description



## Completion Criteria

{completion_criteria or ""}
"""
        temp_file.write_text(template, encoding="utf-8")

        subprocess.run([editor, str(temp_file)], check=True)

        manager.init_project()
        issues = manager.load_mission()
        new_issue = next((i for i in issues if i.slug == slug), None)
        if new_issue:
            console.print(
                f"[bold green]Created new issue: {new_issue.slug}[/bold green]"
            )
            console.print(f"File: {temp_file}")
        else:
            console.print("[yellow]Task not created.[/yellow]")
            shutil.rmtree(temp_dir)
        return

    if not title:
        console.print("[red]Error: title is required for non-interactive mode.[/red]")
        sys.exit(1)

    try:
        issue = manager.create_issue(
            title=title,
            body=body,
            draft=draft,
            as_dir=as_dir,
            completion_criteria=completion_criteria,
            blocked_by=blocked_by,
            subtask_of=subtask_of,
        )
        console.print(f"[bold green]Created new issue: {issue.slug}[/bold green]")
        issue_file = manager.find_issue_file(issue.slug)
        console.print(f"File: {issue_file}")
        if issue.subtask_of:
            console.print(f"Subtask of: {issue.subtask_of}")
        if issue.blocked_by:
            console.print(f"Blocked by: {', '.join(issue.blocked_by)}")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)


def cmd_tree(console: Console, manager: TaskAgent):
    """Display the task hierarchy as a dependency tree."""
    issues = manager.sync_mission()
    if not issues:
        console.print("[yellow]No tasks found.[/yellow]")
        return

    slug_to_issue = {i.slug: i for i in issues}
    completed_slugs = {i.slug for i in issues if i.status == "completed"}
    # Also include completed tasks not in mission.usv
    completed_slugs.update(slug for _, slug in manager.walk_completed())

    # Build children_map using subtask_of (hierarchy)
    children_map: Dict[str, List[str]] = {}
    for i in issues:
        if i.subtask_of and i.subtask_of in slug_to_issue:
            children_map.setdefault(i.subtask_of, []).append(i.slug)

    visited: Set[str] = set()
    tree_lines: List[Tuple[Issue, int]] = []

    def build_rows(issue: Issue, depth: int):
        if issue.slug in visited:
            return
        visited.add(issue.slug)
        tree_lines.append((issue, depth))
        if issue.slug in children_map:
            for child_slug in children_map[issue.slug]:
                if child_slug in slug_to_issue:
                    build_rows(slug_to_issue[child_slug], depth + 1)

    # Root nodes: tasks with no subtask_of parent in the issue set
    for issue in issues:
        if not issue.subtask_of or issue.subtask_of not in slug_to_issue:
            build_rows(issue, 0)

    # Catch any remaining unvisited (shouldn't happen, but defensive)
    for issue in issues:
        if issue.slug not in visited:
            build_rows(issue, 0)

    for issue, depth in tree_lines:
        indent = "  " * depth
        connector = "└─ " if depth > 0 else ""
        status_symbol = {
            "active": "●",
            "pending": "○",
            "draft": "◌",
            "completed": "✔",
        }.get(issue.status, "?")
        active_blockers = [b for b in issue.blocked_by if b not in completed_slugs]
        deps = (
            f"  [dim](blocked by: {', '.join(active_blockers)})[/dim]"
            if active_blockers
            else ""
        )
        console.print(f"{indent}{connector}{status_symbol} {issue.slug}{deps}")


def cmd_list(
    console: Console,
    manager: TaskAgent,
    output_format: str = "table",
):
    """List all issues in mission.usv."""
    if output_format == "table":
        maybe_show_strategy(console, manager)
    issues = manager.sync_mission()
    if not issues:
        if output_format == "json":
            print("[]")
        else:
            console.print(f"[yellow]No issues found in {manager.mission_path}[/yellow]")
        return

    # Build hierarchy for display — nest by subtask_of only, not blocked_by
    slug_to_issue = {i.slug: i for i in issues}
    completed_slugs = {i.slug for i in issues if i.status == "completed"}
    completed_slugs.update(slug for _, slug in manager.walk_completed())
    children_map: Dict[str, List[str]] = {}
    for i in issues:
        if i.subtask_of and i.subtask_of in slug_to_issue:
            if i.subtask_of not in children_map:
                children_map[i.subtask_of] = []
            children_map[i.subtask_of].append(i.slug)

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

    # Root nodes: tasks with no subtask_of parent in the issue set
    for issue in issues:
        if not issue.subtask_of or issue.subtask_of not in slug_to_issue:
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
                    "created": get_created_date(manager, i.slug),
                    "status": i.status,
                    "name": i.name,
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
            created_date = get_created_date(manager, i.slug)
            console.print(
                f"{i.priority:<3} {created_date:<16} {i.status:<8} {i.name:<30} {indent}{prefix}{i.slug:<30} {deps:<20} {location}"
            )
        return

    table = Table(
        title="Task Queue",
        box=theme.table_box,
        header_style=theme.header_style,
        padding=theme.table_padding,
    )
    table.add_column("Pri", justify="right", style="cyan", width=3)
    table.add_column("Date", style="dim", width=5)
    table.add_column("Status", width=6)
    table.add_column("Blocked", style="yellow", width=8)
    table.add_column("Slug")

    for issue, depth in rows_to_display:
        status_style = "white"
        if issue.status == "active":
            status_style = "bold green"
        elif issue.status == "pending":
            status_style = "bold yellow"
        elif issue.status == "draft":
            status_style = "dim"
        elif issue.status == "completed":
            status_style = "bold blue"

        indent = "  " * depth
        prefix = "└─ " if depth > 0 else ""
        display_slug = f"{indent}{prefix}{issue.slug}"
        created_date = get_created_date(manager, issue.slug)
        # Shorten to MM-DD
        if len(created_date) >= 10:
            created_date = created_date[5:10]

        active_blockers = [b for b in issue.blocked_by if b not in completed_slugs]
        blocked_str = ""
        if active_blockers:
            # Show priority numbers of blockers
            blocker_priorities = []
            for b in active_blockers:
                if b in slug_to_issue:
                    blocker_priorities.append(str(slug_to_issue[b].priority))
                else:
                    blocker_priorities.append(b[:4])
            blocked_str = " ".join(blocker_priorities)

        table.add_row(
            str(issue.priority),
            f"[dim]{created_date}[/dim]",
            f"[{status_style}]{issue.status.upper()}[/{status_style}]",
            f"[yellow]{blocked_str}[/yellow]" if blocked_str else "",
            display_slug,
        )
    console.print(table)


def _parse_created_at(manager: TaskAgent, slug: str) -> Optional[datetime]:
    """Parse created_at from frontmatter as a datetime object."""
    try:
        issue_file = manager.find_issue_file(slug, include_completed=True)
        if issue_file and issue_file.exists():
            content = issue_file.read_text(encoding="utf-8")
            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    for line in parts[1].splitlines():
                        if line.strip().startswith("created_at:"):
                            raw_val = line.split(":", 1)[1].strip()
                            try:
                                return datetime.fromisoformat(raw_val)
                            except ValueError:
                                for fmt in (
                                    "%Y-%m-%d %H:%M",
                                    "%Y-%m-%d %H:%M:%S",
                                    "%Y-%m-%d",
                                ):
                                    try:
                                        return datetime.strptime(raw_val, fmt)
                                    except ValueError:
                                        pass
            stat = issue_file.stat()
            birthtime = getattr(stat, "st_birthtime", None)
            t = birthtime if birthtime is not None else stat.st_mtime
            return datetime.fromtimestamp(t)
    except Exception:
        pass
    return None


def _format_age(dt: Optional[datetime]) -> str:
    """Format a timedelta as a human-readable age string."""
    if dt is None:
        return "?"
    now = datetime.now(tz=dt.tzinfo) if dt.tzinfo else datetime.now()
    delta = now - dt
    days = delta.days
    hours = delta.seconds // 3600
    if days > 365:
        y = days // 365
        return f"{y}y"
    if days > 30:
        m = days // 30
        return f"{m}mo"
    if days > 0:
        return f"{days}d"
    if hours > 0:
        return f"{hours}h"
    mins = delta.seconds // 60
    return f"{mins}m"


def cmd_dashboard(console: Console, manager: TaskAgent):
    """Show a live dashboard of all task stations."""
    issues = manager.sync_mission()

    completed_pairs = manager.walk_completed()
    completed_slugs = {slug for _, slug in completed_pairs}

    # Group by status
    stations: Dict[str, List[Issue]] = {}
    for issue in issues:
        stations.setdefault(issue.status, []).append(issue)

    # ── Station summary table ──
    station_table = Table(
        title="Stations",
        box=theme.table_box,
        header_style=theme.header_style,
        padding=theme.table_padding,
    )
    station_table.add_column("Station", style="cyan", no_wrap=True)
    station_table.add_column("Count", justify="right")
    station_table.add_column("Oldest", style="dim")

    station_order = ["active", "pending", "draft", "mr", "completed", "deleted"]
    total = 0
    for name in station_order:
        if name == "completed":
            count = len(completed_pairs)
        elif name == "deleted":
            deleted_root = manager.issues_root / "deleted"
            if deleted_root.exists():
                count = sum(1 for _ in deleted_root.iterdir())
            else:
                count = 0
        elif name == "mr":
            mr_root = manager.issues_root / "mr"
            if mr_root.exists():
                count = sum(
                    1 for f in mr_root.iterdir() if f.is_file() and f.suffix == ".md"
                )
            else:
                count = 0
        else:
            count = len(stations.get(name, []))
        total += count

        # Find oldest item age in this station
        oldest_dt: Optional[datetime] = None
        if name == "completed":
            for fpath, slug in completed_pairs:
                dt = _parse_created_at(manager, slug)
                if dt and (oldest_dt is None or dt < oldest_dt):
                    oldest_dt = dt
        elif name == "deleted":
            deleted_root = manager.issues_root / "deleted"
            if deleted_root.exists():
                for entry in deleted_root.iterdir():
                    slug = entry.stem if entry.is_file() else entry.name
                    dt = _parse_created_at(manager, slug)
                    if dt and (oldest_dt is None or dt < oldest_dt):
                        oldest_dt = dt
        elif name == "mr":
            mr_root = manager.issues_root / "mr"
            if mr_root.exists():
                for f in mr_root.iterdir():
                    if f.is_file() and f.suffix == ".md":
                        dt = _parse_created_at(manager, f.stem)
                        if dt and (oldest_dt is None or dt < oldest_dt):
                            oldest_dt = dt
        else:
            for issue in stations.get(name, []):
                dt = _parse_created_at(manager, issue.slug)
                if dt and (oldest_dt is None or dt < oldest_dt):
                    oldest_dt = dt

        style = ""
        if name == "active":
            style = "bold green"
        elif name == "pending":
            style = "bold yellow"
        elif name == "draft":
            style = "dim"

        station_table.add_row(
            f"[{style}]{name}[/{style}]" if style else name,
            str(count),
            _format_age(oldest_dt),
        )

    station_table.add_row("", "", "")
    station_table.add_row("[bold]total[/bold]", f"[bold]{total}[/bold]", "")

    console.print(
        Panel(
            station_table,
            title="[bold]Dashboard[/bold]",
            subtitle=f"[dim]{manager.issues_root}[/dim]",
            box=theme.panel_box,
            expand=False,
        )
    )

    # ── Blocked-chain view ──
    slug_to_issue = {i.slug: i for i in issues}
    blocked = [i for i in issues if i.status in ("pending", "draft") and i.blocked_by]
    if blocked:
        bt = Table(
            title="Blocked Tasks",
            box=theme.table_box,
            header_style=theme.header_style,
            padding=theme.table_padding,
        )
        bt.add_column("Task", style="cyan")
        bt.add_column("Blocked by")
        bt.add_column("Age", style="dim")

        for issue in blocked:
            blockers = []
            for b in issue.blocked_by:
                if b in slug_to_issue:
                    blockers.append(f"[yellow]{b}[/yellow]")
                elif b in completed_slugs:
                    blockers.append(f"[green]{b} (done)[/green]")
                else:
                    blockers.append(f"[red]{b} (missing)[/red]")
            dt = _parse_created_at(manager, issue.slug)
            bt.add_row(
                issue.slug,
                ", ".join(blockers),
                _format_age(dt),
            )
        console.print(bt)
    else:
        console.print("[green]No blocked tasks.[/green]")

    # ── Active tasks dwell time ──
    active = stations.get("active", [])
    if active:
        at = Table(
            title="Active Tasks",
            box=theme.table_box,
            header_style=theme.header_style,
            padding=theme.table_padding,
        )
        at.add_column("Slug", style="green")
        at.add_column("Name")
        at.add_column("Dwell", style="yellow")

        for issue in active:
            dt = _parse_created_at(manager, issue.slug)
            at.add_row(issue.slug, issue.name, _format_age(dt))
        console.print(at)


def cmd_ingest(console: Console, manager: TaskAgent):
    """Ingest existing markdown files into mission.usv."""
    cmd_init(console, manager)


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
    """Demote an issue: active -> pending, or pending -> draft."""
    issues = manager.load_mission()
    target = select_issue(
        console, issues, slug_part, status_filter=["pending", "active"]
    )
    if not target:
        console.print(
            f"[red]No pending or active issue found matching '{slug_part}'.[/red]"
        )
        return
    try:
        to_status = "pending" if target.status == "active" else "draft"
        manager.demote_issue(target.slug)
        console.print(
            f"[bold green]Issue '{target.slug}' demoted to {to_status}.[/bold green]"
        )
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def cmd_active(
    console: Console,
    manager: TaskAgent,
    slug_part: Optional[str] = None,
    silent: bool = False,
    list_if_none: bool = False,
) -> Optional[Issue]:
    """Move an issue to active status, or list active tasks."""
    issues = manager.load_mission()
    if not slug_part and list_if_none and not silent:
        maybe_show_strategy(console, manager)
    if not slug_part and list_if_none:
        active_issues = [i for i in issues if i.status == "active"]
        if not silent:
            if active_issues:
                from rich.table import Table

                table = Table(
                    title="Active Tasks",
                    box=theme.table_box,
                    header_style=theme.header_style,
                    padding=theme.table_padding,
                )
                table.add_column("Priority")
                table.add_column("Slug")
                table.add_column("Dependencies")
                for i in active_issues:
                    deps = ", ".join(i.dependencies) if i.dependencies else "-"
                    table.add_row(str(i.priority), i.slug, deps)
                console.print(table)
            else:
                console.print("[yellow]No active tasks found.[/yellow]")
        return None

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


def cmd_update(
    console: Console,
    manager: TaskAgent,
    slug_part: str,
    blocked_by: Optional[str] = None,
    subtask_of: Optional[str] = None,
    add_blocked_by: Optional[str] = None,
    remove_blocked_by: Optional[str] = None,
):
    """Update task properties (single slug or comma-separated bulk)."""
    if (
        blocked_by is None
        and subtask_of is None
        and add_blocked_by is None
        and remove_blocked_by is None
    ):
        console.print(
            "[yellow]No updates specified. Use --blocked-by, --add-blocked-by, "
            "--remove-blocked-by, or --subtask-of.[/yellow]"
        )
        return

    raw_parts = [p.strip() for p in slug_part.split(",") if p.strip()]
    is_bulk = len(raw_parts) > 1

    def _resolve_many(parts: list[str]) -> list[str]:
        slugs: list[str] = []
        for p in parts:
            resolved = manager.resolve_issue_slug(p) or manager.slugify(p)
            slugs.append(resolved)
        return slugs

    try:
        if is_bulk:
            slugs = _resolve_many(raw_parts)
            if blocked_by is not None:
                results = manager.bulk_update_dependencies(slugs, blocked_by)
                ok = sum(1 for r in results if r["ok"])
                fail = len(results) - ok
                console.print(
                    f"[bold]blocked_by[/bold] bulk update: "
                    f"[green]{ok} ok[/green], [red]{fail} failed[/red]"
                )
                for r in results:
                    if r["ok"]:
                        console.print(f"  [green]OK[/green] {r['slug']}")
                    else:
                        console.print(f"  [red]FAIL[/red] {r['slug']}: {r['error']}")
            if add_blocked_by is not None:
                for s in slugs:
                    try:
                        manager.add_dependency(s, add_blocked_by)
                        console.print(f"  [green]OK[/green] add-blocked-by {s}")
                    except Exception as e:
                        console.print(f"  [red]FAIL[/red] add-blocked-by {s}: {e}")
            if remove_blocked_by is not None:
                for s in slugs:
                    try:
                        manager.remove_dependency(s, remove_blocked_by)
                        console.print(f"  [green]OK[/green] remove-blocked-by {s}")
                    except Exception as e:
                        console.print(f"  [red]FAIL[/red] remove-blocked-by {s}: {e}")
            if subtask_of is not None:
                parent_slug = subtask_of if subtask_of != "" else None
                results = manager.bulk_update_subtask_of(slugs, parent_slug)
                ok = sum(1 for r in results if r["ok"])
                fail = len(results) - ok
                console.print(
                    f"[bold]subtask_of[/bold] bulk update: "
                    f"[green]{ok} ok[/green], [red]{fail} failed[/red]"
                )
                for r in results:
                    if r["ok"]:
                        console.print(f"  [green]OK[/green] {r['slug']}")
                    else:
                        console.print(f"  [red]FAIL[/red] {r['slug']}: {r['error']}")
            return

        issues = manager.load_mission()
        target = select_issue(
            console, issues, slug_part, status_filter=["pending", "draft", "active"]
        )
        if not target:
            console.print(
                f"[red]No active/pending/draft task found matching '{slug_part}'.[/red]"
            )
            sys.exit(1)

        if blocked_by is not None:
            manager.update_dependencies(target.slug, blocked_by)
            console.print(
                f"[bold green]Successfully updated prerequisites for task '{target.slug}'.[/bold green]"
            )

        if add_blocked_by is not None:
            issue = manager.add_dependency(target.slug, add_blocked_by)
            console.print(
                f"[bold green]Added blockers on '{target.slug}'. "
                f"Now: {', '.join(issue.blocked_by) if issue.blocked_by else '(none)'}[/bold green]"
            )

        if remove_blocked_by is not None:
            issue = manager.remove_dependency(target.slug, remove_blocked_by)
            console.print(
                f"[bold green]Removed blockers from '{target.slug}'. "
                f"Now: {', '.join(issue.blocked_by) if issue.blocked_by else '(none)'}[/bold green]"
            )

        if subtask_of is not None:
            # Empty string means clear the parent
            parent_slug = subtask_of if subtask_of != "" else None
            manager.update_subtask_of(target.slug, parent_slug)
            console.print(
                f"[bold green]Successfully updated parent relationship for task '{target.slug}'.[/bold green]"
            )
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)


def cmd_start(
    console: Console,
    manager: TaskAgent,
    slug_part: Optional[str] = None,
    run: bool = False,
    agent_name: Optional[str] = None,
):
    """Move an issue to active and set up a git worktree."""
    target = cmd_active(console, manager, slug_part, silent=False)
    if not target:
        return

    slug = target.slug
    branch_name = f"issue/{slug}"
    worktree_path = Path(".gwt") / slug

    # Check if a worktree already exists for a different task
    result = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        capture_output=True,
        text=True,
        check=True,
    )
    worktrees = result.stdout.split("\n\n")
    if len(worktrees) > 2:  # main and at least one other
        console.print(
            "[red]Active worktree already exists. Please complete or shelf it first.[/red]"
        )
        if run:
            console.print("[blue]Invoking worker as requested...[/blue]")
            cmd_run(console, manager, slug, agent_name=agent_name)
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
            shell=(os.name == "nt"),
        )
        console.print(f"[bold green]Successfully started issue '{slug}'.[/bold green]")

        if agent_name:
            template_dir = Path(".ta") / "agents" / agent_name
            template_meta = template_dir / "meta.toml"
            if template_meta.exists():
                agent_info = agent.init_per_task_agent(slug, agent_name)
                agent_user = agent_info["user"]
                console.print(
                    f"[dim]Created per-task agent '{agent_user}' "
                    f"from template '{agent_name}'.[/dim]"
                )
            else:
                try:
                    agent_user = agent.get_agent_user(agent_name)
                    agent.set_worktree_permissions(slug, agent_user)
                    console.print(
                        f"[dim]Worktree permissions set for agent '{agent_user}'.[/dim]"
                    )
                except RuntimeError as e:
                    console.print(f"[yellow]Warning: {e}[/yellow]")

        if run:
            console.print("[blue]Invoking worker as requested...[/blue]")
            cmd_run(console, manager, slug, agent_name=agent_name)

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
        subprocess.run(
            ["uv", "tool", "upgrade", "task-agent"], check=True, shell=(os.name == "nt")
        )
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


def cmd_run(
    console: Console,
    manager: TaskAgent,
    slug_part: Optional[str] = None,
    agent_name: Optional[str] = None,
):
    """Run the sidecar worker for an issue. Optionally run as an agent user."""
    issues = manager.load_mission()
    target = select_issue(console, issues, slug_part, status_filter=["active"])
    if not target:
        if slug_part:
            console.print(f"[red]No active issue found matching '{slug_part}'.[/red]")
        else:
            console.print("[yellow]No active issues found to run.[/yellow]")
        return

    issue_file = manager.find_issue_file(target.slug)
    worker_ext = ".bat" if os.name == "nt" else ""
    worker_executable = Path(".ta") / f"worker{worker_ext}"
    if not worker_executable.exists():
        console.print(f"[red]Sidecar worker not found at {worker_executable}[/red]")
        console.print("[blue]Run 'ta init-worker' to set up a reference worker.[/blue]")
        return

    env = os.environ.copy()
    env["TA_SLUG"] = target.slug
    env["TA_FILE"] = str(issue_file.absolute()) if issue_file else ""
    env["TA_ROOT"] = str(Path.cwd().absolute())

    try:
        if agent_name:
            meta = agent.load_per_task_agent_meta(target.slug)
            if meta:
                agent_user = meta["user"]
            else:
                template_dir = Path(".ta") / "agents" / agent_name
                template_meta = template_dir / "meta.toml"
                if template_meta.exists():
                    result = agent.init_per_task_agent(target.slug, agent_name)
                    agent_user = result["user"]
                else:
                    agent_user = agent.get_agent_user(agent_name)

            worktree_path = agent.get_worktree_path(target.slug)

            ta_file = shlex.quote(str(issue_file.absolute())) if issue_file else ""
            shell_cmd = (
                f"cd {shlex.quote(str(worktree_path))} && "
                f"exec env "
                f"TA_SLUG={shlex.quote(target.slug)} "
                f"TA_FILE={ta_file} "
                f"TA_ROOT={shlex.quote(str(Path.cwd().absolute()))} "
                f"{shlex.quote(str(worker_executable.absolute()))}"
            )
            subprocess.run(
                ["sudo", "-u", agent_user, "bash", "-l", "-c", shell_cmd],
                check=True,
            )
        else:
            subprocess.run(
                [str(worker_executable.absolute())],
                env=env,
                check=True,
                shell=(os.name == "nt"),
            )
        console.print(
            f"[bold green]Worker for '{target.slug}' finished successfully.[/bold green]"
        )
    except Exception as e:
        console.print(f"[red]Worker failed: {e}[/red]")


def cmd_plan(console: Console, manager: TaskAgent):
    """View or edit the project plan."""
    plan_file = manager.get_or_create_plan()
    editor = get_editor()
    subprocess.run([editor, str(plan_file)])


def cmd_init(console: Console, manager: TaskAgent):
    """Initialize or heal the project."""
    console.print("[blue]Initializing Task Agent project...[/blue]")
    num_new, num_removed = manager.init_project()
    console.print(
        f"[bold green]Task Agent initialized at {manager.issues_root}[/bold green]"
    )
    if num_new > 0 or num_removed > 0:
        console.print(
            f"[dim]Ingested {num_new} new issues, removed {num_removed} missing ones.[/dim]"
        )
    console.print("[dim]Mission files are protected (Read-Only).[/dim]")


def cmd_list_templates(console: Console):
    """List available agent templates from .ta/agents/."""
    from taskagent import templates

    agents_dir = Path(".ta") / "agents"
    if not agents_dir.is_dir():
        console.print("[yellow]No templates found in .ta/agents/[/yellow]")
        return

    table = Table(
        title="Available Templates",
        box=theme.table_box,
        header_style=theme.header_style,
        padding=theme.table_padding,
    )
    table.add_column("Name", style="cyan")
    table.add_column("Description")

    for d in sorted(agents_dir.iterdir()):
        if d.is_dir():
            meta_file = d / "meta.toml"
            if meta_file.exists():
                try:
                    t = templates.load_template(d.name)
                    table.add_row(t.name, t.description)
                except Exception:
                    table.add_row(d.name, "[dim]invalid meta.toml[/dim]")
            else:
                table.add_row(d.name, "[dim]no meta.toml[/dim]")

    console.print(table)


def cmd_init_agent(
    console: Console, name: str, template: Optional[str] = None, op_timeout: int = 30
):
    """Create a dedicated Linux user for agent isolation."""
    try:
        result = agent.init_agent(name, template_name=template, op_timeout=op_timeout)
        console.print(
            f"[bold green]Agent user '{result['user']}' created.[/bold green]"
        )
        console.print(f"  Home:    [cyan]{result['home']}[/cyan]")
        console.print(f"  SSH key: [cyan]{result['ssh_key']}[/cyan]")
        console.print(f"  Gitconfig: [cyan]{result['gitconfig']}[/cyan]")
        console.print(f"  Sudoers:  [cyan]{result['sudoers']}[/cyan]")
        console.print(
            "\n[dim]Use [bold]ta run <slug> --agent <name>[/bold] "
            "to run tasks as this agent.[/dim]"
        )
    except RuntimeError as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)


def cmd_destroy_agent(console: Console, name: str):
    """Remove an agent Linux user."""
    try:
        agent.destroy_agent(name)
        console.print(f"[bold green]Agent user 'agent-{name}' removed.[/bold green]")
    except RuntimeError as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)


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

    worker_script = target_ta_dir / ("worker.bat" if os.name == "nt" else "worker")
    if os.name == "nt":
        script_content = f"@echo off\nuv run --project {target_sidecar_dir} python {target_sidecar_dir}/worker.py %*\n"
    else:
        script_content = f'#!/usr/bin/env bash\nuv run --project {target_sidecar_dir} python {target_sidecar_dir}/worker.py "$@"\n'

    worker_script.write_text(script_content, encoding="utf-8")
    if os.name != "nt":
        worker_script.chmod(0o755)
    console.print(
        f"[bold green]Successfully initialized {template} worker![/bold green]"
    )


def cmd_mcp():
    """Launch the Model Context Protocol server."""
    from taskagent.mcp import run_mcp_server

    run_mcp_server()


# ... (in imports)


def cmd_init_mcp(
    console: Console,
    agent: str = "gemini",
    print_json: bool = False,
    scope: str = "project",
    claude: bool = False,
):
    """Register the Task Agent as an MCP server.

    Uses ``uv run --project <root> ta mcp`` so the server can be spawned
    without the project's virtualenv being active in the calling shell.
    """
    project_root = Path.cwd().resolve()
    mcp_command = "uv"
    mcp_args = ["run", "--project", str(project_root), "ta", "mcp"]

    mcp_config = {
        "mcpServers": {
            "task_agent": {
                "command": mcp_command,
                "args": mcp_args,
            }
        }
    }

    if print_json:
        console.print(json.dumps(mcp_config, indent=2))
        return

    if claude:
        console.print("[blue]Registering Task Agent MCP with Claude Code...[/blue]")
        try:
            command = [
                "claude",
                "mcp",
                "add",
                "task_agent",
                "--",
                mcp_command,
            ] + mcp_args
            subprocess.run(command, check=True, shell=(os.name == "nt"))
            console.print(
                "[bold green]Successfully registered Task Agent MCP with Claude Code![/bold green]"
            )
        except subprocess.CalledProcessError as e:
            console.print(
                f"[red]Failed to register Claude MCP server via 'claude mcp add': {e}[/red]"
            )
            console.print(
                "[yellow]Make sure Claude Code CLI is installed and in your PATH.[/yellow]"
            )
        except FileNotFoundError:
            console.print("[red]Error: 'claude' command not found.[/red]")
            console.print(
                "[yellow]Make sure Claude Code CLI is installed and available in your PATH.[/yellow]"
            )
        return

    if agent == "gemini":
        console.print(
            f"[blue]Registering Task Agent as an MCP server ({scope} scope)...[/blue]"
        )
        command = [
            "gemini",
            "mcp",
            "add",
            "task_agent",
            mcp_command,
            *mcp_args,
            "--trust",
            "--scope",
            scope,
        ]
        try:
            subprocess.run(command, check=True, shell=(os.name == "nt"))
            console.print(
                "[bold green]Successfully registered Task Agent MCP server![/bold green]"
            )
        except subprocess.CalledProcessError as e:
            console.print(f"[red]Failed to register MCP server: {e}[/red]")
    elif agent == "opencode":
        if scope == "user":
            config_path = Path.home() / ".config" / "opencode" / "opencode.json"
            console.print(
                f"[blue]Installing Task Agent MCP globally at {config_path}...[/blue]"
            )
        else:
            config_path = Path.cwd() / "opencode.json"

        try:
            if config_path.exists():
                with config_path.open("r", encoding="utf-8") as f:
                    config = json.load(f)
            else:
                config = {}
            if "mcp" not in config:
                config["mcp"] = {}
            config["mcp"]["task_agent"] = {
                "type": "local",
                "command": [mcp_command, *mcp_args],
            }
            config_path.parent.mkdir(parents=True, exist_ok=True)
            with config_path.open("w", encoding="utf-8") as f:
                json.dump(config, f, indent=2)
            console.print(
                f"[bold green]Successfully registered Task Agent MCP at {config_path}![/bold green]"
            )
        except Exception as e:
            console.print(f"[red]Failed to register Task Agent MCP: {e}[/red]")


def cmd_version(
    console: Console,
    promote: Optional[str] = None,
    tag: bool = False,
    push: bool = True,
):
    """Show project version, promote it, or tag it."""
    display_version_info(console)

    if tag:
        v, source = get_committed_version()
        if v == "unknown":
            console.print(
                "[red]Error: Could not determine project version to tag.[/red]"
            )
            return

        # Warn if working tree differs from committed version
        working_v, _ = get_project_version()
        if working_v != v:
            console.print(
                f"[yellow]Warning: Working tree has version {working_v}, "
                f"but HEAD has {v}[/yellow]"
            )
            console.print(
                "[yellow]Committing changes with 'ta version promote' first is recommended.[/yellow]"
            )

        tag_name = f"v{v}"
        result = subprocess.run(
            ["git", "tag", tag_name],
            capture_output=True,
            shell=(os.name == "nt"),
        )
        if result.returncode != 0:
            console.print(f"[yellow]Tag {tag_name} already exists.[/yellow]")
        else:
            console.print(f"[bold green]Tagged commit as {tag_name}[/bold green]")

            if push:
                console.print(f"[blue]Pushing tag {tag_name} to origin...[/blue]")
                subprocess.run(
                    ["git", "push", "origin", tag_name],
                    check=True,
                    shell=(os.name == "nt"),
                )
                console.print(
                    f"[bold green]Successfully pushed {tag_name}[/bold green]"
                )

    if promote:
        _, source = get_project_version()
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
                shell=(os.name == "nt"),
            )
            if Path("uv.lock").exists():
                subprocess.run(["uv", "lock"], check=True, shell=(os.name == "nt"))
        elif source == "package.json":
            subprocess.run(
                ["npm", "version", promote, "--no-git-tag-version"],
                check=True,
                shell=(os.name == "nt"),
            )
        new_v, _ = get_project_version()
        console.print(f"[bold green]Promoted to version {new_v}[/bold green]")

        # Auto-amend version bump into previous commit
        try:
            for file in ["pyproject.toml", "package.json", "uv.lock"]:
                if Path(file).exists():
                    subprocess.run(
                        ["git", "add", file],
                        capture_output=True,
                        check=False,
                        shell=(os.name == "nt"),
                    )
            result = subprocess.run(
                ["git", "commit", "--amend", "--no-edit"],
                capture_output=True,
                shell=(os.name == "nt"),
            )
            if result.returncode == 0:
                console.print("[dim]Version bump amended into previous commit[/dim]")
            elif (
                b"nothing to commit" in result.stdout
                or b"nothing to commit" in result.stderr
            ):
                console.print(
                    "[yellow]No changes to commit (already amended?)[/yellow]"
                )
            else:
                console.print(
                    "[yellow]Warning: Could not auto-amend version bump. "
                    "Run 'git add' and 'git commit --amend --no-edit' manually.[/yellow]"
                )
                if result.stderr:
                    console.print(f"[dim]{result.stderr.decode()}[/dim]")
        except Exception as e:
            console.print(
                f"[yellow]Warning: Auto-amend failed: {e}. "
                "Run 'git commit --amend --no-edit' manually.[/yellow]"
            )


def promote_version(console: Console, manager: TaskAgent):
    """Auto-promote project version when a task is completed."""
    # Find the project root containing project files relative to manager's issues_root
    project_root = None
    if manager.issues_root:
        curr = Path(manager.issues_root).resolve()
        while curr.parent != curr:
            if (
                (curr / "pyproject.toml").exists()
                or (curr / "package.json").exists()
                or (curr / ".git").exists()
            ):
                project_root = curr
                break
            curr = curr.parent

    if not project_root:
        return

    _, source = get_project_version(project_root)
    if not source:
        return

    if source == "pyproject.toml":
        subprocess.run(
            [
                "uv",
                "run",
                "bump-my-version",
                "bump",
                "patch",
                "--no-commit",
                "--no-tag",
            ],
            check=True,
            cwd=str(project_root),
            shell=(os.name == "nt"),
        )
        if (project_root / "uv.lock").exists():
            subprocess.run(
                ["uv", "lock"],
                check=True,
                cwd=str(project_root),
                shell=(os.name == "nt"),
            )
    elif source == "package.json":
        subprocess.run(
            ["npm", "version", "patch", "--no-git-tag-version"],
            check=True,
            cwd=str(project_root),
            shell=(os.name == "nt"),
        )
    new_v, _ = get_project_version(project_root)
    console.print(f"[bold green]Promoted to version {new_v}[/bold green]")

    # Auto-amend version bump into previous commit
    try:
        git_root = None
        curr = project_root
        while curr.parent != curr:
            if (curr / ".git").exists():
                git_root = curr
                break
            curr = curr.parent

        if not git_root:
            return

        for file in ["pyproject.toml", "package.json", "uv.lock"]:
            if (project_root / file).exists():
                rel_path = (project_root / file).relative_to(git_root)
                subprocess.run(
                    ["git", "-C", str(git_root), "add", str(rel_path)],
                    capture_output=True,
                    check=False,
                    shell=(os.name == "nt"),
                )
        result = subprocess.run(
            ["git", "-C", str(git_root), "commit", "--amend", "--no-edit"],
            capture_output=True,
            shell=(os.name == "nt"),
        )
        if result.returncode == 0:
            console.print("[dim]Version bump amended into previous commit[/dim]")
        elif (
            b"nothing to commit" in result.stdout
            or b"nothing to commit" in result.stderr
        ):
            console.print("[yellow]No changes to commit (already amended?)[/yellow]")
        else:
            console.print(
                "[yellow]Warning: Could not auto-amend version bump. "
                "Run 'git add' and 'git commit --amend --no-edit' manually.[/yellow]"
            )
            if result.stderr:
                console.print(f"[dim]{result.stderr.decode()}[/dim]")
    except Exception as e:
        console.print(
            f"[yellow]Warning: Auto-amend failed: {e}. "
            "Run 'git commit --amend --no-edit' manually.[/yellow]"
        )


def cmd_worktree(console: Console, manager: TaskAgent, args):
    """Manage git worktrees for branches, tags, and commits."""
    import subprocess
    import os
    from pathlib import Path

    # Default worktree directory
    worktree_base = Path(".gwt")
    worktree_base.mkdir(exist_ok=True)

    # Show help if no action provided
    if not args.action:
        console.print("[bold blue]Worktree Management[/bold blue]")
        console.print()
        console.print("[bold]Available actions:[/bold]")
        console.print("  [cyan]add[/cyan]    - Create a new worktree (requires target)")
        console.print("  [cyan]list[/cyan]   - List all worktrees")
        console.print("  [cyan]remove[/cyan] - Remove a worktree (requires target)")
        console.print("  [cyan]prune[/cyan]   - Remove stale worktree information")
        console.print()
        console.print("[dim]Run 'ta worktree add --help' for detailed options.[/dim]")
        console.print(
            "[dim]Run 'ta worktree <action> --help' for action-specific help.[/dim]"
        )
        return

    if args.action == "add":
        if not args.target:
            console.print(
                "[red]Error: target (branch/tag/commit) is required for add action[/red]"
            )
            return

        # Determine what we're checking out
        if args.tag:
            ref = f"tags/{args.target}"
            display_name = f"tag:{args.target}"
        elif args.commit:
            ref = args.target
            display_name = f"commit:{args.target[:8]}"
        else:
            ref = args.target
            display_name = f"branch:{args.target}"

        # Create worktree path
        worktree_path = worktree_base / args.target
        worktree_path.mkdir(parents=True, exist_ok=True)

        try:
            # Add the worktree
            if args.tag or args.commit:
                # For tags/commits, we need to checkout the specific ref
                subprocess.run(
                    ["git", "worktree", "add", str(worktree_path), ref],
                    check=True,
                    capture_output=True,
                    text=True,
                    shell=(os.name == "nt"),
                )
            else:
                # For branches, create new branch if it doesn't exist
                subprocess.run(
                    ["git", "worktree", "add", "-B", args.target, str(worktree_path)],
                    check=True,
                    capture_output=True,
                    text=True,
                    shell=(os.name == "nt"),
                )

            console.print(
                f"[green]Added worktree for {display_name} at {worktree_path}[/green]"
            )

            # Set permissions if specified
            if args.permissions:
                try:
                    perms = int(args.permissions, 8)
                    os.chmod(worktree_path, perms)
                    console.print(f"[dim]Set permissions to {args.permissions}[/dim]")
                except ValueError:
                    console.print(
                        f"[yellow]Warning: Invalid permissions '{args.permissions}', using default[/yellow]"
                    )

            # Copy files if requested
            copy_patterns = args.copy or []
            if not args.no_symlinks:
                copy_patterns.append("symlinks")
            if not args.no_env:
                copy_patterns.append("*.env")

            if copy_patterns:
                _copy_files_to_worktree(console, worktree_path, copy_patterns)

            # Configure git user for this worktree if needed
            _configure_git_user_for_worktree(console, worktree_path, args.target)

        except subprocess.CalledProcessError as e:
            console.print(f"[red]Error creating worktree: {e.stderr}[/red]")
            # Clean up on failure
            if worktree_path.exists():
                subprocess.run(
                    ["git", "worktree", "remove", str(worktree_path)],
                    check=False,
                    shell=(os.name == "nt"),
                )
                try:
                    if not any(worktree_path.iterdir()):
                        worktree_path.rmdir()
                except (OSError, StopIteration):
                    pass

    elif args.action == "list":
        try:
            result = subprocess.run(
                ["git", "worktree", "list"],
                capture_output=True,
                text=True,
                check=True,
                shell=(os.name == "nt"),
            )
            if result.stdout.strip():
                console.print("[bold blue]Worktrees:[/bold blue]")
                for line in result.stdout.strip().split("\n"):
                    if line.strip():
                        console.print(f"  {line}")
            else:
                console.print("[yellow]No worktrees found[/yellow]")
        except subprocess.CalledProcessError as e:
            console.print(f"[red]Error listing worktrees: {e.stderr}[/red]")

    elif args.action == "remove":
        if not args.target:
            console.print(
                "[red]Error: target (worktree path) is required for remove action[/red]"
            )
            return

        worktree_path = Path(args.target)
        if not worktree_path.exists():
            console.print(
                f"[yellow]Worktree path {worktree_path} does not exist[/yellow]"
            )
            return

        try:
            subprocess.run(
                ["git", "worktree", "remove", str(worktree_path)],
                check=True,
                capture_output=True,
                text=True,
                shell=(os.name == "nt"),
            )
            console.print(f"[green]Removed worktree at {worktree_path}[/green]")
            # Try to remove the directory if empty
            try:
                worktree_path.rmdir()
            except OSError:
                pass  # Directory not empty, leave it
        except subprocess.CalledProcessError as e:
            console.print(f"[red]Error removing worktree: {e.stderr}[/red]")

    elif args.action == "prune":
        try:
            subprocess.run(
                ["git", "worktree", "prune"],
                check=True,
                capture_output=True,
                text=True,
                shell=(os.name == "nt"),
            )
            console.print("[green]Pruned stale worktrees[/green]")
        except subprocess.CalledProcessError as e:
            console.print(f"[red]Error pruning worktrees: {e.stderr}[/red]")


def cmd_github(console: Console, manager: TaskAgent, args):
    """Sync with GitHub Issues."""
    try:
        from taskagent.plugins.github import GitHubPlugin
    except ImportError:
        console.print("[red]GitHub plugin not installed. Run: uv add githubkit[/red]")
        return

    # Load config from .task-agent/worktree-config.json
    config = {}
    config_file = Path(".task-agent/worktree-config.json")
    if config_file.exists():
        try:
            with config_file.open("r", encoding="utf-8") as f:
                config = json.load(f)
        except Exception:
            pass

    # Override repo if specified in args
    if hasattr(args, "repo") and args.repo:
        if "github" not in config:
            config["github"] = {}
        config["github"]["repo"] = args.repo

    try:
        plugin = GitHubPlugin(config)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        return

    if args.github_command == "sync":
        try:
            issues = plugin.sync_from_github()
            console.print(f"[green]Imported {len(issues)} issues from GitHub[/green]")

            # Add issues to task-agent
            for issue in issues:
                try:
                    manager.create_issue(issue.name, body="Imported from GitHub")
                    console.print(f"  Added: {issue.name}")
                except Exception as e:
                    console.print(f"  [yellow]Skipped {issue.slug}: {e}[/yellow]")

            # Save mission
            manager.save_mission(manager.load_mission())
            console.print("[green]Mission file updated[/green]")
        except Exception as e:
            console.print(f"[red]Error syncing: {e}[/red]")

    elif args.github_command == "create":
        try:
            issue = None
            # Find the issue by slug
            issue_file = manager.find_issue_file(args.slug)
            if not issue_file:
                console.print(f"[red]Issue '{args.slug}' not found[/red]")
                return

            # Load issue details
            content = (
                issue_file.read_text()
                if issue_file.name == "README.md"
                else issue_file.read_text()
            )
            name = content.split("\n")[0].lstrip("#").strip()

            # Create GitHub issue
            from taskagent.models.issue import Issue

            temp_issue = Issue(name=name, slug=args.slug, dependencies=[])
            result = plugin.create_github_issue(temp_issue)

            console.print(f"[green]Created GitHub Issue #{result['number']}[/green]")
            console.print(f"URL: {result['url']}")
        except Exception as e:
            console.print(f"[red]Error creating issue: {e}[/red]")
    else:
        console.print("[yellow]Use 'sync' or 'create' subcommand[/yellow]")


def _copy_files_to_worktree(console: Console, worktree_path: Path, patterns: list):
    """Copy files matching patterns to the worktree directory."""
    import shutil

    repo_root = Path.cwd()

    for pattern in patterns:
        if pattern == "symlinks":
            # Find and copy symlinks
            for item in repo_root.rglob("*"):
                if item.is_symlink() and not any(
                    part.startswith(".gwt") for part in item.parts
                ):
                    relative_path = item.relative_to(repo_root)
                    target_path = worktree_path / relative_path
                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    try:
                        shutil.copy2(item, target_path)
                        console.print(f"[dim]Copied symlink: {relative_path}[/dim]")
                    except Exception as e:
                        console.print(
                            f"[yellow]Warning: Failed to copy symlink {relative_path}: {e}[/yellow]"
                        )
        else:
            # Handle glob patterns
            for item in repo_root.glob(pattern):
                if not any(part.startswith(".gwt") for part in item.parts):
                    relative_path = item.relative_to(repo_root)
                    target_path = worktree_path / relative_path
                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    try:
                        if item.is_dir():
                            shutil.copytree(item, target_path, dirs_exist_ok=True)
                        else:
                            shutil.copy2(item, target_path)
                        console.print(f"[dim]Copied: {relative_path}[/dim]")
                    except Exception as e:
                        console.print(
                            f"[yellow]Warning: Failed to copy {relative_path}: {e}[/yellow]"
                        )


def _configure_git_user_for_worktree(
    console: Console, worktree_path: Path, branch_name: str
):
    """Configure git user.email and user.name for a worktree based on branch."""
    import subprocess
    import json
    from pathlib import Path

    # Default to current user's git config
    try:
        # Get current git config
        user_name_result = subprocess.run(
            ["git", "config", "--get", "user.name"],
            capture_output=True,
            text=True,
            check=False,
        )
        user_email_result = subprocess.run(
            ["git", "config", "--get", "user.email"],
            capture_output=True,
            text=True,
            check=False,
        )

        user_name = (
            user_name_result.stdout.strip() if user_name_result.returncode == 0 else ""
        )
        user_email = (
            user_email_result.stdout.strip()
            if user_email_result.returncode == 0
            else ""
        )

        # Check for branch-specific git config
        # Look for .task-agent/worktree-config.json
        config_path = Path(".task-agent/worktree-config.json")
        if config_path.exists():
            try:
                with config_path.open("r", encoding="utf-8") as f:
                    config = json.load(f)
                    # Check if there's a specific config for this branch
                    branch_config = config.get("branches", {}).get(branch_name, {})
                    if branch_config:
                        user_name = branch_config.get("user.name", user_name)
                        user_email = branch_config.get("user.email", user_email)
                        console.print(
                            f"[dim]Using branch-specific config for '{branch_name}'[/dim]"
                        )
                    # Check for default config
                    elif "default" in config.get("branches", {}):
                        default_config = config["branches"]["default"]
                        user_name = default_config.get("user.name", user_name)
                        user_email = default_config.get("user.email", user_email)
                        console.print("[dim]Using default worktree config[/dim]")
            except Exception as e:
                console.print(
                    f"[yellow]Warning: Failed to read worktree config: {e}[/yellow]"
                )

        if user_name and user_email:
            # Set git config locally for this worktree
            subprocess.run(
                ["git", "-C", str(worktree_path), "config", "user.name", user_name],
                check=False,
                capture_output=True,
            )
            subprocess.run(
                ["git", "-C", str(worktree_path), "config", "user.email", user_email],
                check=False,
                capture_output=True,
            )
            console.print(
                f"[dim]Configured git user for worktree: {user_name} <{user_email}>[/dim]"
            )
        else:
            console.print(
                "[yellow]Warning: Could not determine git user from current config[/yellow]"
            )

    except Exception as e:
        console.print(
            f"[yellow]Warning: Failed to configure git user for worktree: {e}[/yellow]"
        )


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
    """Interactively prioritize and promote tasks."""
    show_completed = False

    def get_display_issues(search: Optional[str] = None, completed: bool = False):
        if completed:
            # Load completed issues from disk since they aren't in mission.usv
            all_issues = []
            for f, slug in manager.walk_completed():
                name = manager.extract_title(f)
                all_issues.append(
                    Issue(name=name, slug=slug, status="completed", priority=0)
                )
            issues = all_issues
        else:
            issues = manager.sync_mission()

        if search:
            issues = [i for i in issues if search.lower() in i.slug.lower()]
        return issues

    def build_hierarchy(issues: List[Issue]) -> List[Tuple[Issue, int]]:
        """Build a flat list with depth info for dependency hierarchy."""
        slug_to_issue = {i.slug: i for i in issues}
        children_map: Dict[str, List[str]] = {}
        for i in issues:
            for dep in i.dependencies:
                if dep in slug_to_issue:
                    if dep not in children_map:
                        children_map[dep] = []
                    children_map[dep].append(i.slug)

        visited: Set[str] = set()
        rows: List[Tuple[Issue, int]] = []

        def build_rows(issue: Issue, depth: int):
            if issue.slug in visited:
                return
            visited.add(issue.slug)
            rows.append((issue, depth))
            if issue.slug in children_map:
                for child_slug in children_map[issue.slug]:
                    if child_slug in slug_to_issue:
                        build_rows(slug_to_issue[child_slug], depth + 1)

        for issue in issues:
            has_internal_dep = any(dep in slug_to_issue for dep in issue.dependencies)
            if not has_internal_dep:
                build_rows(issue, 0)

        for issue in issues:
            if issue.slug not in visited:
                build_rows(issue, 0)

        return rows

    issues = get_display_issues(search_query, show_completed)
    if not issues and not search_query:
        console.print("[yellow]No issues to triage.[/yellow]")
        return

    # Build hierarchy for cursor mapping
    hierarchy = build_hierarchy(issues)
    # Map flat index to (issue, depth)
    indexed_issues = [(issue, depth) for issue, depth in hierarchy]
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
                box=theme.table_box,
                show_header=True,
                header_style=theme.header_style,
                padding=theme.table_padding,
            )
            table.add_column("Pos", justify="right", style="dim")
            table.add_column("Created", style="dim", width=16)
            table.add_column("Status", width=10)
            table.add_column("Slug")

            for idx, (issue, depth) in enumerate(indexed_issues):
                style = "bold cyan" if idx == cursor else "white"
                indent = "  " * depth
                prefix = "└─ " if depth > 0 else ""
                if idx == cursor:
                    display_slug = f"> [reverse]{indent}{prefix}{issue.slug}[/reverse]"
                else:
                    display_slug = f"  {indent}{prefix}{issue.slug}"

                status_style = "white"
                if issue.status == "active":
                    status_style = "bold green"
                elif issue.status == "pending":
                    status_style = "bold yellow"
                elif issue.status == "draft":
                    status_style = "dim"
                elif issue.status == "completed":
                    status_style = "bold blue"

                created_date = get_created_date(manager, issue.slug)

                table.add_row(
                    str(idx + 1) if not show_completed else "-",
                    f"[dim]{created_date}[/dim]",
                    f"[{status_style}]{issue.status.upper()}[/{status_style}]",
                    display_slug,
                    style=style,
                )

            help_text = "[dim]j/k: move | ctrl+k/j: prio | p: prom | d: dem | v: view | e: edit | a: add | D: done | A: active | l: depends on above | h: unlink dep | /: search | y: copy slug | q: exit[/dim]"

            live.update(
                Panel(table, subtitle=help_text, box=theme.panel_box), refresh=True
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
                indexed_issues = build_hierarchy(issues)
                cursor = 0
                live.start()
            elif key == "y":
                slug = indexed_issues[cursor][0].slug
                pyperclip.copy(slug)
                console.print(
                    f"[bold green]Copied slug to clipboard: {slug}[/bold green]"
                )
                questionary.press_any_key_to_continue().ask()
            elif key == "c":
                show_completed = not show_completed
                issues = get_display_issues(search_query, show_completed)
                indexed_issues = build_hierarchy(issues)
                cursor = 0
            elif key in ["k", "\x1b[A"]:  # up
                cursor = max(0, cursor - 1)
            elif key in ["j", "\x1b[B"]:  # down
                cursor = min(len(indexed_issues) - 1, cursor + 1)
            elif key == "v":
                live.stop()
                issue = indexed_issues[cursor][0]
                issue_file = manager.find_issue_file(
                    issue.slug, include_completed=show_completed
                )
                if issue_file:
                    render_issue(console, issue, issue_file, issues)
                else:
                    console.print(f"[red]Issue file not found for {issue.slug}[/red]")
                questionary.press_any_key_to_continue().ask()
                live.start()
            elif key == "e":
                live.stop()
                issue = indexed_issues[cursor][0]
                issue_file = manager.find_issue_file(
                    issue.slug, include_completed=show_completed
                )
                if issue_file:
                    editor = get_editor()
                    subprocess.run([editor, str(issue_file)])
                    manager.init_project()
                    issues = get_display_issues(search_query, show_completed)
                    indexed_issues = build_hierarchy(issues)
                else:
                    console.print(f"[red]Issue file not found for {issue.slug}[/red]")
                    questionary.press_any_key_to_continue().ask()
                live.start()
            elif key == "a" and not show_completed:
                live.stop()
                title = questionary.text("Issue title:").ask()
                if title:
                    body = questionary.text("Issue body (optional):").ask() or ""
                    draft = questionary.confirm("Create as draft?").ask()
                    try:
                        issue = manager.create_issue(title, body, draft)
                        console.print(f"[bold green]Created: {issue.slug}[/bold green]")
                        manager.init_project()
                        issues = get_display_issues(search_query, show_completed)
                        indexed_issues = build_hierarchy(issues)
                    except Exception as e:
                        console.print(f"[red]Error: {e}[/red]")
                        questionary.press_any_key_to_continue().ask()
                live.start()
            elif key == "\x0b" and not show_completed:  # ctrl+k
                slug = indexed_issues[cursor][0].slug
                try:
                    manager.prioritize_issue(slug, "up")
                    issues = get_display_issues(search_query, show_completed)
                    indexed_issues = build_hierarchy(issues)
                    cursor = max(0, cursor - 1)
                except Exception:
                    pass
            elif key == "\x0a" and not show_completed:  # ctrl+j (often \n)
                slug = indexed_issues[cursor][0].slug
                try:
                    manager.prioritize_issue(slug, "down")
                    issues = get_display_issues(search_query, show_completed)
                    indexed_issues = build_hierarchy(issues)
                    cursor = min(len(indexed_issues) - 1, cursor + 1)
                except Exception:
                    pass
            elif key == "p" and not show_completed:  # promote
                issue = indexed_issues[cursor][0]
                if issue.status == "draft":
                    try:
                        manager.promote_issue(issue.slug)
                        issues = get_display_issues(search_query, show_completed)
                        indexed_issues = build_hierarchy(issues)
                    except Exception:
                        pass
            elif key == "d" and not show_completed:  # demote
                issue = indexed_issues[cursor][0]
                if issue.status in ("pending", "active"):
                    try:
                        manager.demote_issue(issue.slug)
                        issues = get_display_issues(search_query, show_completed)
                        indexed_issues = build_hierarchy(issues)
                    except Exception:
                        pass
            elif key == "r" and show_completed:  # restore
                target = indexed_issues[cursor][0]
                try:
                    manager.restore_issue(target.slug, to_status="pending")
                    issues = get_display_issues(search_query, show_completed)
                    indexed_issues = build_hierarchy(issues)
                    cursor = min(len(indexed_issues) - 1, cursor)
                except Exception:
                    pass
            elif key == "A" and not show_completed:  # active
                live.stop()
                issue = indexed_issues[cursor][0]
                try:
                    manager.move_to_active(issue.slug)
                    console.print(
                        f"[bold green]Issue '{issue.slug}' is now active.[/bold green]"
                    )
                    issues = get_display_issues(search_query, show_completed)
                    indexed_issues = build_hierarchy(issues)
                except Exception as e:
                    console.print(f"[red]Error: {e}[/red]")
                questionary.press_any_key_to_continue().ask()
                live.start()
            elif key == "D" and not show_completed:  # done
                live.stop()
                issue = indexed_issues[cursor][0]
                solution = questionary.text("Solution explanation (optional):").ask()
                try:
                    cmd_done(console, manager, issue.slug, solution=solution or None)
                    issues = get_display_issues(search_query, show_completed)
                    indexed_issues = build_hierarchy(issues)
                except Exception as e:
                    console.print(f"[red]Error: {e}[/red]")
                    questionary.press_any_key_to_continue().ask()
                live.start()
            elif key == "l" and not show_completed:  # make current depend on above
                if cursor > 0:
                    current_issue = indexed_issues[cursor][0]
                    current_depth = indexed_issues[cursor][1]
                    target_issue = None

                    if current_depth == 0:
                        # Link to the root of the above tree
                        root_idx = cursor - 1
                        while root_idx >= 0 and indexed_issues[root_idx][1] > 0:
                            root_idx -= 1
                        if root_idx >= 0:
                            target_issue = indexed_issues[root_idx][0]
                    else:
                        # Link to the sibling immediately above it at the same depth
                        sibling_idx = cursor - 1
                        while (
                            sibling_idx >= 0
                            and indexed_issues[sibling_idx][1] > current_depth
                        ):
                            sibling_idx -= 1
                        if (
                            sibling_idx >= 0
                            and indexed_issues[sibling_idx][1] == current_depth
                        ):
                            target_issue = indexed_issues[sibling_idx][0]

                    if target_issue:
                        live.stop()
                        try:
                            choice = questionary.select(
                                f"Link '{current_issue.slug}' to '{target_issue.slug}' as:",
                                choices=[
                                    f"Subtask of (Hierarchy: parent '{target_issue.slug}' is blocked until child '{current_issue.slug}' is done)",
                                    f"Blocked by (Ordering: child '{current_issue.slug}' cannot start/finish until parent '{target_issue.slug}' is done)",
                                    "Cancel",
                                ],
                            ).ask()
                        except (EOFError, Exception):
                            choice = "Blocked by"

                        if choice and not choice.startswith("Cancel"):
                            try:
                                if choice.startswith("Subtask of"):
                                    # If it was blocked_by, remove to avoid redundancy
                                    if target_issue.slug in current_issue.blocked_by:
                                        manager.remove_dependency(
                                            current_issue.slug,
                                            target_issue.slug,
                                        )
                                    manager.update_subtask_of(
                                        current_issue.slug, target_issue.slug
                                    )
                                else:
                                    # Blocked by
                                    # If it was subtask_of, remove to avoid conflicts
                                    if current_issue.subtask_of == target_issue.slug:
                                        manager.update_subtask_of(
                                            current_issue.slug, None
                                        )

                                    # Check transitive dependencies recursively to avoid redundancy
                                    all_issues = manager.load_mission()

                                    def is_ancestor(ancestor_slug, desc_slug):
                                        slug_to_issue = {i.slug: i for i in all_issues}
                                        if desc_slug not in slug_to_issue:
                                            return False
                                        todo = list(
                                            slug_to_issue[desc_slug].dependencies
                                        )
                                        visited = set(todo)
                                        while todo:
                                            curr = todo.pop()
                                            if curr == ancestor_slug:
                                                return True
                                            if curr in slug_to_issue:
                                                for dep in slug_to_issue[
                                                    curr
                                                ].dependencies:
                                                    if dep not in visited:
                                                        visited.add(dep)
                                                        todo.append(dep)
                                        return False

                                    manager.add_dependency(
                                        current_issue.slug, target_issue.slug
                                    )

                                    # Remove redundant direct dependencies that are transitively covered
                                    for dep in list(current_issue.dependencies):
                                        if dep != target_issue.slug and is_ancestor(
                                            dep, target_issue.slug
                                        ):
                                            manager.remove_dependency(
                                                current_issue.slug, dep
                                            )

                                issues = get_display_issues(
                                    search_query, show_completed
                                )
                                indexed_issues = build_hierarchy(issues)
                            except Exception as e:
                                console.print(f"[red]Error: {e}[/red]")
                                questionary.press_any_key_to_continue().ask()
                        live.start()
            elif key == "h" and not show_completed:  # remove dependency on above
                if cursor > 0:
                    current_issue = indexed_issues[cursor][0]
                    above_issue = indexed_issues[cursor - 1][0]
                    try:
                        updated = False
                        if current_issue.subtask_of == above_issue.slug:
                            manager.update_subtask_of(current_issue.slug, None)
                            updated = True
                        elif above_issue.slug in current_issue.blocked_by:
                            parents = list(above_issue.dependencies)
                            manager.remove_dependency(
                                current_issue.slug, above_issue.slug
                            )
                            # Move up: inherit the parent's dependencies
                            for parent in parents:
                                manager.add_dependency(current_issue.slug, parent)
                            updated = True

                        if updated:
                            issues = get_display_issues(search_query, show_completed)
                            indexed_issues = build_hierarchy(issues)
                    except Exception as e:
                        console.print(f"[red]Error: {e}[/red]")
                        questionary.press_any_key_to_continue().ask()


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
            box=theme.panel_box,
        )
    )

    # Plan
    plan_path = manager.plan_path
    if plan_path.exists():
        plan_content = plan_path.read_text().strip()
        if plan_content:
            console.print(Markdown(plan_content))

    # Task Summary

    stats_table = Table.grid(padding=theme.table_padding)
    console.print(stats_table)
    console.print()

    # Commands Table
    table = Table(
        title="Available Commands",
        box=None,
        show_header=False,
        padding=theme.table_padding,
    )
    table.add_column("Command", style="cyan", no_wrap=True)
    table.add_column("Description", style="white")

    commands = [
        ("next", "Show the highest priority task"),
        ("prior", "Interactively prioritize and promote tasks"),
        ("list", "List all tasks in the queue (try --json or --text)"),
        ("search", "Search for tasks by slug pattern"),
        ("new", "Create a new task"),
        ("start", "Start a task (creates branch & worktree)"),
        ("done", "Complete a task (moves file & commits)"),
        ("init", "Initialize or heal the Task Agent project"),
        ("plan", "View or edit the project plan"),
        ("push", "Push the mission repository to origin"),
        ("commit", "Commit pending changes in the active task directory"),
        (
            "eject-mission",
            "Deprecated: legacy in-repo eject (prefer ta store migrate)",
        ),
        (
            "store",
            "Machine data root / moniker / registry / migrate",
        ),
        ("", ""),  # Spacer
        ("active", "Mark a task as active without starting a worktree"),
        ("promote", "Promote a draft task to pending"),
        ("demote", "Demote a pending task back to draft"),
        ("up/down", "Adjust task priority"),
        ("ingest", "Scan disk for new markdown tasks"),
        ("triage", "(alias for prior)"),
        ("", ""),  # Spacer
        ("init-worker", "Scaffold an autonomous sidecar worker"),
        ("init-mcp", "Register Task Agent MCP (Claude Code, Gemini CLI, etc.)"),
        ("mcp", "Run the MCP server"),
        ("mcp-api", "Display the MCP API (tools and docstrings)"),
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
    subparsers.add_parser("init", help="Initialize or heal the project")
    triage_parser = subparsers.add_parser(
        "triage", help="Interactively prioritize and promote tasks"
    )
    triage_parser.add_argument(
        "search", nargs="?", help="Optional search query to filter by slug"
    )
    search_parser = subparsers.add_parser(
        "search", help="Search for tasks by slug pattern"
    )
    search_parser.add_argument(
        "pattern", help="Pattern to match against slug (wildcard end)"
    )
    prior_parser = subparsers.add_parser(
        "prior", help="Interactively prioritize and promote tasks"
    )
    prior_parser.add_argument(
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

    report_parser = subparsers.add_parser(
        "report", help="View metadata/logs for a task"
    )
    report_parser.add_argument("slug", help="Slug of the issue")

    subparsers.add_parser(
        "dashboard", help="Show a live dashboard of all task stations"
    )
    list_parser = subparsers.add_parser("list")
    subparsers.add_parser("tree", help="Display task hierarchy as a dependency tree")
    list_parser.add_argument("--json", action="store_true")
    list_parser.add_argument("--text", action="store_true")
    history_parser = subparsers.add_parser("history")
    history_parser.add_argument(
        "-n", "--limit", type=int, default=20, help="Number of items to show"
    )
    subparsers.add_parser(
        "recover-history",
        help="Recover deleted task files from git history and recover task creation dates into frontmatter",
    )
    subparsers.add_parser("ingest")
    subparsers.add_parser("mcp-api", help="List available MCP tools and API")
    subparsers.add_parser("self-up")
    worktree_parser = subparsers.add_parser(
        "worktree", help="Manage git worktrees with advanced features"
    )
    worktree_parser.add_argument(
        "action",
        nargs="?",
        choices=["add", "list", "remove", "prune"],
        help="Worktree action to perform (shows help if omitted)",
    )
    worktree_parser.add_argument(
        "target", nargs="?", help="Branch, tag, or commit SHA (for add action)"
    )
    worktree_parser.add_argument(
        "--tag", action="store_true", help="Create worktree from tag instead of branch"
    )
    worktree_parser.add_argument(
        "--commit", action="store_true", help="Create worktree from specific commit SHA"
    )
    worktree_parser.add_argument(
        "--copy",
        action="append",
        help="Glob patterns to copy to worktree (can be specified multiple times)",
    )
    worktree_parser.add_argument(
        "--permissions",
        help="Octal permissions for worktree directory (e.g., 700, 755)",
    )
    worktree_parser.add_argument(
        "--no-symlinks", action="store_true", help="Do not copy symlinks to worktree"
    )
    worktree_parser.add_argument(
        "--no-env", action="store_true", help="Do not copy .env files to worktree"
    )

    # GitHub integration
    github_parser = subparsers.add_parser("github", help="Sync with GitHub Issues")
    github_sub = github_parser.add_subparsers(dest="github_command")

    sync_parser = github_sub.add_parser("sync", help="Import issues from GitHub")
    sync_parser.add_argument("--repo", help="Repository (owner/repo) override")

    create_parser = github_sub.add_parser(
        "create", help="Create GitHub issue from task"
    )
    create_parser.add_argument("slug", help="Task slug to create GitHub issue for")

    # Add other commands as needed

    up_parser = subparsers.add_parser("up")
    up_parser.add_argument("slug")
    down_parser = subparsers.add_parser("down")
    down_parser.add_argument("slug")
    promote_parser = subparsers.add_parser("promote")
    promote_parser.add_argument("slug")
    demote_parser = subparsers.add_parser("demote")
    demote_parser.add_argument("slug")
    active_parser = subparsers.add_parser(
        "active",
        help="Move an issue to active status, or list active tasks if no slug is provided",
    )
    active_parser.add_argument(
        "slug", nargs="?", help="Optional slug of the task to mark as active"
    )
    update_parser = subparsers.add_parser(
        "update",
        help="Update task relationships (blocked_by / parent) for one or many tasks",
    )
    update_parser.add_argument(
        "slug",
        help=(
            "Slug of the task to update, or comma-separated slugs for bulk "
            "(e.g. task-a,task-b,task-c)"
        ),
    )
    update_parser.add_argument(
        "--blocked-by",
        help="Replace blocked_by with this comma-separated list (empty string clears / removes property)",
    )
    update_parser.add_argument(
        "--add-blocked-by",
        help="Append these comma-separated blocker slugs without replacing existing ones",
    )
    update_parser.add_argument(
        "--remove-blocked-by",
        help="Remove these comma-separated blocker slugs (removes property if last)",
    )
    update_parser.add_argument(
        "--subtask-of",
        help="Slug of the parent task this task is a subtask of (use empty string to clear)",
    )
    start_parser = subparsers.add_parser(
        "start",
        help="Activate a task and set up its git worktree/branch",
        description="""
Start working on a task. This command automates the following workflow:
  1. Marks the task (identified by its slug) as ACTIVE in the task manager.
     If no slug is provided, prompts you to select one from pending tasks.
  2. Creates a new git branch named 'issue/<slug>' (branched from main/current).
  3. Creates and checks out a new git worktree located at '.gwt/<slug>'.
  4. If --agent is specified:
     - If it matches a template in '.ta/agents/<agent_name>/meta.toml',
       creates a dedicated per-task agent user 'agent-<slug>-<agent_name>'.
     - Otherwise, configures worktree permissions for an existing agent user.
  5. If --run is specified, immediately runs the sidecar worker on the worktree.
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    start_parser.add_argument(
        "slug", nargs="?", help="Slug or partial slug of the task to start"
    )
    start_parser.add_argument(
        "--run", action="store_true", help="Immediately run the sidecar worker"
    )
    start_parser.add_argument(
        "--agent",
        help="Template name (creates per-task agent) or existing agent user name",
    )
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("slug", nargs="?")
    run_parser.add_argument(
        "--agent",
        help="Template name (creates per-task agent) or existing agent user name",
    )
    init_parser = subparsers.add_parser("init-worker")

    init_agent_parser = subparsers.add_parser(
        "init-agent", help="Create a dedicated Linux user for agent isolation"
    )
    init_agent_parser.add_argument(
        "name", nargs="?", help="Agent name (creates user agent-<name>)"
    )
    init_agent_parser.add_argument(
        "--template",
        help="Template name from .ta/agents/<name>/meta.toml",
    )
    init_agent_parser.add_argument(
        "--list-templates",
        action="store_true",
        help="List available agent templates",
    )
    init_agent_parser.add_argument(
        "--op-timeout",
        type=int,
        default=30,
        help="Timeout in seconds for 1Password CLI operations (default: 30)",
    )

    destroy_agent_parser = subparsers.add_parser(
        "destroy-agent",
        help="Remove an agent Linux user created by init-agent",
    )
    destroy_agent_parser.add_argument("name", help="Agent name to remove")
    init_parser.add_argument("--template", default="adk")

    # mcp
    subparsers.add_parser("mcp", help="Run the Model Context Protocol server")

    # init-mcp
    init_mcp_parser = subparsers.add_parser(
        "init-mcp",
        help="Register Task Agent as an MCP server (Claude Code, Gemini CLI, OpenCode)",
    )
    init_mcp_parser.add_argument(
        "--claude",
        action="store_true",
        help="Register with Claude Code (via 'claude mcp add')",
    )
    init_mcp_parser.add_argument(
        "--agent",
        choices=["gemini", "opencode"],
        default="gemini",
        help="MCP agent to configure (default: gemini)",
    )
    init_mcp_parser.add_argument(
        "--print", action="store_true", help="Print MCP configuration JSON"
    )
    init_mcp_parser.add_argument(
        "--scope",
        choices=["project", "user"],
        default="project",
        help="Registration scope (default: project)",
    )

    # plan
    subparsers.add_parser("plan", help="View or edit the project plan")

    # strategy
    strategy_parser = subparsers.add_parser(
        "strategy",
        help="View, edit, or initialize the project strategy",
        description="""
Manage the project's strategic direction document.

The strategy is a concise statement of the project's current direction, goals,
and priorities. It is displayed periodically at the top of 'list', 'next', and
'active' commands to keep all workers aligned.

Usage:
  ta strategy          View the current strategy
  ta strategy edit     Open the strategy in your $EDITOR
  ta strategy init     Create a starter strategy file
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    strategy_parser.add_argument(
        "action",
        nargs="?",
        choices=["edit", "init"],
        help="Action to perform (default: view)",
    )

    # push
    subparsers.add_parser("push", help="Push the mission repository to origin")

    # commit - commit changes to task-agent's own tasks or the host project's tasks
    commit_parser = subparsers.add_parser(
        "commit", help="Commit changes in the tasks directory"
    )
    commit_parser.add_argument(
        "target",
        choices=["repo", "tasks"],
        help="'repo' commits the current project's tasks, 'tasks' commits the task-agent's own tasks",
    )
    commit_parser.add_argument(
        "-m", "--message", help="Commit message (default: auto-generated)"
    )
    commit_parser.add_argument(
        "--no-push",
        dest="push",
        action="store_false",
        help="Do not push to remote",
    )
    commit_parser.set_defaults(push=True)

    # mr
    mr_parser = subparsers.add_parser("mr", help="Manage merge requests from workers")
    mr_sub = mr_parser.add_subparsers(dest="mr_command")
    mr_sub.add_parser("list", help="List pending merge requests")

    # merge
    merge_parser = subparsers.add_parser(
        "merge", help="Merge a task completion datagram"
    )
    merge_parser.add_argument("slug", help="Slug of the task to merge")
    merge_parser.add_argument("-m", "--message", help="Git commit message")
    merge_parser.add_argument(
        "--push", action="store_true", help="Push mission repo after merge"
    )

    # eject-mission (deprecated — prefer ta store migrate)
    eject_parser = subparsers.add_parser(
        "eject-mission",
        help="Deprecated: legacy eject into .task-agent/tasks (prefer ta store migrate)",
    )
    eject_parser.add_argument(
        "--public", action="store_true", help="Make the new mission repo public"
    )

    # store — machine data root / moniker / registry (Phase 1: no migration)
    store_parser = subparsers.add_parser(
        "store",
        help="Inspect machine-level task store layout (data root, moniker, registry)",
    )
    store_sub = store_parser.add_subparsers(dest="store_command")
    store_sub.add_parser(
        "data-root", help="Print the machine task-agent data root path"
    )
    moniker_p = store_sub.add_parser(
        "moniker", help="Print the moniker for a host path (default: cwd)"
    )
    moniker_p.add_argument(
        "path",
        nargs="?",
        default=None,
        help="Host project path (default: current directory)",
    )
    store_sub.add_parser("list", help="List registered machine task stores")
    inspect_p = store_sub.add_parser(
        "inspect",
        help="Read-only inspect: moniker, legacy store, migration status",
    )
    inspect_p.add_argument(
        "path",
        nargs="?",
        default=None,
        help="Host project path (default: current directory)",
    )
    inspect_p.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON"
    )
    store_sub.add_parser(
        "rebuild-index",
        help="Rebuild registry.json by scanning stores/ under the data root",
    )
    migrate_p = store_sub.add_parser(
        "migrate",
        help="Move legacy .task-agent/tasks into the machine data root store",
    )
    migrate_p.add_argument(
        "path",
        nargs="?",
        default=None,
        help="Host project path (default: current directory)",
    )
    migrate_p.add_argument(
        "--dry-run",
        action="store_true",
        help="Plan only; do not move data or rewrite pointers",
    )
    migrate_p.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON"
    )
    remote_parser = store_sub.add_parser(
        "remote",
        help="Show, suggest, or set the git remote for a task store",
    )
    remote_sub = remote_parser.add_subparsers(dest="remote_command")
    remote_show = remote_sub.add_parser(
        "show", help="List git remotes on the current project's task store"
    )
    remote_show.add_argument(
        "path",
        nargs="?",
        default=None,
        help="Host project path (default: cwd)",
    )
    remote_suggest = remote_sub.add_parser(
        "suggest",
        help="Suggest remotes via provider plugins (GitHub sibling/wiki)",
    )
    remote_suggest.add_argument(
        "path",
        nargs="?",
        default=None,
        help="Host project path (default: cwd)",
    )
    remote_set = remote_sub.add_parser(
        "set",
        help="Set the store's git remote URL (does not create the remote host repo)",
    )
    remote_set.add_argument("url", help="Git remote URL")
    remote_set.add_argument(
        "--name",
        default="origin",
        help="Remote name (default: origin)",
    )
    remote_set.add_argument(
        "path",
        nargs="?",
        default=None,
        help="Host project path (default: cwd)",
    )

    delete_parser = subparsers.add_parser(
        "delete", help="Soft-delete a task (archive without commit, restorable)"
    )
    delete_parser.add_argument("slug")
    done_parser = subparsers.add_parser("done")
    done_parser.add_argument("slug", nargs="?")
    done_parser.add_argument("-m", "--message")
    done_parser.add_argument("-s", "--solution", help="Solution explanation")
    done_parser.add_argument(
        "--push", action="store_true", help="Push the mission repo after completion"
    )
    done_parser.add_argument(
        "--no-verify",
        action="store_true",
        default=True,
        help="Skip running git pre-commit hooks (default)",
    )
    done_parser.add_argument(
        "--hooks",
        dest="no_verify",
        action="store_false",
        help="Force running git pre-commit hooks",
    )

    path_parser = subparsers.add_parser("path", help="Get the absolute path to a task")
    path_parser.add_argument("slug", help="Task slug")

    new_parser = subparsers.add_parser("new")
    new_parser.add_argument("title", nargs="?")
    new_parser.add_argument("-b", "--body", default="")
    new_parser.add_argument("-c", "--criteria", help="Completion criteria")
    new_parser.add_argument("-d", "--draft", action="store_true")
    new_parser.add_argument(
        "--file",
        action="store_true",
        help="Create as single file instead of folder (default: folder)",
    )
    new_parser.add_argument(
        "--dir", action="store_true", help="Create as folder (default)"
    )
    new_parser.add_argument(
        "-i", "--interactive", action="store_true", help="Open editor to fill in task"
    )
    new_parser.add_argument(
        "--blocked-by",
        help="Comma-separated slugs of prerequisite tasks that block this task, e.g. 'setup-ci,build-artifacts'.",
    )
    new_parser.add_argument(
        "--subtask-of",
        help="Slug of the parent task this task is a subtask of, e.g. 'cli-consolidation'.",
    )
    new_parser.add_argument(
        "--bulk",
        help="Path to a JSON file containing an array of task definitions, or '-' to read JSON from stdin.",
    )
    version_parser = subparsers.add_parser("version")
    v_sub = version_parser.add_subparsers(dest="version_command")
    p_v = v_sub.add_parser("promote")
    p_v.add_argument("part", choices=["major", "minor", "patch"])
    tag_parser = v_sub.add_parser("tag")
    tag_parser.add_argument(
        "--no-push",
        dest="push",
        action="store_false",
        help="Do not push the tag to origin",
    )
    tag_parser.set_defaults(push=True)

    args = parser.parse_args()
    console = Console()
    if args.version:
        display_version_info(console)
        return

    try:
        manager = discover(Path(args.config_dir) if args.config_dir else None)
    except (RuntimeError, ValueError, OSError) as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)

    if args.command == "path":
        issue_file = manager.find_issue_file(args.slug)
        if issue_file:
            print(issue_file.absolute())
        else:
            console.print(f"[red]Task '{args.slug}' not found.[/red]")
            sys.exit(1)
    elif args.command == "next":
        cmd_next(console, manager)
    elif args.command == "init":
        cmd_init(console, manager)
    elif args.command == "triage":
        cmd_triage(console, manager, search_query=args.search)
    elif args.command == "prior":
        cmd_triage(console, manager, search_query=args.search)
    elif args.command == "search":
        cmd_search(console, manager, args.pattern)
    elif args.command == "restore":
        cmd_restore(console, manager, args.slug, to_status=args.status)
    elif args.command == "report":
        cmd_report(console, manager, args.slug)
    elif args.command == "dashboard":
        cmd_dashboard(console, manager)
    elif args.command == "list":
        fmt = "table"
        if args.json:
            fmt = "json"
        elif args.text:
            fmt = "text"
        cmd_list(console, manager, fmt)
    elif args.command == "tree":
        cmd_tree(console, manager)
    elif args.command == "history":
        cmd_history(console, manager, args.limit)
    elif args.command == "recover-history":
        cmd_recover_history(console, manager)
    elif args.command == "ingest":
        cmd_ingest(console, manager)
    elif args.command == "mcp-api":
        cmd_mcp_api(console)
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
        cmd_active(console, manager, args.slug, list_if_none=True)
    elif args.command == "update":
        cmd_update(
            console,
            manager,
            args.slug,
            blocked_by=args.blocked_by,
            subtask_of=args.subtask_of,
            add_blocked_by=args.add_blocked_by,
            remove_blocked_by=args.remove_blocked_by,
        )
    elif args.command == "start":
        cmd_start(console, manager, args.slug, run=args.run, agent_name=args.agent)
    elif args.command == "run":
        cmd_run(console, manager, args.slug, agent_name=args.agent)
    elif args.command == "init-agent":
        if args.list_templates:
            cmd_list_templates(console)
        elif not args.name:
            init_agent_parser.error("the following arguments are required: name")
        else:
            cmd_init_agent(
                console, args.name, template=args.template, op_timeout=args.op_timeout
            )
    elif args.command == "destroy-agent":
        cmd_destroy_agent(console, args.name)
    elif args.command == "init-worker":
        cmd_init_worker(console, args.template)
    elif args.command == "mcp":
        cmd_mcp()
    elif args.command == "init-mcp":
        cmd_init_mcp(
            console,
            agent=args.agent,
            print_json=args.print,
            scope=args.scope,
            claude=args.claude,
        )
    elif args.command == "push":
        cmd_push(console, manager)
    elif args.command == "plan":
        cmd_plan(console, manager)
    elif args.command == "strategy":
        cmd_strategy(console, manager, action=args.action)
    elif args.command == "commit":
        if args.target == "repo":
            cmd_commit(console, manager, message=args.message, should_push=args.push)
        elif args.target == "tasks":
            cmd_commit_tasks(console, message=args.message, should_push=args.push)
    elif args.command == "mr":
        if args.mr_command == "list":
            cmd_mr_list(console, manager)
        else:
            console.print("[yellow]Unknown mr command. Use 'ta mr list'.[/yellow]")
    elif args.command == "merge":
        cmd_merge(console, manager, args.slug, message=args.message, push=args.push)
    elif args.command == "eject-mission":
        cmd_eject_mission(console, manager, public=args.public)
    elif args.command == "store":
        cmd_store(console, args)
    elif args.command == "done":
        cmd_done(
            console,
            manager,
            args.slug,
            args.message,
            True,
            args.push,
            args.solution,
            args.no_verify,
        )
    elif args.command == "delete":
        cmd_soft_delete(console, manager, args.slug)
    elif args.command == "new":
        cmd_new(
            console=console,
            manager=manager,
            title=args.title,
            body=args.body,
            draft=args.draft,
            as_dir=not args.file,
            completion_criteria=args.criteria,
            interactive=args.interactive,
            blocked_by=args.blocked_by,
            subtask_of=args.subtask_of,
            bulk=args.bulk,
        )
    elif args.command == "worktree":
        cmd_worktree(console, manager, args)
    elif args.command == "github":
        cmd_github(console, manager, args)
    elif args.command == "version":
        if args.version_command == "promote":
            cmd_version(console, promote=args.part, push=False)
        elif args.version_command == "tag":
            cmd_version(console, tag=True, push=args.push)
        else:
            cmd_version(console)
    else:
        display_overview(console, manager)


if __name__ == "__main__":
    main()
