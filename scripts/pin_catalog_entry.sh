#!/usr/bin/env bash
# Re-pin catalog-entry/worktree-sandbox.yaml's `sha` to the current commit.
#
# Run this AFTER the last commit that changes the plugin, and before opening the catalog PR
# (the pinned sha must exist in the public repository).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENTRY="$REPO_ROOT/catalog-entry/worktree-sandbox.yaml"

if [ ! -f "$ENTRY" ]; then
  echo "missing $ENTRY" >&2
  exit 1
fi

if [ -n "$(git -C "$REPO_ROOT" status --porcelain)" ]; then
  echo "refusing to pin: the working tree has uncommitted changes (commit them first)" >&2
  git -C "$REPO_ROOT" status --short >&2
  exit 1
fi

SHA="$(git -C "$REPO_ROOT" rev-parse HEAD)"
if ! printf '%s' "$SHA" | grep -Eq '^[0-9a-f]{40}$'; then
  echo "unexpected commit id: $SHA" >&2
  exit 1
fi

python3 - "$ENTRY" "$SHA" <<'PY'
import re, sys
path, sha = sys.argv[1], sys.argv[2]
text = open(path, encoding="utf-8").read()
new, n = re.subn(r"(?m)^sha:.*$", f"sha: {sha}", text, count=1)
if n != 1:
    sys.exit("no `sha:` line found in the catalog entry")
open(path, "w", encoding="utf-8").write(new)
print(f"pinned {path} -> {sha}")
PY

echo
echo "Reminder: the commit above must exist in the public repo before the catalog PR."
echo "Commit this entry change last; if you commit again, re-run this script."
