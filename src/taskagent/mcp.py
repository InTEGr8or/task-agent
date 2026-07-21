import functools
import os
import subprocess
from datetime import datetime
from typing import Callable, Optional, TypeVar
from mcp.server.fastmcp import FastMCP

from taskagent.manager import TaskAgent
from taskagent.discovery import discover, get_task_agent_project_root

# Create an MCP server
mcp = FastMCP("TaskAgent")

_F = TypeVar("_F", bound=Callable)


def get_manager() -> TaskAgent:
    """Helper to initialize the manager based on current environment."""
    return discover()


def get_manager_for_repo(repo: Optional[str] = None) -> TaskAgent:
    """Return the current manager, or a fuzzy-matched registered store when ``repo`` is set."""
    if not repo:
        return get_manager()
    from taskagent.store_registry import (
        AmbiguousRepoMatchError,
        RepoNotFoundError,
        manager_for_repo_query,
    )

    try:
        manager, _resolved = manager_for_repo_query(repo)
        return manager
    except AmbiguousRepoMatchError as e:
        monikers = ", ".join(c.moniker for c in e.candidates)
        raise ValueError(f"Ambiguous repo {repo!r}: {monikers}") from e
    except RepoNotFoundError as e:
        raise ValueError(str(e)) from e


def _parse_name_list(names: str) -> list[str]:
    """Split a comma-separated name list, dropping empties."""
    return [n.strip() for n in names.split(",") if n.strip()]


def _resolve_slug(manager: TaskAgent, name: str) -> str:
    """Resolve title/slug query to a concrete task slug (supports retitled tasks)."""
    resolved = manager.resolve_issue_slug(name)
    if resolved:
        return resolved
    # Fall back to slugify so error messages stay familiar for missing tasks
    return manager.slugify(name)


def _normalize_relation_slugs(manager: TaskAgent, value: str) -> str:
    """Resolve each comma-separated token to a task slug (empty stays clear)."""
    parts = _parse_name_list(value)
    if not parts:
        return ""
    return ", ".join(_resolve_slug(manager, p) for p in parts)


def _format_bulk_results(results: list[dict], field: str, value: str) -> str:
    """Render bulk update results as a short agent-readable report."""
    ok = [r for r in results if r.get("ok")]
    failed = [r for r in results if not r.get("ok")]
    lines = [f"Bulk set {field}={value!r}: {len(ok)} succeeded, {len(failed)} failed."]
    for r in ok:
        lines.append(f"  OK: {r['slug']}")
    for r in failed:
        lines.append(f"  FAIL: {r['slug']} — {r.get('error')}")
    return "\n".join(lines)


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


def _maybe_attach_inbox_indicator(
    response: str,
    *,
    tool_name: str = "",
    manager: Optional[TaskAgent] = None,
) -> str:
    """Prepend an unread-inbox line to MCP tool output when the current store has mail.

    Non-mutating (same as the CLI banner). Skips tools that are themselves the
    full inbox list, to avoid double-noise; still shows after ack/send so the
    remaining count is visible.
    """
    if not isinstance(response, str):
        return response
    # list_inbox already enumerates unread messages
    if tool_name == "list_inbox":
        return response
    # Avoid recursive decoration noise if banner text is the whole answer
    if response.lstrip().startswith("📬 Inbox"):
        return response

    try:
        mgr = manager if manager is not None else get_manager()
        store = getattr(mgr, "issues_root", None)
        if not store:
            return response
        from taskagent.inbox import format_unread_banner, moniker_for_store

        moniker = moniker_for_store(store)
        banner = format_unread_banner(store, moniker=moniker)
        if not banner:
            return response
        return f"{banner}\n\n{response}"
    except Exception:
        return response


# Wrap every @mcp.tool() so string results get the inbox indicator automatically.
_orig_mcp_tool = mcp.tool


