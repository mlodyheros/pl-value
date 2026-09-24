#!/bin/bash
# Removes the daily refresh job installed by install_refresh_schedule.sh.
set -euo pipefail

LABEL="com.plvalue.refresh"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
rm -f "$PLIST"
echo "Removed $LABEL"
