#!/usr/bin/env bash
# Seed (or reset) the recording workspace for the demo video.
#
#   scripts/demo_seed.sh            # seed a fresh demo project + keep the two candidate worktrees
#   scripts/demo_seed.sh --reset    # delete every seeded demo project first
#
# Prints DEMO_PROJECT=<path>: open that folder in Hermes before you hit record.
# Needs a Hermes Agent checkout only because the plugin modules import Hermes at call time;
# set HERMES_AGENT_REPO, or PYTHON to a Hermes-activated interpreter.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-python3}"
RESET=0
[ "${1:-}" = "--reset" ] && RESET=1

if [ -n "${HERMES_AGENT_REPO:-}" ]; then
  export PYTHONPATH="$HERMES_AGENT_REPO:${PYTHONPATH:-}"
fi

"$PYTHON" - "$REPO_ROOT" "$RESET" <<'PY'
import sys, importlib.util
from pathlib import Path

repo_root, reset = Path(sys.argv[1]), sys.argv[2] == "1"

spec = importlib.util.spec_from_file_location(
    "worktree_sandbox", repo_root / "plugin" / "__init__.py",
    submodule_search_locations=[str(repo_root / "plugin")])
pkg = importlib.util.module_from_spec(spec)
sys.modules["worktree_sandbox"] = pkg
spec.loader.exec_module(pkg)

from worktree_sandbox.manager import WorktreeManager
from worktree_sandbox.race import purge_demo_projects, run_demo_race

manager = WorktreeManager()
if reset:
    removed = purge_demo_projects(manager)
    print(f"removed {removed} seeded demo project(s)")

result = run_demo_race(manager, keep_worktrees=True)
print()
print(f"DEMO_PROJECT={result['project']}")
print(f"DEMO_RACE={result['race_id']}  WINNER={result['winner']}")
for row in result["results"]:
    verdict = "PASS" if row["passed"] else ("TIMEOUT" if row["timed_out"] else "FAIL")
    print(f"  {row['label']:<12} {verdict:<8} {row['duration_ms']:>5} ms  {row['worktree_id']}")
print()
print("next: open DEMO_PROJECT in Hermes Desktop and start recording (see DEMO.md)")
PY
