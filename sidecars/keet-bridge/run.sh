#!/usr/bin/env bash
set -euo pipefail

REPO="${2:-$(pwd)}"
ROOM="${1:-}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Starting Task Agent Keet Bridge..."
echo "  Store Repo: ${REPO}"
echo ""

if [ -n "$ROOM" ]; then
  exec node "${SCRIPT_DIR}/bridge.js" --room="${ROOM}" --repo="${REPO}"
else
  exec node "${SCRIPT_DIR}/bridge.js" --repo="${REPO}"
fi
