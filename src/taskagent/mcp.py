import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional
from mcp.server.fastmcp import FastMCP

from taskagent.manager import TaskAgent
from taskagent.discovery import discover, get_task_agent_project_root

# Create an MCP server
mcp = FastMCP("TaskAgent")


def get_manager() -> TaskAgent:
    """Helper to initialize the manager based on current environment."""
    return discover()


def _maybe_prepend_strategy(manager: TaskAgent, response: str) -> str:
    """If the strategy cooldown has elapsed, prepend the strategy to the response."""
    if hasattr(manager, "should_show_strategy") and manager.should_show_strategy():
        if hasattr(manager, "get_strategy"):
            strategy = manager.get_strategy()
            if strategy:
                # Strip the H1 header if present — we want to keep it clean and concise
                lines = strategy.split("\n")
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
                if (
                    body
                    and body
                    != "_Define the current strategic direction for this project._"
                ):
                    if hasattr(manager, "update_strategy_last_shown"):
                        manager.update_strategy_last_shown()
                    # Prepend without a blockquote: just standard Markdown headers/body
                    prefix = f"## 📐 {title}\n\n{body}\n\n"
                    return prefix + response
    return response


@mcp.tool()
def get_strategy() -> str:
    """Retrieve the current project strategy statement.

    This provides high-level principles, constraints, or goals that should guide development.
    """
    manager = get_manager()
    if not hasattr(manager, "get_strategy"):
        return "No strategy defined yet."
    strategy = manager.get_strategy()
    if not strategy:
        return "No strategy defined yet."

    # Strip HTML comments for the tool output to keep it clean
    lines = strategy.split("\n")
    body_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("<!--") and stripped.endswith("-->"):
            continue
        body_lines.append(line)
    return "\n".join(body_lines).strip()


@mcp.tool()
def list_tasks() -> str:
    """List all tasks in the current project's mission queue.

    Tasks may have parent relationships (sub-task of) or ordering constraints (blocked by).
    """
    manager = get_manager()
    issues = manager.sync_mission()
    if not issues:
        res = "No tasks found in the queue."
    else:
        lines = []
        for i in issues:
            deps_list = []
            if i.subtask_of:
                deps_list.append(f"subtask of: {i.subtask_of}")
            if i.blocked_by:
                deps_list.append(f"blocked by: {', '.join(i.blocked_by)}")
            deps = f" ({'; '.join(deps_list)})" if deps_list else ""
            lines.append(f"[{i.priority}] {i.status.upper()}: {i.name}{deps}")
        res = "\n".join(lines)
    return _maybe_prepend_strategy(manager, res)


@mcp.tool()
def list_active_tasks() -> str:
    """List only the currently active tasks in the mission queue."""
    manager = get_manager()
    issues = manager.sync_mission()
    active_issues = [i for i in issues if i.status == "active"]
    if not active_issues:
        res = "No active tasks found."
    else:
        lines = []
        for i in active_issues:
            deps_list = []
            if i.subtask_of:
                deps_list.append(f"subtask of: {i.subtask_of}")
            if i.blocked_by:
                deps_list.append(f"blocked by: {', '.join(i.blocked_by)}")
            deps = f" ({'; '.join(deps_list)})" if deps_list else ""
            lines.append(f"[{i.priority}] ACTIVE: {i.name}{deps}")
        res = "\n".join(lines)
    return _maybe_prepend_strategy(manager, res)


