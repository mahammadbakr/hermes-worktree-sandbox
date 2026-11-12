"""Lifecycle hooks: keep the ledger and Desktop surface in sync, and gate on verification.

Every hook is best-effort and fail-open — a hook that raises is logged and skipped by Hermes, so
none of this can break a turn. Two behaviours are deliberately conservative:

* ``post_tool_call`` does real (cheap) ``git`` work, so it is throttled per worktree and only fires
  for tools that can change files.
* ``pre_verify`` only does anything when the operator sets ``verify_command`` in the plugin config;
  its default is empty, so an unconfigured install pays nothing.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from . import race as race_module
from .events import emit
from .manager import WorktreeError, WorktreeManager
from .storage import Ledger

logger = logging.getLogger(__name__)

# Tools that can change the working tree; only these trigger a stats refresh.
_MUTATING_TOOLS = frozenset({
    "terminal", "execute_code", "write_file", "patch", "file_edit", "apply_patch",
    "create_file", "delete_file", "move_file", "edit_file", "str_replace_editor",
})
_REFRESH_INTERVAL_S = 1.5
_VERIFY_TIMEOUT_S = 60
_MAX_SHOWN_COMMAND = 160


def _short(value: Any) -> str:
    """One-line, length-bounded rendering of a command for an approval prompt."""
    text = " ".join(str(value or "").split())
    return text if len(text) <= _MAX_SHOWN_COMMAND else text[:_MAX_SHOWN_COMMAND] + "…"


class HookHandlers:
    """Owns the per-session bookkeeping the hooks read."""

    def __init__(
        self, manager: WorktreeManager, ledger: Ledger, *,
        get_config: Callable[..., Any] | None = None,
    ) -> None:
        self.manager = manager
        self.ledger = ledger
        self._get_config = get_config or (lambda key, default=None: default)
        self._active_by_task: dict[str, str] = {}   # task_id -> worktree_id
        self._last_refresh: dict[str, float] = {}
        self._verified: set[str] = set()

    def _config(self, key: str, default: Any = None) -> Any:
        try:
            return self._get_config(key, default)
        except Exception:  # pragma: no cover - defensive
            return default

    # -- provider callback -------------------------------------------------------

    def on_worktree_created(self, task_id: str, worktree_id: str) -> None:
        """Called by the terminal provider when a worktree is created/reused."""
        if task_id and worktree_id:
            self._active_by_task[str(task_id)] = worktree_id

    # -- hooks -------------------------------------------------------------------

    def on_session_start(self, session_id: str = "", model: str = "", platform: str = "", **kwargs: Any) -> None:
        self.ledger.record_event(None, "session.start", {"platform": platform, "model": model})
        emit("session.started", {"session_id": session_id, "platform": platform})

    # -- approval gate -----------------------------------------------------------

    def pre_tool_call(self, tool_name: str = "", args: dict[str, Any] | None = None, **kwargs: Any) -> dict[str, Any] | None:
        """Route the plugin's own privileged tool calls through Hermes' approval gate.

        ``worktree_race`` executes commands the model wrote (candidate, setup and verify commands) in
        its own worktrees rather than through the active terminal backend, and ``worktree_promote``
        writes into the user's real folder. Both are exactly the calls a person should see, so this
        hook returns ``{"action": "approve", ...}`` with the commands and the file list, which
        Hermes turns into its normal approval prompt (and fails closed when nobody can answer, e.g.
        cron or the gateway).

        User-started runs — the ``/sandbox`` commands and the Desktop pane, which call the manager
        directly — do not go through tool dispatch and are not gated here.
        """
        try:
            args = args if isinstance(args, dict) else {}
            if tool_name == "worktree_race":
                return self._gate_race(args)
            if tool_name == "worktree_promote":
                return self._gate_promote(args)
            return None
        except Exception as exc:  # never fail open: ask a person instead of running unapproved
            logger.warning("worktree-sandbox: approval gate failed (%s); escalating to the user", exc)
            return {
                "action": "approve",
                "message": (
                    f"{tool_name or 'worktree tool'} refused to describe its own call "
                    f"({exc}). Approve only if you expected it."
                ),
            }

    def _gate_race(self, args: dict[str, Any]) -> dict[str, Any] | None:
        lines: list[str] = []
        raw_candidates = args.get("candidates")
        candidates: list[Any] = raw_candidates if isinstance(raw_candidates, list) else []
        for index, candidate in enumerate(candidates[:5], start=1):
            if not isinstance(candidate, dict):
                continue
            label = str(candidate.get("label") or f"candidate-{index}")[:40]
            setup = candidate.get("setup_command")
            command = candidate.get("command")
            raw_files = candidate.get("files")
            files: dict[str, Any] = raw_files if isinstance(raw_files, dict) else {}
            bits = [f"{len(files)} file(s)"] if files else []
            if setup:
                bits.append(f"setup: {_short(setup)}")
            if command:
                bits.append(f"command: {_short(command)}")
            lines.append(f"  • {label}: " + ("; ".join(bits) if bits else "no command"))
        verify = args.get("verify_command")
        if verify:
            lines.append(f"  • verify: {_short(verify)}")
        if len(candidates) > 5:
            lines.append(f"  • …and {len(candidates) - 5} more")

        message = [
            "worktree_race will run the following in its own isolated Git worktrees "
            "(not through your terminal backend):",
            *lines,
        ]
        workspace = args.get("workspace")
        if isinstance(workspace, str) and workspace.strip():
            message.append(f"  workspace: {workspace.strip()}")
        if args.get("promote_winner"):
            message.append(
                "It will also promote the winning candidate INTO YOUR PROJECT "
                f"({workspace.strip() if isinstance(workspace, str) and workspace.strip() else 'the session project'}), "
                "writing and deleting files there (a backup is written first)."
            )
        return {"action": "approve", "message": "\n".join(message), "rule_key": "worktree_race"}

    def _gate_promote(self, args: dict[str, Any]) -> dict[str, Any] | None:
        worktree_id = str(args.get("worktree_id") or "").strip()
        if not worktree_id:
            return None
        target, changes = "", None
        try:
            record = self.manager.require(worktree_id)
            target = str(record.get("workspace") or "")
        except Exception:
            record = None
        raw_requested = args.get("files")
        requested: list[Any] = raw_requested if isinstance(raw_requested, list) else []
        if requested:
            listed = ", ".join(str(f) for f in requested[:10])
            if len(requested) > 10:
                listed += f", …and {len(requested) - 10} more"
            files_line = f"  files: {listed}"
        elif record is not None:
            try:
                status = self.manager.status(worktree_id)
                changes = status.get("changed_files")
                files_line = f"  every changed file in the worktree ({changes} file(s))"
            except Exception:
                files_line = "  every changed file in the worktree"
        else:
            files_line = "  every changed file in the worktree"

        message = [
            f"worktree_promote will write '{worktree_id}' into YOUR PROJECT"
            + (f" at {target}" if target else "")
            + " (overwriting and deleting files; a timestamped backup is written first):",
            files_line,
        ]
        if args.get("force"):
            message.append("  force: true — files you edited since the worktree base will be overwritten")
        return {"action": "approve", "message": "\n".join(message), "rule_key": "worktree_promote"}

    def post_tool_call(self, tool_name: str = "", task_id: str = "", **kwargs: Any) -> None:
        if tool_name not in _MUTATING_TOOLS:
            return
        worktree_id = self._active_by_task.get(str(task_id or ""))
        if not worktree_id:
            return
        now = time.monotonic()
        if now - self._last_refresh.get(worktree_id, 0.0) < _REFRESH_INTERVAL_S:
            return
        self._last_refresh[worktree_id] = now
        try:
            status = self.manager.status(worktree_id)
        except WorktreeError:
            return
        emit("updated", {
            "worktree_id": worktree_id, "changed_files": status["changed_files"],
            "added": status["added"], "deleted": status["deleted"], "clean": status["clean"],
        })

    def pre_verify(self, session_id: str = "", changed_paths: Any = None, **kwargs: Any) -> dict[str, Any] | None:
        """Run the configured verification command in the worktree this turn touched.

        Returns a ``{"action": "continue", "message": ...}`` directive when verification fails, so
        the agent keeps working instead of declaring success. Empty ``verify_command`` → no-op.

        The worktree is chosen from the turn's ``changed_paths`` so a dirty worktree from another
        project can never be verified by mistake; without a match we fall back to the newest dirty
        worktree.
        """
        command = str(self._config("verify_command", "") or "").strip()
        if not command:
            return None
        if session_id and session_id in self._verified:
            return None

        worktree_id = self._pick_worktree(changed_paths)
        if not worktree_id:
            return None
        if session_id:
            self._verified.add(session_id)
        try:
            record = self.manager._require(worktree_id)  # noqa: SLF001 - same package
        except WorktreeError:
            return None
        worktree_path = record["path"]
        try:
            timeout = int(self._config("verify_timeout", _VERIFY_TIMEOUT_S))
        except (TypeError, ValueError):
            timeout = _VERIFY_TIMEOUT_S
        from pathlib import Path

        run = race_module._run_bounded(Path(worktree_path), command, max(5, min(timeout, 600)))
        self.ledger.record_event(worktree_id, "verify", {
            "command": command, "passed": run["passed"], "duration_ms": run["duration_ms"],
        })
        emit("verified", {"worktree_id": worktree_id, "passed": run["passed"],
                          "duration_ms": run["duration_ms"]})
        if run["passed"]:
            return None
        return {
            "action": "continue",
            "message": (
                f"Verification command `{command}` failed in the isolated worktree "
                f"{worktree_id} (exit code {run['exit_code']}). The user's checkout is unchanged. "
                f"Fix the failure, or report it. Output tail:\n{run['output'][:800]}"
            ),
        }

    def on_session_finalize(self, session_id: str = "", platform: str = "", **kwargs: Any) -> None:
        try:
            limit = int(self._config("max_worktrees", 20))
        except (TypeError, ValueError):
            limit = 20
        kept = bool(self._config("keep_on_exit", True))
        try:
            if kept:
                self.manager.prune(limit)
            else:
                for row in self.manager.list_worktrees():
                    if row.get("clean"):
                        self.manager.discard(row["worktree_id"])
        except Exception:  # pragma: no cover - teardown must never raise
            logger.debug("worktree-sandbox: prune on session finalize failed", exc_info=True)
        self._active_by_task.clear()
        self._last_refresh.clear()

    # -- helpers -----------------------------------------------------------------

    def _newest_dirty_worktree(self) -> str | None:
        try:
            rows = self.manager.list_worktrees()
        except Exception:  # pragma: no cover - defensive
            return None
        for row in rows:  # newest first
            if not row.get("clean"):
                return row["worktree_id"]
        return None

    def _pick_worktree(self, changed_paths: Any) -> str | None:
        """The dirty worktree this turn touched, else the newest dirty one."""
        try:
            rows = [row for row in self.manager.list_worktrees() if not row.get("clean")]
        except Exception:  # pragma: no cover - defensive
            return None
        if not rows:
            return None
        paths = [p for p in (changed_paths or []) if isinstance(p, str) and p]
        if paths:
            from pathlib import Path

            for row in rows:
                worktree_root = str(row.get("path") or "")
                workspace_root = str(row.get("workspace") or "")
                for raw in paths:
                    if worktree_root and raw.startswith(worktree_root):
                        return row["worktree_id"]
                    try:
                        if workspace_root and (Path(workspace_root) / raw).exists():
                            return row["worktree_id"]
                        if worktree_root and (Path(worktree_root) / raw).exists():
                            return row["worktree_id"]
                    except OSError:
                        continue
        return rows[0]["worktree_id"]
