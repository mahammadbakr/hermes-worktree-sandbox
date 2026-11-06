"""``/worktree`` slash command and ``hermes worktree`` CLI.

Both share one verb dispatcher so the text output is identical everywhere (CLI, TUI, Desktop,
Telegram/Discord/Slack). The slash command additionally offers an interactive picker via
``ctx.ask_choice`` when a worktree id is omitted — and degrades to a text usage hint in
unattended runs (cron, gateway) where ``ask_choice`` returns ``None``.
"""

from __future__ import annotations

import argparse
import os
from collections.abc import Callable
from typing import Any

from . import race as race_module
from .events import emit
from .manager import WorktreeError, WorktreeManager
from .storage import Ledger

USAGE = (
    "Usage: /sandbox <status|list|diff <id>|promote <id> [--force]|discard <id>|"
    "prune [n]|demo [--reset]|help>"
)

_DEFAULT_VERB = "status"


def _workspace() -> str:
    try:
        from agent.runtime_cwd import resolve_agent_cwd

        return str(resolve_agent_cwd())
    except Exception:
        return os.getcwd()


def _fmt_status_row(row: dict[str, Any]) -> str:
    state = row.get("state") or "active"
    mark = "clean" if row.get("clean") else "dirty"
    return (f"  {row['worktree_id']}  [{state}/{mark}]  "
            f"+{row.get('added', 0)}/-{row.get('deleted', 0)} in "
            f"{row.get('changed_files', 0)} file(s)  {row.get('path', '')}")


class WorktreeCommands:
    """Verb dispatcher shared by the slash command and the CLI."""

    def __init__(self, manager: WorktreeManager, ledger: Ledger | None = None) -> None:
        self.manager = manager
        self.ledger = ledger or manager.ledger
        self.runner = race_module.RaceRunner(manager, self.ledger)

    # -- verbs -------------------------------------------------------------------

    def status(self, workspace: str | None = None) -> str:
        try:
            target = str(self.manager.peek_workspace(workspace or _workspace()))
            rows = self.manager.list_worktrees(workspace=target)
        except WorktreeError:
            try:
                rows = self.manager.list_worktrees()
            except Exception as exc:  # noqa: BLE001 - a broken manager must still produce text
                return f"worktree: {exc}"
        except Exception as exc:  # noqa: BLE001
            return f"worktree: {exc}"
        if not rows:
            return ("No managed worktrees yet. Set `terminal.backend: worktree` (or call "
                    "`worktree_create`) to isolate a session, or run `/worktree demo` for a live race.")
        header = f"Worktrees ({len(rows)}):"
        return "\n".join([header, *(_fmt_status_row(r) for r in rows)])

    def diff(self, worktree_id: str) -> str:
        result = self.manager.diff(worktree_id)
        summary = f"{worktree_id}: {result.get('branch')}"
        body = result.get("diff") or "(no changes)"
        return f"{summary}\n{body}"

    def promote(self, worktree_id: str, force: bool = False) -> str:
        result = self.manager.promote(worktree_id, force=force)
        emit("promoted", {"worktree_id": worktree_id, "applied": result["applied"]})
        lines = [f"Promoted {worktree_id}: {len(result['applied'])} applied, "
                 f"{len(result['deleted'])} deleted."]
        if result.get("backup_dir"):
            lines.append(f"  backup: {result['backup_dir']}")
        if result["conflicts"]:
            lines.append("  REFUSED for conflicting files (modified on the host since the base):")
            lines.extend(f"    - {c['path']}" for c in result["conflicts"])
            lines.append("  Re-run with --force to overwrite (a backup is still written).")
        if result.get("skipped"):
            lines.append("  skipped: " + ", ".join(s["path"] for s in result["skipped"]))
        if not result["applied"] and not result["deleted"] and not result["conflicts"]:
            lines.append("  (nothing to promote)")
        return "\n".join(lines)

    def discard(self, worktree_id: str) -> str:
        self.manager.discard(worktree_id)
        return f"Discarded {worktree_id} (worktree and branch removed; your checkout was never touched)."

    def prune(self, limit: int = 20) -> str:
        result = self.manager.prune(limit)
        if not result["removed"]:
            return f"Nothing to prune ({result['kept']} worktree(s) kept; dirty ones are never removed)."
        return (f"Pruned {len(result['removed'])} clean worktree(s): "
                f"{', '.join(result['removed'])}. Kept {result['kept']}.")

    def demo(self, reset: bool = False, keep: bool = False) -> str:
        if reset:
            race_module.purge_demo_projects(self.manager)
        result = race_module.run_demo_race(self.manager, keep_worktrees=keep)
        emit("race.completed", {"race_id": result["race_id"], "winner": result["winner"],
                                "demo": True})
        lines = [
            f"Demo race complete in {result['duration_ms']} ms "
            f"(verify: {result['verify_command']})",
            "",
        ]
        for rank, row in enumerate(result["results"], start=1):
            verdict = "PASS" if row["passed"] else ("TIMEOUT" if row["timed_out"] else "FAIL")
            lines.append(
                f"  {rank}. {row['label']:<14} {verdict:<8} {row['duration_ms']:>6} ms  "
                f"+{row['added']}/-{row['deleted']} in {row['changed_files']} file(s)  "
                f"score {row['score']}"
            )
        lines.append("")
        lines.append(f"  winner: {result['winner']}")
        keep_note = ""
        if keep:
            for row in result["results"]:
                lines.append(f"  worktree {row['worktree_id']} ({row['label']})")
            keep_note = " Promote or discard them from the Desktop pane or with /sandbox promote <id>."
        lines.append(f"  demo project: {result.get('project', '(unknown)')}")
        lines.append(
            "  Open that folder in Hermes to keep experimenting; the race itself needs no model, "
            "no network and no API key." + keep_note)
        return "\n".join(lines)

    # -- dispatch ----------------------------------------------------------------

    def dispatch(self, verb: str, args: list[str], *, ask: Callable[[str, list], Any] | None = None) -> str:
        verb = (verb or _DEFAULT_VERB).lower()
        try:
            if verb in ("status", "list", ""):
                return self.status(args[0] if args else None)
            if verb == "diff":
                worktree_id = self._pick(args, ask, "Which worktree do you want to diff?")
                if worktree_id is None:
                    return USAGE
                return self.diff(worktree_id)
            if verb == "promote":
                force = "--force" in args or "-f" in args
                rest = [a for a in args if not a.startswith("-")]
                worktree_id = self._pick(rest, ask, "Which worktree should I promote into your checkout?")
                if worktree_id is None:
                    return USAGE
                return self.promote(worktree_id, force=force)
            if verb == "discard":
                worktree_id = self._pick(args, ask, "Which worktree should I discard?")
                if worktree_id is None:
                    return USAGE
                return self.discard(worktree_id)
            if verb == "prune":
                limit = 20
                for token in args:
                    if token.isdigit():
                        limit = int(token)
                return self.prune(limit)
            if verb == "demo":
                return self.demo(reset="--reset" in args, keep="--keep" in args)
            if verb in ("help", "-h", "--help"):
                return USAGE
            return f"Unknown verb {verb!r}. {USAGE}"
        except WorktreeError as exc:
            return f"worktree: {exc}"
        except Exception as exc:  # never raise into a slash command / CLI
            return f"worktree: unexpected error: {exc}"

    def _pick(self, args: list[str], ask: Callable[[str, list], Any] | None, question: str) -> str | None:
        cleaned = [a for a in args if not a.startswith("-")]
        if cleaned:
            return cleaned[0]
        if ask is None:
            return None
        try:
            rows = self.manager.list_worktrees()
        except Exception:
            rows = []
        if not rows:
            return None
        choices = [
            {"value": row["worktree_id"],
             "label": row["worktree_id"],
             "description": f"+{row.get('added', 0)}/-{row.get('deleted', 0)} in "
                            f"{row.get('changed_files', 0)} file(s)"}
            for row in rows
        ]
        picked = ask(question, choices)
        return picked if isinstance(picked, str) and picked else None


