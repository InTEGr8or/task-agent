#!/usr/bin/env bash
# Statusline helper for task-agent Claude Code plugin
# Prints a compact one-liner active task status suitable for Claude status line.

set -euo pipefail

if command -v ta >/dev/null 2>&1; then
    ta prompt --pending 2>/dev/null || true
elif command -v uv >/dev/null 2>&1; then
    uv run ta prompt --pending 2>/dev/null || true
fi