def _mcp_tool_with_inbox(*tool_args, **tool_kwargs):  # type: ignore[no-untyped-def]
    """Decorator factory: same as FastMCP.tool, plus inbox banner on str results."""
    register = _orig_mcp_tool(*tool_args, **tool_kwargs)

    def decorator(fn: _F) -> _F:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):  # type: ignore[no-untyped-def]
            result = fn(*args, **kwargs)
            if isinstance(result, str):
                return _maybe_attach_inbox_indicator(
                    result, tool_name=getattr(fn, "__name__", "")
                )
            return result

        return register(wrapper)  # type: ignore[return-value]

    return decorator


mcp.tool = _mcp_tool_with_inbox  # type: ignore[method-assign]


@mcp.tool()
def list_inbox(thread: str = "", repo: Optional[str] = None) -> str:
    """List unread inbox messages for the current (or target) store.

    Display only — never marks messages as read. Use ack_inbox to acknowledge.

    Args:
        thread: Optional task slug filter (only messages with this thread).
        repo: Optional moniker fragment for another store (default: current project).
    """
    from taskagent.inbox import list_unread, moniker_for_store

    try:
        manager = get_manager_for_repo(repo)
    except ValueError as e:
        return f"Error resolving repo: {e}"
    thr = thread.strip() or None
    msgs = list_unread(manager.issues_root, thread=thr)
    moniker = moniker_for_store(manager.issues_root) or str(manager.issues_root)
    if not msgs:
        scope = f" thread={thr}" if thr else ""
        return f"No unread inbox messages on {moniker}{scope}."
    lines = [f"Unread inbox on {moniker} ({len(msgs)}):"]
    for m in msgs:
        lines.append(f"  {m.summary_line()}")
    lines.append("Ack with ack_inbox(id=...) when processed.")
    return "\n".join(lines)


@mcp.tool()
def send_inbox_message(
    to_repo: str,
    body: str,
    kind: str = "info",
    thread: str = "",
    task: str = "",
    from_moniker: str = "",
) -> str:
    """Send an inbox message to another store's inbox/unread/ (shared filesystem).

    Not real-time across machines — only visible after the target store is on
    the same data root / synced. For alerts and pointers, not the task queue.

    Args:
        to_repo: Target moniker/host fragment (fuzzy, e.g. ``task-agent``).
        body: Message body (Markdown).
        kind: One of task-created, question, update, comment, ack-request, info.
        thread: Optional task slug this message is about.
        task: Task slug to link (required for kind=task-created). Embeds a local
            snapshot when the task exists in the sender store; still sets the
            ``task``/``thread`` pointer when it only exists on the target.
        from_moniker: Override sender moniker (default: current store).
    """
    from taskagent.inbox import (
        resolve_sender_moniker,
        send_to_repo,
        snapshot_from_issue,
    )
    from taskagent.store_registry import AmbiguousRepoMatchError, RepoNotFoundError

    manager = get_manager()
    snapshot = None
    thr = thread.strip() or None
    task_slug = task.strip() or None
    if task_slug:
        slug = _resolve_slug(manager, task_slug)
        issues = manager.load_mission()
        issue = next((i for i in issues if i.slug == slug), None)
        if issue is not None:
            snapshot = snapshot_from_issue(issue)
            task_slug = issue.slug
            if not thr:
                thr = issue.slug
        else:
            # Task may live only on the target store (cross-repo create).
            task_slug = slug
            if not thr:
                thr = slug
    sender = from_moniker.strip() or resolve_sender_moniker(
        store_path=manager.issues_root
    )
    try:
        msg, resolved = send_to_repo(
            to_repo,
            from_moniker=sender,
            body=body,
            kind=kind,
            thread=thr,
            task=task_slug,
            task_snapshot=snapshot,
        )
    except (
        RepoNotFoundError,
        AmbiguousRepoMatchError,
        ValueError,
        FileExistsError,
    ) as e:
        return f"Error sending inbox message: {e}"
    return (
        f"Sent inbox message {msg.id} → {resolved.moniker} "
        f"({resolved.store_path}/.task-agent/inbox/unread/{msg.id}.msg.md)"
    )


