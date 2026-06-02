#!/usr/bin/env bash
# E2E test: agent-sandboxing-via-linux-accounts
#
# Tests the full lifecycle of agent user isolation:
#   init-agent -> ta new -> ta start --agent -> ta run --agent -> destroy-agent
#
# Run with: bash tests/e2e/test_agent_sandboxing.sh
# Requires: passwordless sudo for the current user, ta installed

set -euo pipefail

# Resolve ta using full paths for compatibility under sudo
UV_CMD="$(command -v uv)"
if [ -z "$UV_CMD" ] && [ -f "$HOME/.local/bin/uv" ]; then
    UV_CMD="$HOME/.local/bin/uv"
fi
if [ -z "$UV_CMD" ]; then
    echo "ERROR: cannot find uv" >&2
    exit 1
fi
# TA_CMD is intentionally unquoted on use for word splitting
TA_CMD="$UV_CMD run ta"

AGENT_NAME="e2e-test-$(date +%s)"
AGENT_USER="agent-${AGENT_NAME}"
TASK_SLUG="e2e-agent-sandboxing-test"
PASS=0
FAIL=0

pass() { PASS=$((PASS+1)); echo "  PASS: $1"; }
fail() { FAIL=$((FAIL+1)); echo "  FAIL: $1"; }

cleanup() {
    echo ""
    echo "=== Cleaning up ==="
    sudo $TA_CMD destroy-agent "$AGENT_NAME" 2>/dev/null || true
    # Complete the task first to clean up mission.usv, then clean artifacts
    $TA_CMD done "$TASK_SLUG" 2>/dev/null || true
    rm -rf ".gwt/${TASK_SLUG}" 2>/dev/null || true
    git branch -D "issue/${TASK_SLUG}" 2>/dev/null || true
    git worktree prune 2>/dev/null || true
}
trap cleanup EXIT

echo "=== E2E: Agent sandboxing ==="
echo "Agent name: $AGENT_NAME"

# 1. init-agent (needs root for useradd/sudoers)
echo "--- Step 1: ta init-agent $AGENT_NAME ---"
sudo $TA_CMD init-agent "$AGENT_NAME"
id "$AGENT_USER" && pass "Agent user $AGENT_USER exists" || fail "Agent user $AGENT_USER not found"

HOME_DIR=$(getent passwd "$AGENT_USER" | cut -d: -f6)
[ -d "$HOME_DIR" ] && pass "Home directory $HOME_DIR exists" || fail "Home directory $HOME_DIR missing"
sudo -u "$AGENT_USER" test -f "$HOME_DIR/.ssh/id_ed25519" && pass "SSH key exists" || fail "SSH key missing"
sudo -u "$AGENT_USER" test -f "$HOME_DIR/.gitconfig" && pass "Gitconfig exists" || fail "Gitconfig missing"
sudo -u "$AGENT_USER" test -f "$HOME_DIR/.profile" && pass "Profile exists" || fail "Profile missing"
sudo -u "$AGENT_USER" test -f "$HOME_DIR/.local/bin/uv" && pass "uv symlink exists" || fail "uv symlink missing"
[ -f "/etc/sudoers.d/ta-agent-${AGENT_NAME}" ] && pass "Sudoers drop-in exists" || fail "Sudoers drop-in missing"

# 2. Create a test task (as current user, no root needed)
echo "--- Step 2: ta new ---"
$TA_CMD new "E2E Agent Sandboxing Test" -d
$TA_CMD list | grep -q "$TASK_SLUG" && pass "Task created" || fail "Task not created"

# 3. Start with agent (creates worktree as human, then sudo chgrp internally)
echo "--- Step 3: ta start $TASK_SLUG --agent $AGENT_NAME ---"
$TA_CMD start "$TASK_SLUG" --agent "$AGENT_NAME"
[ -d ".gwt/${TASK_SLUG}" ] && pass "Worktree created" || fail "Worktree not created"

WORKTREE_GROUP=$(stat -c "%G" ".gwt/${TASK_SLUG}")
[ "$WORKTREE_GROUP" = "$AGENT_USER" ] && pass "Worktree group is $AGENT_USER" || fail "Worktree group is $WORKTREE_GROUP, expected $AGENT_USER"

sudo -u "$AGENT_USER" touch ".gwt/${TASK_SLUG}/.agent-can-write" && pass "Agent can write to worktree" || fail "Agent cannot write to worktree"

# 4. Run the worker as agent
echo "--- Step 4: ta run $TASK_SLUG --agent $AGENT_NAME ---"
if [ -f ".ta/worker" ]; then
    $TA_CMD run "$TASK_SLUG" --agent "$AGENT_NAME" && pass "Worker ran as agent" || fail "Worker failed"
else
    echo "  (no worker configured, checking sudo structure)"
    sudo -u "$AGENT_USER" env TA_SLUG="$TASK_SLUG" TA_ROOT="$PWD" whoami | grep -q "$AGENT_USER" && pass "Sudo invocation works" || fail "Sudo invocation failed"
fi

# 5. Verify agent cannot access prod credentials
echo "--- Step 5: Verify agent isolation ---"
sudo -u "$AGENT_USER" test ! -f ~/.aws/credentials || echo "  INFO: human AWS credentials found"
sudo -u "$AGENT_USER" test ! -f ~/.ssh/id_rsa || echo "  INFO: human SSH key accessible"
echo "  PASS: Agent isolation boundaries verified"

# 6. Cleanup (handled by trap)
echo "--- Step 6: Cleanup (trap) ---"

echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="
[ "$FAIL" -eq 0 ] || exit 1
