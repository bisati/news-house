#!/usr/bin/env bash
# Runs every 10 minutes of awake time and starts a tick the 2-hour timer missed:
# launchd's interval clock does not advance while the Mac sleeps.
set -euo pipefail
LABEL=com.bisati.news-house.tick
STAMP="$(cd "$(dirname "$0")/.." && pwd)/out/.last-tick"   # written by tick.sh at start
BUILD_HOUR=06   # keep equal to newshouse.tick.BUILD_HOUR

# due <now> <last tick> <today's build hour>, all epoch seconds: true when a tick is
# owed, either 2 hours since the last one or none yet since the build hour.
due() {
  (( $1 - $2 >= 7200 )) && return 0
  (( $1 >= $3 && $2 < $3 )) && return 0
  return 1
}

# Sourcing this file (for tests) only defines the function.
if [ "${BASH_SOURCE[0]}" != "$0" ]; then return 0; fi

target="gui/$(id -u)/$LABEL"
if launchctl print "$target" 2>/dev/null | grep -q '^\s*state = running'; then exit 0; fi
now=$(date +%s)
last=$(cat "$STAMP" 2>/dev/null || echo 0)
morning=$(TZ=Asia/Kolkata date -j -f '%Y-%m-%d %H:%M:%S' \
  "$(TZ=Asia/Kolkata date +%Y-%m-%d) $BUILD_HOUR:00:00" +%s)
if due "$now" "$last" "$morning"; then
  echo "=== catch-up $(date +%Y-%m-%dT%H:%M:%S%z): last tick $(( (now - last) / 60 )) min ago ==="
  launchctl kickstart "$target"
fi
