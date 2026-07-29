#!/usr/bin/env bash
# SessionStart hook for task-agent Antigravity CLI plugin
# Injects current active task and queue summary into session context.

set -euo pipefail

TA_CMD=""
if command -v ta >/dev/null 2>&1; then
    TA_CMD="ta"
elif command -v uv >/dev/null 2>&1; then
    TA_CMD="uv run ta"
fi

if [ -z "$TA_CMD" ]; then
    exit 0
fi

echo "--- Task Agent Context ---"

PROMPT_STATUS=$($TA_CMD prompt --pending 2>/dev/null || true)
if [ -n "$PROMPT_STATUS" ]; then
    echo "Queue status: $PROMPT_STATUS"
else
    echo "Queue status: no active task"
fi

ACTIVE_SLUG=$($TA_CMD prompt --format text 2>/dev/null || true)
if [ -n "$ACTIVE_SLUG" ]; then
    echo "Active task slug: $ACTIVE_SLUG"
fi

echo "Instructions: Prefer task-agent MCP tools (list_tasks, mark_task_active, complete_task) over ephemeral agent todos."
echo "--------------------------"
