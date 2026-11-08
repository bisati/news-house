#!/usr/bin/env bash
# One scheduled tick, run inside the production clone. What runs is always the
# latest commit of the chosen branch (default main) on GitHub.
set -euo pipefail
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
cd "$(dirname "$0")/.."
mkdir -p out
date +%s > out/.last-tick   # catchup.sh reads this
BRANCH="${NEWSHOUSE_BRANCH:-main}"
git fetch -q origin
git checkout -q "$BRANCH"
git pull -q --ff-only origin "$BRANCH"
echo "=== tick $(date +%Y-%m-%dT%H:%M:%S%z) on $BRANCH@$(git rev-parse --short HEAD) ==="
. .venv/bin/activate
pip install -q -e . >/dev/null
# caffeinate -i: no idle sleep while the tick runs (a build takes up to an hour)
exec /usr/bin/caffeinate -i newshouse tick --out out
