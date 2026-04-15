#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="$HOME/.local/share/claude-bar"
LAUNCHAGENT_PLIST="$HOME/Library/LaunchAgents/com.user.claude-bar.plist"
LAUNCHAGENT_LABEL="com.user.claude-bar"

echo "Removing claude-bar from this Mac..."

if [[ -f "$LAUNCHAGENT_PLIST" ]]; then
    launchctl unload "$LAUNCHAGENT_PLIST" 2>/dev/null || true
fi

launchctl remove "$LAUNCHAGENT_LABEL" 2>/dev/null || true
pkill -f "$INSTALL_DIR/run.sh" 2>/dev/null || true
pkill -f "claude_bar.py" 2>/dev/null || true

rm -rf "$INSTALL_DIR" "$LAUNCHAGENT_PLIST"

echo "Done."
