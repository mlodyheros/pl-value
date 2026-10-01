#!/bin/bash
# Runs `python -m backend.refresh` every morning at 07:00 (macOS launchd).
#
# The job does nothing on days without a new gameweek or stale Transfermarkt
# pages, so running it daily is cheap. If the Mac is asleep at 07:00, launchd
# runs it on waking. Output goes to data/refresh.log.
#
# Remove it again with scripts/uninstall_refresh_schedule.sh.
#
# macOS does not let background jobs read Desktop, Documents or Downloads, so keep
# the project elsewhere (e.g. ~/projects). From those folders the job only logs
# "Operation not permitted". To move it, see "Keeping it current" in docs/data.md.
# Run the job at once with: launchctl kickstart -k gui/$(id -u)/com.plvalue.refresh
set -euo pipefail

PROJECT="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="com.plvalue.refresh"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
PYTHON="$PROJECT/.venv/bin/python"

if [ ! -x "$PYTHON" ]; then
  echo "No virtualenv at $PROJECT/.venv - create it first (see README)." >&2
  exit 1
fi

mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PYTHON</string><string>-m</string><string>backend.refresh</string>
  </array>
  <key>WorkingDirectory</key><string>$PROJECT</string>
  <key>EnvironmentVariables</key>
  <dict><key>MPLBACKEND</key><string>Agg</string></dict>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>7</integer><key>Minute</key><integer>0</integer></dict>
  <key>StandardOutPath</key><string>$PROJECT/data/refresh.log</string>
  <key>StandardErrorPath</key><string>$PROJECT/data/refresh.log</string>
</dict>
</plist>
PLIST

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "Installed $LABEL: daily at 07:00, log in $PROJECT/data/refresh.log"
