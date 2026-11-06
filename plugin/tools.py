"""Tool handlers — real code the model calls. Every handler returns a JSON string.

Rules (from the Hermes developer guide): a handler receives ``args`` (the parameters the LLM
passed) plus optional context keywords, must return a JSON string on success **and** on error,
and must never raise.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from .manager import WorktreeError, WorktreeManager
from .storage import PLUGIN_NAME, Ledger

logger = logging.getLogger(__name__)


def _ok(**payload: Any) -> str:
    return json.dumps({"ok": True, **payload}, default=str)


def _err(message: str, **extra: Any) -> str:
    return json.dumps({"ok": False, "error": message, **extra}, default=str)


def _emit(event: str, payload: dict[str, Any]) -> None:
    """Best-effort push to connected Desktop/TUI clients; never raises."""
    try:
        from hermes_cli.plugin_events import broadcast_plugin_event

        broadcast_plugin_event(PLUGIN_NAME, event, payload)
    except Exception:  # pragma: no cover - no client attached / older core
        logger.debug("worktree-sandbox: broadcast of %s failed", event, exc_info=True)


def _session_workspace(args: dict[str, Any]) -> str:
    """Resolve the repo to operate on: explicit arg, else the session's working directory."""
    explicit = args.get("workspace")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()
    try:
        from agent.runtime_cwd import resolve_agent_cwd

        return str(resolve_agent_cwd())
    except Exception:
        return os.getcwd()


class WorktreeTools:
    """Bundles the manager + ledger behind the four tool handlers."""

    def __init__(self, manager: WorktreeManager | None = None, ledger: Ledger | None = None) -> None:
        self.ledger = ledger or Ledger()
        self.manager = manager or WorktreeManager(self.ledger)

    # -- worktree_create ---------------------------------------------------------

    def worktree_create(self, args: dict[str, Any], **kwargs: Any) -> str:
        try:
            workspace = _session_workspace(args)
            task_id = str(args.get("task_id") or kwargs.get("task_id") or "default")
            base = args.get("base") or None
            info = self.manager.create_worktree(workspace, task_id=task_id, base=base, reuse=True)
            self.ledger.record_event(info["worktree_id"], "tool:create", {"task_id": task_id})
            _emit("updated", {"worktree_id": info["worktree_id"], "state": "created"})
            return _ok(**info)
        except WorktreeError as exc:
            return _err(str(exc))
        except Exception as exc:  # never raise into the agent loop
            logger.warning("worktree_create failed: %s", exc, exc_info=True)
            return _err(f"worktree_create failed: {exc}")

    # -- worktree_status ---------------------------------------------------------

    def worktree_status(self, args: dict[str, Any], **kwargs: Any) -> str:
        try:
            worktree_id = args.get("worktree_id")
            if isinstance(worktree_id, str) and worktree_id.strip():
                return _ok(**self.manager.status(worktree_id.strip()))

            workspace: str | None = None
            include_inactive = bool(args.get("include_inactive", False))
            try:
                workspace = str(self.manager.resolve_workspace(_session_workspace(args)))
            except WorktreeError:
                workspace = None
            worktrees = self.manager.list_worktrees(workspace=workspace, include_inactive=include_inactive)
            return _ok(worktrees=worktrees, count=len(worktrees), workspace=workspace)
        except WorktreeError as exc:
            return _err(str(exc))
        except Exception as exc:
            logger.warning("worktree_status failed: %s", exc, exc_info=True)
            return _err(f"worktree_status failed: {exc}")

    # -- worktree_diff -----------------------------------------------------------

    def worktree_diff(self, args: dict[str, Any], **kwargs: Any) -> str:
        try:
            worktree_id = str(args.get("worktree_id") or "").strip()
            if not worktree_id:
                return _err("worktree_diff requires a worktree_id")
            path = args.get("path") or None
            if path is not None and not isinstance(path, str):
                return _err("path must be a string")
            result = self.manager.diff(worktree_id, path=path)
            return _ok(**result)
        except WorktreeError as exc:
            return _err(str(exc))
        except Exception as exc:
            logger.warning("worktree_diff failed: %s", exc, exc_info=True)
            return _err(f"worktree_diff failed: {exc}")

    # -- worktree_promote --------------------------------------------------------

    def worktree_promote(self, args: dict[str, Any], **kwargs: Any) -> str:
        try:
            worktree_id = str(args.get("worktree_id") or "").strip()
            if not worktree_id:
                return _err("worktree_promote requires a worktree_id")
            force = bool(args.get("force", False))
            files = args.get("files")
            if files is not None and not isinstance(files, list):
                return _err("files must be an array of repo-relative paths")
            result = self.manager.promote(worktree_id, force=force, files=files)
            _emit("promoted", {
                "worktree_id": worktree_id,
                "applied": result["applied"], "deleted": result["deleted"],
                "conflicts": [c["path"] for c in result["conflicts"]],
            })
            if result["conflicts"]:
                return json.dumps({
                    "ok": False,
                    "error": "refused: some files were modified on the host since the worktree was created",
                    **result,
                }, default=str)
            return _ok(**result)
        except WorktreeError as exc:
            return _err(str(exc))
        except Exception as exc:
            logger.warning("worktree_promote failed: %s", exc, exc_info=True)
            return _err(f"worktree_promote failed: {exc}")
