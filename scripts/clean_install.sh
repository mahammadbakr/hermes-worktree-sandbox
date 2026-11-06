#!/usr/bin/env bash
# Clean-install test: reproduce what the README tells a user to do, on a throwaway HERMES_HOME,
# and time it to first success. Exits non-zero if anything fails or if it takes over 120 seconds.
#
#   HERMES_AGENT_REPO=/path/to/hermes-agent bash scripts/clean_install.sh
#
# The only step it cannot perform is the real clone, because the public repository may not exist
# yet; it copies the working tree exactly as `hermes plugins install owner/repo#plugin` would lay
# it out (the plugin directory becomes $HERMES_HOME/plugins/worktree-sandbox).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HERMES_AGENT_REPO="${HERMES_AGENT_REPO:?set HERMES_AGENT_REPO to a Hermes Agent checkout}"
PYTHON="${PYTHON:-python3}"
BUDGET_SECONDS=120

WORK="$(mktemp -d "${TMPDIR:-/tmp}/worktree-install-XXXXXX")"
HERMES_HOME="$WORK/hermes-home"
PROJECT="$WORK/project"

start=$(date +%s)

echo "== 1/4  a fresh HERMES_HOME and a project to work on =="
mkdir -p "$HERMES_HOME/plugins" "$PROJECT"
git -C "$PROJECT" init -q -b main
git -C "$PROJECT" config user.email install@example.com
git -C "$PROJECT" config user.name Install
printf 'def greet():\n    return "hi"\n' > "$PROJECT/app.py"
git -C "$PROJECT" add -A
git -C "$PROJECT" commit -qm init

echo "== 2/4  installing the plugin (as 'hermes plugins install ...#plugin --enable' would) =="
cp -R "$REPO_ROOT/plugin" "$HERMES_HOME/plugins/worktree-sandbox"
cat > "$HERMES_HOME/config.yaml" <<'YAML'
plugins:
  enabled:
    - worktree-sandbox
terminal:
  backend: worktree
YAML

echo "== 3/4  first success: load the plugin, run a command in the worktree, run the demo race =="
HERMES_AGENT_REPO="$HERMES_AGENT_REPO" HERMES_HOME="$HERMES_HOME" "$PYTHON" - <<'PY'
import os, sys, asyncio, json, subprocess
from pathlib import Path

repo = os.environ["HERMES_AGENT_REPO"]
project = Path(os.environ["HERMES_HOME"]).parent / "project"
sys.path.insert(0, repo)
os.environ["TERMINAL_ENV"] = "worktree"
os.environ["TERMINAL_CWD"] = str(project)
os.chdir(project)

import hermes_cli.plugins as hp
from tools.registry import discover_builtin_tools, registry

hp.discover_plugins()
loaded = {p["name"]: p for p in hp.get_plugin_manager().list_plugins()}
entry = loaded.get("worktree-sandbox")
assert entry and entry["enabled"] and not entry["error"], f"plugin did not load: {entry}"
print(f"  plugin loaded: {entry['name']} v{entry['version']} tools={entry['tools']} hooks={entry['hooks']}")

discover_builtin_tools()
assert registry.get_entry("worktree_race"), "worktree_race is not registered"

raw = registry.dispatch("terminal", {"command": "printf 'hello\\n' > installed.txt && pwd"})
result = json.loads(raw)
assert result.get("exit_code") == 0, raw
assert "/plugin-data/worktree-sandbox/worktrees/" in result.get("output", ""), raw
clean = subprocess.run(["git", "status", "--porcelain"], cwd=project, capture_output=True, text=True).stdout.strip()
assert clean == "", f"the checkout was modified: {clean!r}"
print("  terminal ran inside the worktree; host checkout still clean")

demo = json.loads(registry.dispatch("worktree_race", {
    "workspace": str(project),
    "candidates": [{"label": "a", "files": {"a.txt": "a\n"}}, {"label": "b", "files": {"b.txt": "b\n"}}],
    "verify_command": "test -f a.txt",
}))
assert demo["winner"] == "a", demo
print(f"  race winner: {demo['winner']}")

import importlib.util
api_path = Path(os.environ["HERMES_HOME"]) / "plugins" / "worktree-sandbox" / "dashboard" / "plugin_api.py"
spec = importlib.util.spec_from_file_location("hermes_dashboard_plugin_worktree-sandbox", api_path)
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
status = asyncio.run(mod.status())
assert status["ok"], status
print(f"  dashboard backend: /status -> {status['count']} worktree(s)")
PY

echo "== 4/4  the CLI surface answers =="
HERMES_AGENT_REPO="$HERMES_AGENT_REPO" HERMES_HOME="$HERMES_HOME" HERMES_PLUGINS_SMOKE=1 "$PYTHON" - <<'PY'
import os, sys
sys.path.insert(0, os.environ["HERMES_AGENT_REPO"])
import hermes_cli.plugins as hp
hp.discover_plugins()
commands = hp.get_plugin_manager()._cli_commands
assert "worktree" in commands, sorted(commands)
print("  hermes worktree is registered")
PY

elapsed=$(( $(date +%s) - start ))
echo
echo "first success in ${elapsed}s (budget ${BUDGET_SECONDS}s)"
if [ "$elapsed" -gt "$BUDGET_SECONDS" ]; then
  echo "FAIL: over budget"
  exit 1
fi
echo "PASS: clean install works and is under budget"
rm -rf "$WORK"
