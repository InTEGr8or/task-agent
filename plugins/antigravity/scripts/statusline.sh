#!/usr/bin/env bash
# Status line helper script for task-agent Antigravity CLI plugin

set -euo pipefail

TA_CMD=""
if command -v ta >/dev/null 2>&1; then
    TA_CMD="ta"
elif command -v uv >/dev/null 2>&1; then
    TA_CMD="uv run ta"
fi

if [ -n "$TA_CMD" ]; then
    $TA_CMD prompt --pending 2>/dev/null || echo "ta: idle"
else
    echo "ta: offline"
fi