@mcp.tool()
def create_task(
    title: str,
    completion_criteria: str,
    body: str = "",
    draft: bool = False,
    depends_on: Optional[str] = None,
) -> str:
    """Create a new task in the mission queue.

    Dependencies define the task hierarchy: if task B depends on task A,
    then A is a parent of B. This controls status promotion cascading —
    promoting a task also promotes all tasks that depend on it.

    Args:
        title: The title of the task.
        completion_criteria: Clear, measurable criteria for task completion.
        body: Detailed description of the task.
        draft: If True, creates the task in 'draft' status. Default is False (pending).
        depends_on: Comma-separated list of existing task slugs this task depends on.
            Example: "setup-infra, configure-db" means this task depends on
            both "setup-infra" and "configure-db" being completed first.

    Examples:
        # Create a task that depends on two others
        create_task(
            title="Deploy to staging",
            completion_criteria="Staging deployment passes smoke tests",
            depends_on="setup-ci, build-artifacts"
        )

        # Create a standalone draft task
        create_task(
            title="Research options",
            completion_criteria="Document comparing at least 3 approaches",
            draft=True
        )
    """
    manager = get_manager()
    try:
        issue = manager.create_issue(
            title, body, draft, depends_on, completion_criteria=completion_criteria
        )
        return f"Created task: {issue.slug} (Status: {issue.status})"
    except Exception as e:
        return f"Error creating task: {e}"


@mcp.tool()
def promote_task(name: str) -> str:
    """Promote a task from 'draft' to 'pending' status.

    Args:
        name: The title or partial name of the task.
    """
    manager = get_manager()
    slug = manager.slugify(name)
    try:
        manager.promote_issue(slug)
        return f"Task '{slug}' promoted to pending."
    except Exception as e:
        return f"Error promoting task: {e}"


@mcp.tool()
def demote_task(name: str) -> str:
    """Demote a task from 'pending' back to 'draft' status.

    Args:
        name: The title or partial name of the task.
    """
    manager = get_manager()
    slug = manager.slugify(name)
    try:
        manager.demote_issue(slug)
        return f"Task '{slug}' demoted to draft."
    except Exception as e:
        return f"Error demoting task: {e}"


@mcp.tool()
def mark_task_active(name: str) -> str:
    """Move a task to 'active' status, indicating work has started.

    Args:
        name: The title or partial name of the task.
    """
    manager = get_manager()
    slug = manager.slugify(name)
    try:
        manager.move_to_active(slug)
        return f"Task '{slug}' is now active."
    except Exception as e:
        return f"Error marking task active: {e}"


@mcp.tool()
def complete_task(name: str, solution: str, message: Optional[str] = None) -> str:
    """Mark a task as completed and commit the changes.

    Args:
        name: The title or partial name of the task to complete.
        solution: Clear explanation of what was implemented or fixed.
        message: Optional git commit message.
    """
    manager = get_manager()
    slug = manager.slugify(name)
    try:
        issue, commit_hash = manager.complete_issue(
            slug, commit_message=message, solution_explanation=solution
        )
        return (
            f"### Task Completed Successfully\n\n"
            f"- **Slug**: `{slug}`\n"
            f"- **Title**: {issue.name}\n"
            f"- **Status**: `completed`\n"
            f"- **Git Commit SHA**: `{commit_hash}`\n\n"
            f"#### Solution Explanation\n"
            f"{solution}\n"
        )
    except Exception as e:
        return f"Error completing task: {e}"


@mcp.tool()
def search_task(name: str) -> str:
    """Search for a task by title or partial name, including in completed tasks.

    Args:
        name: The title or partial name of the task to search for.
    """
    manager = get_manager()
    slug = manager.slugify(name)
    issue_file = manager.find_issue_file(slug, include_completed=True)
    if not issue_file:
        return f"Task matching '{name}' ({slug}) not found anywhere."

    # Determine status based on path
    status = "unknown"
    for s in ["pending", "draft", "active", "completed"]:
        if f"/{s}/" in str(issue_file.absolute()):
            status = s
            break

    return f"Task '{slug}' found in [bold]{status}[/bold]. Location: {issue_file}"


@mcp.tool()
def restore_task(name: str, status: str = "pending") -> str:
    """Restore a completed task back to pending, draft, or active status.

    Args:
        name: The title or partial name of the task to restore.
        status: The target status ('pending', 'draft', or 'active'). Defaults to 'pending'.
    """
    manager = get_manager()
    slug = manager.slugify(name)
    try:
        manager.restore_issue(slug, to_status=status)
        return f"Task '{slug}' restored to '{status}'."
    except Exception as e:
        return f"Error restoring task: {e}"


