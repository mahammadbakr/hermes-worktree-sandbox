#!/usr/bin/env bash
# Re-pin the catalog entry to the current commit, push it, and update the open catalog PR.
#
#   bash scripts/update_catalog_pr.sh
#
# Use after any push to the plugin repo (a SHA bump). The pinned commit must contain the same
# `plugin/` tree as the pushed HEAD; tests/test_submission.py enforces that locally.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FORK="${FORK:-mahammadbakr/hermes-agent}"
UPSTREAM="${UPSTREAM:-NousResearch/hermes-agent}"
BRANCH="${BRANCH:-catalog-worktree-sandbox}"
ENTRY_REL="plugin-catalog/worktree-sandbox.yaml"
LOCAL_ENTRY="$REPO_ROOT/catalog-entry/worktree-sandbox.yaml"

cd "$REPO_ROOT"

if [ -n "$(git status --porcelain)" ]; then
  echo "working tree is dirty; commit first" >&2
  exit 1
fi

echo "== 1/4  pin the entry to the pushed HEAD =="
PINNED=$(git rev-parse HEAD)
python3 - "$LOCAL_ENTRY" "$PINNED" <<'PY'
import re, sys
path, sha = sys.argv[1], sys.argv[2]
text = open(path, encoding="utf-8").read()
new, n = re.subn(r"(?m)^sha:.*$", f"sha: {sha}", text, count=1)
if n != 1:
    sys.exit("no `sha:` line in the catalog entry")
open(path, "w", encoding="utf-8").write(new)
print(f"  {path} -> {sha}")
PY

echo "== 2/4  commit and push =="
git add "$LOCAL_ENTRY"
git commit -q -m "chore(submission): re-pin catalog entry to $PINNED"
git push -q origin main
echo "  pushed"

echo "== 3/4  refresh the catalog PR branch with the same file =="
CURRENT_SHA=$(gh api "repos/$FORK/contents/$ENTRY_REL?ref=$BRANCH" --jq '.sha' 2>/dev/null || echo "")
python3 - "$LOCAL_ENTRY" "$CURRENT_SHA" > /tmp/entry_update.json <<'PY'
import base64, json, pathlib, sys
content = pathlib.Path(sys.argv[1]).read_bytes()
body = {
    "message": "catalog: re-pin worktree-sandbox to the current commit",
    "content": base64.b64encode(content).decode("ascii"),
    "branch": "catalog-worktree-sandbox",
}
if sys.argv[2]:
    body["sha"] = sys.argv[2]
json.dump(body, open("/dev/stdout", "w"))
PY
gh api -X PUT "repos/$FORK/contents/$ENTRY_REL" --input /tmp/entry_update.json --jq '"  new commit: \(.commit.sha)"'

echo "== 4/4  verify the PR still contains exactly one file =="
gh api "repos/$FORK/compare/main...$BRANCH" --jq '.files[] | "  \(.status) \(.filename)"'
PR=$(gh pr view "$UPSTREAM" --head "${FORK%%/*}:$BRANCH" --json url,state --jq '.url + "  (" + .state + ")"' 2>/dev/null || echo "(PR not found yet)")
echo "  $PR"