@mcp.tool()
def ack_inbox(
    message_id: str,
    repo: Optional[str] = None,
    start: bool = False,
) -> str:
    """Acknowledge an unread inbox message (move to read/YYYY/MM/DD/).

    Args:
        message_id: Message id or unique prefix.
        repo: Optional moniker fragment (default: current project store).
        start: If True, also mark the linked task (task/thread frontmatter)
            as active in that store — ack + start in one step.
    """
    from taskagent.inbox import ack_message

    try:
        manager = get_manager_for_repo(repo)
    except ValueError as e:
        return f"Error resolving repo: {e}"
    try:
        msg = ack_message(manager.issues_root, message_id)
    except (FileNotFoundError, FileExistsError) as e:
        return f"Error acking message: {e}"
    parts = [f"Acked {msg.id} → {msg.path}"]
    if start:
        slug = msg.linked_slug
        if not slug:
            parts.append(
                "start=true ignored: message has no task/thread slug "
                "(senders must pass task= or thread= for task-created)."
            )
        else:
            try:
                manager.move_to_active(slug)
                parts.append(f"Started task {slug} (status → active).")
            except Exception as e:
                parts.append(f"Could not start task {slug!r}: {e}")
    return " ".join(parts)


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
def list_tasks(repo: Optional[str] = None) -> str:
    """List all tasks in the current project's mission queue.

    Tasks may have parent relationships (sub-task of) or ordering constraints (blocked by).

    Args:
        repo: Optional moniker/host fragment for another registered store.
    """
    try:
        manager = get_manager_for_repo(repo)
    except ValueError as e:
        return f"Error resolving repo: {e}"
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
    blocked_by: Optional[str] = None,
    subtask_of: Optional[str] = None,
    repo: Optional[str] = None,
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
        blocked_by: Comma-separated list of existing task slugs that block this task.
            Example: "setup-infra, configure-db" means this task is blocked by
            both "setup-infra" and "configure-db" needing to be completed first.
        subtask_of: Slug of the parent task this task is a subtask of.
        repo: Optional moniker/host fragment for another registered store
            (zoxide-style fuzzy match). Omit to use the current project.

    Examples:
        # Create a task blocked by two others
        create_task(
            title="Deploy to staging",
            completion_criteria="Staging deployment passes smoke tests",
            blocked_by="setup-ci, build-artifacts"
        )

        # Create a standalone draft task
        create_task(
            title="Research options",
            completion_criteria="Document comparing at least 3 approaches",
            draft=True
        )

        # Create in another registered project's store
        create_task(
            title="Add stations inspector",
            completion_criteria="CLI ships with tests",
            repo="stations",
        )
    """
    try:
        manager = get_manager_for_repo(repo)
    except ValueError as e:
        return f"Error resolving repo: {e}"
    try:
        issue = manager.create_issue(
            title,
            body,
            draft,
            blocked_by=blocked_by,
            subtask_of=subtask_of,
            completion_criteria=completion_criteria,
        )
        where = f" in {manager.issues_root}" if repo else ""
        return f"Created task: {issue.slug} (Status: {issue.status}){where}"
    except Exception as e:
        return f"Error creating task: {e}"


@mcp.tool()
def promote_task(name: str) -> str:
    """Promote a task from 'draft' to 'pending' status.

    Args:
        name: The title or partial name of the task.
    """
    manager = get_manager()
    slug = _resolve_slug(manager, name)
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
    slug = _resolve_slug(manager, name)
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
    slug = _resolve_slug(manager, name)
    try:
        manager.move_to_active(slug)
        return f"Task '{slug}' is now active."
    except Exception as e:
        return f"Error marking task active: {e}"


@mcp.tool()
def complete_task(
    name: str,
    solution: str,
    message: Optional[str] = None,
    model: Optional[str] = None,
    model_version: Optional[str] = None,
    provider: Optional[str] = None,
    agent_harness: Optional[str] = None,
    input_tokens: Optional[int] = None,
    output_tokens: Optional[int] = None,
    tokens_accuracy: Optional[str] = None,
    duration_seconds: Optional[float] = None,
    cost_usd: Optional[float] = None,
    started_at: Optional[str] = None,
    ended_at: Optional[str] = None,
    metrics_notes: Optional[str] = None,
) -> str:
    """Mark a task as completed and commit the changes.

    Self-report agent cost context when available so the station can optimize
    spend later (model, harness, tokens, duration). Partial reports are fine.

    Args:
        name: The title or partial name of the task to complete.
        solution: Clear explanation of what was implemented or fixed.
        message: Optional git commit message.
        model: Primary model id used for most of the work (e.g. 'claude-opus-4', 'grok-4').
        model_version: Model version / snapshot when known.
        provider: Provider name (e.g. 'anthropic', 'openai', 'xai', 'google').
        agent_harness: Product/harness that drove the work
            (e.g. 'claude-code', 'codex', 'cursor', 'grok', 'antigravity', 'adk-worker').
        input_tokens: Prompt/context tokens consumed (up).
        output_tokens: Completion tokens produced (down).
        tokens_accuracy: 'measured', 'estimated', or 'unknown' (default unknown).
        duration_seconds: Wall-clock seconds spent on the task.
        cost_usd: Estimated or billed cost in USD when known.
        started_at: ISO-8601 start time (optional; derived from duration when omitted).
        ended_at: ISO-8601 end time (defaults to now when metrics are provided).
        metrics_notes: Free-form cost notes (retries, cache hits, tool-loop count, …).
    """
    from taskagent.models.metric import SubtaskMetric

    manager = get_manager()
    slug = _resolve_slug(manager, name)
    try:
        metrics = SubtaskMetric.from_completion_args(
            model=model,
            provider=provider,
            model_version=model_version,
            agent_harness=agent_harness,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            tokens_accuracy=tokens_accuracy,
            duration_seconds=duration_seconds,
            cost_usd=cost_usd,
            started_at=started_at,
            ended_at=ended_at,
            notes=metrics_notes,
        )
        issue, commit_hash = manager.complete_issue(
            slug,
            commit_message=message,
            solution_explanation=solution,
            metrics=metrics,
        )
        lines = [
            "### Task Completed Successfully",
            "",
            f"- **Slug**: `{slug}`",
            f"- **Title**: {issue.name}",
            "- **Status**: `completed`",
            f"- **Git Commit SHA**: `{commit_hash}`",
            "",
            "#### Solution Explanation",
            solution,
        ]
        if metrics is not None:
            lines.extend(["", metrics.to_markdown().rstrip()])
        return "\n".join(lines) + "\n"
    except Exception as e:
        return f"Error completing task: {e}"


@mcp.tool()
def search_task(name: str) -> str:
    """Search for a task by title or partial name, including in completed tasks.

    Matches current display title even when it differs from the slug (retitled tasks).

    Args:
        name: The title or partial name of the task to search for.
    """
    manager = get_manager()
    slug = _resolve_slug(manager, name)
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
    slug = _resolve_slug(manager, name)
    try:
        manager.restore_issue(slug, to_status=status)
        return f"Task '{slug}' restored to '{status}'."
    except Exception as e:
        return f"Error restoring task: {e}"


@mcp.tool()
def get_task_details(name: str) -> str:
    """Get the full description and content of a specific task.

    Returns the primary README body plus any secondary Markdown documents
    in the task directory (investigation notes, designs, diffs, etc.).

    Args:
        name: The title or partial name of the task.
    """
    manager = get_manager()
    slug = _resolve_slug(manager, name)
    try:
        return manager.format_task_details(slug, include_completed=True)
    except FileNotFoundError:
        return f"Task matching '{name}' ({slug}) not found."


@mcp.tool()
def list_task_documents(name: str) -> str:
    """List secondary Markdown documents attached to a task (not README.md).

    Args:
        name: The title or partial name of the task.
    """
    manager = get_manager()
    slug = _resolve_slug(manager, name)
    try:
        docs = manager.list_secondary_documents(slug, include_completed=True)
    except FileNotFoundError:
        return f"Task matching '{name}' ({slug}) not found."
    if not docs:
        return f"Task '{slug}' has no secondary documents."
    lines = [f"Secondary documents on '{slug}' ({len(docs)}):"]
    for d in docs:
        lines.append(f"  - {d.name}")
    return "\n".join(lines)


@mcp.tool()
def add_task_document(
    name: str,
    filename: str,
    content: str,
    overwrite: bool = False,
) -> str:
    """Add a secondary Markdown document to a task directory.

    Use this for investigation findings, design notes, diffs, or other
    artifacts that should live next to the primary README without replacing it.
    File-based tasks are migrated to a folder layout automatically.

    Args:
        name: The title or partial name of the task.
        filename: Basename for the document (e.g. ``findings.md``).
            ``.md`` is appended if missing. Cannot be README.md.
        content: Full Markdown content to write.
        overwrite: If True, replace an existing document with the same name.
    """
    manager = get_manager()
    slug = _resolve_slug(manager, name)
    try:
        path = manager.add_task_document(slug, filename, content, overwrite=overwrite)
        return f"Added document '{path.name}' to task '{slug}' at {path}."
    except FileNotFoundError:
        return f"Task matching '{name}' ({slug}) not found."
    except (ValueError, FileExistsError, RuntimeError) as e:
        return f"Error adding document: {e}"


@mcp.tool()
def update_task(name: str, content: str) -> str:
    """Update the Markdown content of a task.

    Args:
        name: The title or partial name of the task to update.
        content: The new complete Markdown content for the task.
    """
    manager = get_manager()
    slug = _resolve_slug(manager, name)
    try:
        manager.update_issue(slug, content)
        return f"Successfully updated task '{slug}'."
    except Exception as e:
        return f"Error updating task: {e}"


@mcp.tool()
def update_task_dependencies(name: str, blocked_by: str) -> str:
    """Update the blocked_by dependencies of a task (alias of set_task_blocked_by).

    Prefer set_task_blocked_by for new callers.

    Args:
        name: The title or partial name of the task to update.
        blocked_by: Comma-separated list of task slugs that block this task (use empty string to clear).
    """
    return set_task_blocked_by(name, blocked_by)


@mcp.tool()
def set_task_blocked_by(name: str, blocked_by: str = "") -> str:
    """Set or clear blocked_by on a single task without rewriting the body.

    Replaces the entire blocked_by list (not append). Use empty string / omit to clear.
    Clearing removes the blocked_by frontmatter property entirely.

    Args:
        name: Title or partial name of the task to update.
        blocked_by: Comma-separated task slugs/names that block this task.
            Empty string clears all blockers and removes the property.
    """
    manager = get_manager()
    slug = _resolve_slug(manager, name)
    normalized = _normalize_relation_slugs(manager, blocked_by)
    try:
        manager.update_dependencies(slug, normalized)
        if normalized:
            return f"Successfully set blocked_by for task '{slug}' to: {normalized}."
        return f"Successfully cleared blocked_by for task '{slug}'."
    except Exception as e:
        return f"Error setting blocked_by: {e}"


@mcp.tool()
def add_task_blocked_by(name: str, blocked_by: str) -> str:
    """Add one or more blockers to a task without replacing existing blocked_by entries.

    Args:
        name: Title or partial name of the task to update.
        blocked_by: Comma-separated task slugs/names to add as blockers.
    """
    manager = get_manager()
    slug = _resolve_slug(manager, name)
    normalized = _normalize_relation_slugs(manager, blocked_by)
    if not normalized:
        return "Error: no blocker slugs provided to add."
    try:
        issue = manager.add_dependency(slug, normalized)
        return (
            f"Successfully added blocked_by on task '{slug}'. "
            f"Now: {', '.join(issue.blocked_by) if issue.blocked_by else '(none)'}."
        )
    except Exception as e:
        return f"Error adding blocked_by: {e}"


@mcp.tool()
def remove_task_blocked_by(name: str, blocked_by: str) -> str:
    """Remove one or more blockers from a task.

    If the last blocker is removed, the blocked_by property is deleted entirely.

    Args:
        name: Title or partial name of the task to update.
        blocked_by: Comma-separated task slugs/names to remove from blockers.
    """
    manager = get_manager()
    slug = _resolve_slug(manager, name)
    normalized = _normalize_relation_slugs(manager, blocked_by)
    if not normalized:
        return "Error: no blocker slugs provided to remove."
    try:
        issue = manager.remove_dependency(slug, normalized)
        if issue.blocked_by:
            return (
                f"Successfully removed blocked_by from task '{slug}'. "
                f"Now: {', '.join(issue.blocked_by)}."
            )
        return (
            f"Successfully removed blocked_by from task '{slug}'. "
            "No blockers remain (property cleared)."
        )
    except Exception as e:
        return f"Error removing blocked_by: {e}"


@mcp.tool()
def set_task_parent(name: str, parent: str = "") -> str:
    """Set or clear the parent (subtask_of) of a single task without rewriting the body.

    Clearing removes the subtask_of frontmatter property entirely.

    Args:
        name: Title or partial name of the task to update.
        parent: Parent task slug or name. Empty string clears the parent.
    """
    manager = get_manager()
    slug = _resolve_slug(manager, name)
    parent_slug = _resolve_slug(manager, parent) if parent.strip() else None
    try:
        manager.update_subtask_of(slug, parent_slug)
        if parent_slug:
            return f"Successfully set parent of task '{slug}' to '{parent_slug}'."
        return f"Successfully cleared parent of task '{slug}'."
    except Exception as e:
        return f"Error setting parent: {e}"


@mcp.tool()
def bulk_set_task_blocked_by(names: str, blocked_by: str = "") -> str:
    """Set the same blocked_by list on many tasks without rewriting bodies.

    Replaces each task's blocked_by list (not append). Empty blocked_by clears
    and removes the property.

    Args:
        names: Comma-separated task titles or slugs to update.
        blocked_by: Comma-separated blocker slugs/names applied to every task.
            Empty string clears blockers on every named task.
    """
    manager = get_manager()
    slugs = [_resolve_slug(manager, n) for n in _parse_name_list(names)]
    if not slugs:
        return "Error: no task names provided."
    normalized = _normalize_relation_slugs(manager, blocked_by)
    results = manager.bulk_update_dependencies(slugs, normalized)
    return _format_bulk_results(results, "blocked_by", normalized)


@mcp.tool()
def bulk_set_task_parent(names: str, parent: str = "") -> str:
    """Set the same parent (subtask_of) on many tasks without rewriting bodies.

    Args:
        names: Comma-separated task titles or slugs to update.
        parent: Parent task slug or name applied to every task.
            Empty string clears the parent on every named task.
    """
    manager = get_manager()
    slugs = [_resolve_slug(manager, n) for n in _parse_name_list(names)]
    if not slugs:
        return "Error: no task names provided."
    parent_slug = _resolve_slug(manager, parent) if parent.strip() else None
    results = manager.bulk_update_subtask_of(slugs, parent_slug)
    return _format_bulk_results(results, "parent", parent_slug or "")


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
            remotes = subprocess.run(
                ["git", "-C", str(git_root), "remote"],
                capture_output=True,
                text=True,
                shell=(os.name == "nt"),
            )
            if not (remotes.stdout or "").strip():
                return (
                    f"Committed: {message} "
                    "(no remote on store; skipped push — ta store remote set <url>)"
                )
            manager.push_mission_repo()
        return f"Committed: {message}"
    except subprocess.CalledProcessError as e:
        return f"Error: {e.stderr}"
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
def commit_tasks(message: str = "", push: bool = False) -> str:
    """Commit changes to the task-agent project's task store.

    Always targets the task-agent project via discovery (centralized data-root
    store when migrated), regardless of the current working directory.

    Args:
        message: Optional commit message. Auto-generated if omitted.
        push: Whether to push after committing.
    """
    project_root = get_task_agent_project_root()
    try:
        manager = discover(project_root)
    except Exception as e:
        return f"Could not discover task-agent store: {e}"

    tasks_dir = manager.issues_root
    git_root = manager.mission_root
    if not tasks_dir or not tasks_dir.exists():
        return "Task-agent tasks directory not found."
    if not git_root:
        return "No git repository found for task-agent task store."

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
            remotes = subprocess.run(
                ["git", "-C", str(git_root), "remote"],
                capture_output=True,
                text=True,
                shell=(os.name == "nt"),
            )
            if not (remotes.stdout or "").strip():
                return (
                    f"Committed: {message} "
                    "(no remote on store; skipped push — ta store remote set <url>)"
                )
            manager.push_mission_repo()
        return f"Committed: {message}"
    except subprocess.CalledProcessError as e:
        return f"Error: {e.stderr}"


@mcp.tool()
def create_tasks(
    tasks: list[dict],
    repo: Optional[str] = None,
) -> str:
    """Create multiple new tasks in the mission queue at once.

    Args:
        tasks: A list of task definitions. Each definition is a dictionary that
            can contain the following keys:
            - 'title' (str, required): The title of the task.
            - 'completion_criteria' (str, required): Clear, measurable criteria for task completion.
            - 'body' (str, optional): Detailed description of the task.
            - 'draft' (bool, optional): If True, creates the task in 'draft' status. Default is False (pending).
            - 'blocked_by' (str, optional): Comma-separated list of existing task slugs that block this task.
            - 'subtask_of' (str, optional): Slug of the parent task this task is a subtask of.
            - 'as_dir' (bool, optional): Create as folder directory. Default is True.
            - 'repo' (str, optional): Per-task store moniker fragment; overrides the top-level ``repo``.
        repo: Optional default moniker/host fragment for all tasks (zoxide-style).

    Returns:
        A summary report of created task slugs and any errors.
    """
    created = []
    errors = []

    for idx, t in enumerate(tasks):
        title = t.get("title")
        criteria = t.get("completion_criteria")
        if not title:
            errors.append(f"Task at index {idx} is missing required 'title'.")
            continue
        if not criteria:
            errors.append(
                f"Task '{title}' (index {idx}) is missing required 'completion_criteria'."
            )
            continue

        body = t.get("body", "")
        draft = t.get("draft", False)
        blocked_by = t.get("blocked_by")
        subtask_of = t.get("subtask_of")
        as_dir = t.get("as_dir", True)
        task_repo = t.get("repo", repo)

        try:
            manager = get_manager_for_repo(task_repo)
        except ValueError as e:
            errors.append(f"Error resolving repo for '{title}': {e}")
            continue

        try:
            issue = manager.create_issue(
                title=title,
                body=body,
                draft=draft,
                as_dir=as_dir,
                completion_criteria=criteria,
                blocked_by=blocked_by,
                subtask_of=subtask_of,
            )
            suffix = f" @ {manager.issues_root}" if task_repo else ""
            created.append(f"{issue.slug} (Status: {issue.status}){suffix}")
        except Exception as e:
            errors.append(f"Error creating task '{title}': {e}")

    report = []
    if created:
        report.append(
            "Successfully created tasks:\n" + "\n".join(f"- {c}" for c in created)
        )
    if errors:
        report.append("Errors encountered:\n" + "\n".join(f"- {err}" for err in errors))

    return "\n\n".join(report)


def run_mcp_server():
    """Main entry point to run the MCP server."""
    mcp.run()


if __name__ == "__main__":
    run_mcp_server()