# --------------------------------------------------------------------------- #
# In-session slash command
# --------------------------------------------------------------------------- #

def make_slash_handler(ctx, commands: WorktreeCommands) -> Callable[..., str]:
    """Build the ``/worktree`` handler bound to a live ``PluginContext``."""

    def handler(raw_args: str, **kwargs: Any) -> str:
        parts = (raw_args or "").split()
        verb = parts[0] if parts else _DEFAULT_VERB

        def ask(question: str, choices: list) -> Any:
            try:
                return ctx.ask_choice(question, choices)
            except Exception:  # unattended / no interactive surface
                return None

        return commands.dispatch(verb, parts[1:], ask=ask)

    return handler


# --------------------------------------------------------------------------- #
# `hermes worktree` CLI
# --------------------------------------------------------------------------- #

def setup_parser(subparser: argparse.ArgumentParser) -> None:
    subs = subparser.add_subparsers(dest="worktree_command")
    status = subs.add_parser("status", help="List managed worktrees with diff stats")
    status.add_argument("--workspace", default="", help="Only list worktrees for this project")
    listing = subs.add_parser("list", help="Alias for status")
    listing.add_argument("--workspace", default="", help="Only list worktrees for this project")
    diff = subs.add_parser("diff", help="Show a worktree's unified diff")
    diff.add_argument("worktree_id")
    promote = subs.add_parser("promote", help="Apply a worktree's changes to your checkout")
    promote.add_argument("worktree_id")
    promote.add_argument("--force", action="store_true", help="Overwrite conflicting host edits")
    discard = subs.add_parser("discard", help="Remove a worktree and its branch")
    discard.add_argument("worktree_id")
    prune = subs.add_parser("prune", help="Remove clean worktrees beyond a limit")
    prune.add_argument("--max", type=int, default=20, help="Worktrees to keep (default 20)")
    demo = subs.add_parser("demo", help="Run the built-in offline demo race")
    demo.add_argument("--reset", action="store_true", help="Delete seeded demo projects first")
    demo.add_argument("--keep", action="store_true", help="Keep the candidate worktrees")


def make_cli_handler(commands: WorktreeCommands) -> Callable[[argparse.Namespace], int]:
    def handle(args: argparse.Namespace) -> int:
        verb = getattr(args, "worktree_command", None) or "status"
        argv: list[str] = []
        if verb in ("status", "list"):
            workspace = getattr(args, "workspace", "") or ""
            argv = [workspace] if workspace else []
        elif verb == "diff":
            argv = [args.worktree_id]
        elif verb == "promote":
            argv = [args.worktree_id] + (["--force"] if args.force else [])
        elif verb == "discard":
            argv = [args.worktree_id]
        elif verb == "prune":
            argv = [str(args.max)]
        elif verb == "demo":
            argv = ["--reset"] if args.reset else []
            if args.keep:
                argv.append("--keep")
        print(commands.dispatch(verb, argv))
        return 0

    return handle


__all__ = ["WorktreeCommands", "make_slash_handler", "make_cli_handler", "setup_parser", "USAGE"]
