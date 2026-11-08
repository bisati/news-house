#!/usr/bin/env bash
# Install the News House launchd agent. It runs the production clone
# ($HOME/mihir_ai/news-house-prod), never the development clone.
set -euo pipefail
LABEL=com.bisati.news-house.tick
SERVE_LABEL=com.bisati.news-house.serve
CATCHUP_LABEL=com.bisati.news-house.catchup
PROD="$HOME/mihir_ai/news-house-prod"
SRC="$(cd "$(dirname "$0")/.." && pwd)"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
SERVE_PLIST="$HOME/Library/LaunchAgents/$SERVE_LABEL.plist"
CATCHUP_PLIST="$HOME/Library/LaunchAgents/$CATCHUP_LABEL.plist"
LOGS="$HOME/Library/Logs/news-house"

# render_plist <template> <output> <repo path>: substitute @REPO@ and @HOME@,
# fail if any @TOKEN@ survives, then lint.
render_plist() {
  sed -e "s|@REPO@|$3|g" -e "s|@HOME@|$HOME|g" "$1" > "$2"
  if grep -q '@[A-Z]*@' "$2"; then echo "unrendered token in $2"; exit 1; fi
  plutil -lint "$2"
}

# Sourcing this file (for tests) only defines the function.
if [ "${BASH_SOURCE[0]}" != "$0" ]; then return 0; fi

if [ ! -d "$PROD/.git" ]; then
  mkdir -p "$(dirname "$PROD")"
  git clone --branch main https://github.com/bisati/news-house.git "$PROD"
fi
# publish commits use the GitHub no-reply identity Vercel accepts
git -C "$PROD" config user.name bisati
git -C "$PROD" config user.email 81610063+bisati@users.noreply.github.com
if [ ! -x "$PROD/.venv/bin/pip" ]; then
  (cd "$PROD" && python3 -m venv .venv && .venv/bin/pip install -e .)
fi
# profile.md is gitignored: seed it from the dev clone's copy, else the example
if [ ! -f "$PROD/profile.md" ]; then
  if [ -f "$SRC/profile.md" ]; then cp "$SRC/profile.md" "$PROD/profile.md"
  else cp "$PROD/profile.example.md" "$PROD/profile.md"; fi
fi
(cd "$PROD" && .venv/bin/newshouse init-db)   # idempotent create_all

mkdir -p "$LOGS" "$HOME/Library/LaunchAgents"
render_plist "$SRC/launchd/$LABEL.plist.template" "$PLIST" "$PROD"

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"

render_plist "$SRC/launchd/$SERVE_LABEL.plist.template" "$SERVE_PLIST" "$PROD"
launchctl bootout "gui/$(id -u)/$SERVE_LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$SERVE_PLIST"

# Catch-up after sleep. Seed the stamp so a fresh install doesn't count as "never ticked".
mkdir -p "$PROD/out"; [ -f "$PROD/out/.last-tick" ] || date +%s > "$PROD/out/.last-tick"
render_plist "$SRC/launchd/$CATCHUP_LABEL.plist.template" "$CATCHUP_PLIST" "$PROD"
launchctl bootout "gui/$(id -u)/$CATCHUP_LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$CATCHUP_PLIST"

echo "Installed $LABEL (every 2 hours, and now)."
echo "Check:  launchctl print gui/\$(id -u)/$LABEL | grep -E 'state|last exit'"
echo "Log:    $LOGS/tick.log"
echo "Output: $PROD/out/latest.html"
echo "Installed $SERVE_LABEL (page + feedback on port 8787)."
echo "Open:   http://$(scutil --get LocalHostName 2>/dev/null || hostname -s).local:8787/latest.html"
echo "Log:    $LOGS/serve.log"
echo "Installed $CATCHUP_LABEL (every 10 awake minutes: starts a tick missed during sleep)."
