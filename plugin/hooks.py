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

    def pre_verify(self, session_id: str = "", **kwargs: Any) -> dict[str, Any] | None:
        """Run the configured verification command in the newest dirty worktree.

        Returns a ``{"action": "continue", "message": ...}`` directive when verification fails, so
        the agent keeps working instead of declaring success. Empty ``verify_command`` → no-op.
        """
        command = str(self._config("verify_command", "") or "").strip()
        if not command:
            return None
        if session_id and session_id in self._verified:
            return None

        worktree_id = self._newest_dirty_worktree()
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
