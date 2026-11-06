#!/usr/bin/env python3
"""Vertical-slice proof: load the plugin in real Hermes and run one real action.

Runs the plugin through Hermes's own machinery against a throwaway ``HERMES_HOME``:

1. ``hermes_cli.plugins.discover_plugins()`` loads ``worktree-sandbox`` from ``$HERMES_HOME/plugins``.
2. The real ``terminal`` tool dispatches through ``terminal.backend: worktree``.
3. A command writes a file inside the isolated worktree; the user's checkout stays clean.
4. ``worktree_status`` / ``worktree_promote`` (real tool registry) apply it back.

Usage:
    HERMES_AGENT_REPO=/path/to/hermes-agent python scripts/vertical_slice.py
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PLUGIN_SRC = REPO / "plugin"


def _banner(text: str) -> None:
    print(f"\n=== {text} ===")


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True,
                   env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})


def main() -> int:
    hermes_repo = os.environ.get("HERMES_AGENT_REPO", "").strip()
    if not hermes_repo:
        print("set HERMES_AGENT_REPO to a Hermes Agent checkout")
        return 2
    sys.path.insert(0, hermes_repo)

    work_root = Path(tempfile.mkdtemp(prefix="worktree-slice-"))
    hermes_home = work_root / "hermes-home"
    hermes_home.mkdir(parents=True)

    # 1. Install the plugin the way `hermes plugins install` lays it out.
    plugins_dir = hermes_home / "plugins"
    plugins_dir.mkdir()
    shutil.copytree(PLUGIN_SRC, plugins_dir / "worktree-sandbox")

    (hermes_home / "config.yaml").write_text(
        "plugins:\n  enabled:\n    - worktree-sandbox\nterminal:\n  backend: worktree\n",
        encoding="utf-8",
    )

    # 2. A throwaway Git project the agent will "edit".
    project = work_root / "project"
    project.mkdir()
    _git(project, "init", "-b", "main")
    _git(project, "config", "user.email", "slice@example.com")
    _git(project, "config", "user.name", "Slice")
    (project / "app.py").write_text("def greet():\n    return 'hi'\n", encoding="utf-8")
    _git(project, "add", "-A")
    _git(project, "commit", "-m", "init")

    os.environ["HERMES_HOME"] = str(hermes_home)
    os.environ["TERMINAL_ENV"] = "worktree"
    os.environ["TERMINAL_CWD"] = str(project)
    os.environ["HERMES_SAFE_MODE"] = ""
    os.chdir(project)

    import hermes_cli.plugins as hp
    from tools.registry import discover_builtin_tools, registry

    _banner("1. Plugin discovery through the real PluginManager")
    hp.discover_plugins()
    manager = hp.get_plugin_manager()
    loaded = manager.list_plugins()
    for plugin in loaded:
        print(f"  {plugin['name']} v{plugin['version']} enabled={plugin['enabled']} "
              f"tools={plugin['tools']} hooks={plugin['hooks']} error={plugin['error']}")
    entry = next((p for p in loaded if p["name"] == "worktree-sandbox"), None)
    if not entry or not entry["enabled"] or entry["error"]:
        print("FAIL: plugin did not load cleanly")
        return 1

    _banner("2. Tools registered in the real registry")
    discover_builtin_tools()
    tool_names = sorted(n for n in registry.get_all_tool_names() if n.startswith("worktree"))
    print("  worktree tools:", tool_names)
    expected = {"worktree_create", "worktree_status", "worktree_diff", "worktree_promote", "worktree_race"}
    if set(tool_names) != expected:
        print(f"FAIL: expected {sorted(expected)}")
        return 1

    def dispatch(name: str, args: dict) -> dict:
        raw = registry.dispatch(name, args)
        print(f"  → {name}: {raw[:220]}{'...' if len(raw) > 220 else ''}")
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            return {"raw": raw}

    _banner("3. Real `terminal` tool runs inside the worktree")
    res = dispatch("terminal", {"command": "printf 'def greet():\\n    return \"slice\"\\n' > app.py "
                                          "&& printf 'new file\\n' > sliced.txt && pwd"})
    output = str(res.get("output", ""))
    worktree_seen = "/plugin-data/worktree-sandbox/worktrees/" in output
    print("  command ran inside a worktree:", worktree_seen)

    host_status = subprocess.run(["git", "status", "--porcelain"], cwd=str(project),
                                capture_output=True, text=True).stdout.strip()
    print("  host `git status --porcelain`:", repr(host_status))
    host_app = (project / "app.py").read_text(encoding="utf-8")
    print("  host app.py still original:", "slice" not in host_app)

    if host_status != "" or "slice" in host_app:
        print("FAIL: the host checkout was modified")
        return 1

    _banner("4. worktree_status / worktree_diff / worktree_promote (real tools)")
    listing = dispatch("worktree_status", {"workspace": str(project)})
    worktrees = listing.get("worktrees") or []
    if not worktrees:
        print("FAIL: no worktrees listed")
        return 1
    wid = worktrees[0]["worktree_id"]
    print("  worktree:", wid, "changed_files:", worktrees[0]["changed_files"],
          "added:", worktrees[0]["added"], "deleted:", worktrees[0]["deleted"])

    diff = dispatch("worktree_diff", {"worktree_id": wid})
    print("  diff has 'slice':", "slice" in diff.get("diff", ""))

    promoted = dispatch("worktree_promote", {"worktree_id": wid})
    print("  promoted ok:", promoted.get("ok"), "applied:", promoted.get("applied"),
          "backup_dir set:", bool(promoted.get("backup_dir")))

    final_app = (project / "app.py").read_text(encoding="utf-8")
    print("  host app.py now contains 'slice':", "slice" in final_app)
    print("  host sliced.txt exists:", (project / "sliced.txt").exists())

    if "slice" not in final_app or not (project / "sliced.txt").exists():
        print("FAIL: promotion did not land")
        return 1

    _banner("5. worktree_race — parallel candidates scored by a verify command")
    race = dispatch("worktree_race", {
        "workspace": str(project),
        "candidates": [
            {"label": "reuse-app", "files": {"race_a.txt": "alpha\n"}},
            {"label": "bad-candidate", "files": {"race_b.txt": "beta\n"}},
        ],
        "verify_command": "test -f race_a.txt",
        "promote_winner": True,
    })
    for row in race.get("results", []):
        print(f"    {row['label']:<14} passed={row['passed']} "
              f"score={row['score']} +{row['added']}/-{row['deleted']}")
    print("  winner:", race.get("winner"), "| promoted:", bool(race.get("promoted")))
    if race.get("winner") != "reuse-app" or not (project / "race_a.txt").exists():
        print("FAIL: race did not pick and promote the passing candidate")
        return 1

    _banner("6. Slash command + CLI surfaces registered")
    manager_commands = hp.get_plugin_commands()
    print("  plugin slash commands:", sorted(manager_commands))
    cli = manager._cli_commands
    print("  plugin CLI commands:", sorted(cli))
    if "sandbox" not in manager_commands or "worktree" not in cli:
        print("FAIL: /sandbox or `hermes worktree` was not registered")
        return 1

    slash = manager_commands["sandbox"]["handler"]
    print("  /sandbox demo →")
    for line in slash("demo").splitlines():
        print("    " + line)

    _banner("7. Lifecycle hooks registered")
    for hook in ("on_session_start", "post_tool_call", "pre_verify", "on_session_finalize"):
        print(f"  {hook}: {manager.has_hook(hook)}")
    if not all(manager.has_hook(h) for h in
               ("on_session_start", "post_tool_call", "pre_verify", "on_session_finalize")):
        print("FAIL: lifecycle hooks were not registered")
        return 1

    _banner("RESULT: vertical slice PASSED")
    print(f"  throwaway home: {hermes_home}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001 - report and exit non-zero for the caller
        import traceback

        traceback.print_exc()
        print(f"\nFAIL: {exc}")
        raise SystemExit(1) from exc