@mcp.tool()
def get_task_details(name: str) -> str:
    """Get the full description and content of a specific task.

    Args:
        name: The title or partial name of the task.
    """
    manager = get_manager()
    slug = manager.slugify(name)
    issue_file = manager.find_issue_file(slug)
    if not issue_file:
        return f"Task matching '{name}' ({slug}) not found."

    return issue_file.read_text(encoding="utf-8")


@mcp.tool()
def update_task(name: str, content: str) -> str:
    """Update the Markdown content of a task.

    Args:
        name: The title or partial name of the task to update.
        content: The new complete Markdown content for the task.
    """
    manager = get_manager()
    slug = manager.slugify(name)
    try:
        manager.update_issue(slug, content)
        return f"Successfully updated task '{slug}'."
    except Exception as e:
        return f"Error updating task: {e}"


@mcp.tool()
def update_task_dependencies(name: str, depends_on: str) -> str:
    """Update the dependencies of a task.

    Args:
        name: The title or partial name of the task to update.
        depends_on: Comma-separated list of task slugs this task depends on (use empty string to clear).
    """
    manager = get_manager()
    slug = manager.slugify(name)
    try:
        manager.update_dependencies(slug, depends_on)
        return f"Successfully updated dependencies for task '{slug}'."
    except Exception as e:
        return f"Error updating task dependencies: {e}"


@mcp.tool()
def commit_repo(message: str = "", push: bool = False) -> str:
    """Commit changes to the current project's tasks directory (host repo).

    Args:
        message: Optional commit message. Auto-generated if omitted.
        push: Whether to push after committing.
    """
    manager = get_manager()
    tasks_dir = manager.issues_root
    if not tasks_dir or not tasks_dir.exists():
        return "Tasks directory not found."

    git_root = manager.mission_root
    if not git_root:
        return "No git repository found for tasks directory."

    if not message:
        message = f"Update tasks - {datetime.now().strftime('%Y-%m-%d %H:%M')}"

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
            return "No changes to commit."

        subprocess.run(
            ["git", "-C", str(git_root), "commit", "--no-verify", "-m", message],
            check=True,
            capture_output=True,
            text=True,
            shell=(os.name == "nt"),
        )
        if push:
            manager.push_mission_repo()
        return f"Committed: {message}"
    except subprocess.CalledProcessError as e:
        return f"Error: {e.stderr}"
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
def commit_tasks(message: str = "", push: bool = False) -> str:
    """Commit changes to the task-agent's own tasks directory.

    Always targets the task-agent project's ``docs/tasks/`` regardless of
    the current working directory.

    Args:
        message: Optional commit message. Auto-generated if omitted.
        push: Whether to push after committing.
    """
    project_root = get_task_agent_project_root()
    tasks_dir = project_root / "docs" / "tasks"

    if not tasks_dir.exists():
        return "Task-agent tasks directory not found."

    git_result = subprocess.run(
        ["git", "-C", str(project_root), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        shell=(os.name == "nt"),
    )
    if git_result.returncode != 0:
        return "No git repository found for task-agent project."
    git_root = Path(git_result.stdout.strip())

    if not message:
        message = f"Update tasks - {datetime.now().strftime('%Y-%m-%d %H:%M')}"

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
            return "No changes to commit."

        subprocess.run(
            ["git", "-C", str(git_root), "commit", "--no-verify", "-m", message],
            check=True,
            capture_output=True,
            text=True,
            shell=(os.name == "nt"),
        )
        if push:
            subprocess.run(
                ["git", "-C", str(git_root), "push"],
                check=True,
                capture_output=True,
                text=True,
                shell=(os.name == "nt"),
            )
        return f"Committed: {message}"
    except subprocess.CalledProcessError as e:
        return f"Error: {e.stderr}"
    except Exception as e:
        return f"Error: {e}"


def run_mcp_server():
    """Main entry point to run the MCP server."""
    mcp.run()


if __name__ == "__main__":
    run_mcp_server()
