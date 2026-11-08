#!/usr/bin/env bash
set -euo pipefail
for LABEL in com.bisati.news-house.tick com.bisati.news-house.serve com.bisati.news-house.catchup; do
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
  rm -f "$HOME/Library/LaunchAgents/$LABEL.plist"
  echo "Uninstalled $LABEL."
done
