"""Tool handlers — real code the model calls. Every handler returns a JSON string.

Rules (from the Hermes developer guide): a handler receives ``args`` (the parameters the LLM
passed) plus optional context keywords, must return a JSON string on success **and** on error,
and must never raise.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from .events import emit as _emit
from .manager import WorktreeError, WorktreeManager
from .race import RaceRunner
from .storage import Ledger

logger = logging.getLogger(__name__)


def _ok(**payload: Any) -> str:
    return json.dumps({"ok": True, **payload}, default=str)


def _err(message: str, **extra: Any) -> str:
    return json.dumps({"ok": False, "error": message, **extra}, default=str)


def _session_workspace(args: dict[str, Any]) -> str:
    """Resolve the repo to operate on: explicit arg, else the session's working directory."""
    explicit = args.get("workspace")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()
    return session_workspace()


def session_workspace() -> str:
    """The session's own working directory (what the model's commands run against)."""
    try:
        from agent.runtime_cwd import resolve_agent_cwd

        return str(resolve_agent_cwd())
    except Exception:
        return os.getcwd()


def is_forbidden_workspace(path: Path) -> str | None:
    """Refuse a workspace that must never be raced or promoted into, or ``None`` if it is fine.

    A model-supplied ``workspace`` used to be taken at face value, so ``~`` (or ``$HERMES_HOME``)
    would have had file edits written straight into it. Home, the Hermes home and the filesystem
    root are refused outright; everything else must be the session's project or inside it.
    """
    try:
        resolved = path.expanduser().resolve()
    except (OSError, RuntimeError):
        return f"workspace {str(path)!r} cannot be resolved"

    homes: list[Path] = []
    for raw in (os.path.expanduser("~"), os.environ.get("HERMES_HOME")):
        if raw:
            try:
                homes.append(Path(raw).expanduser().resolve())
            except (OSError, RuntimeError):
                continue
    for home in homes:
        if resolved == home or home in resolved.parents:
            return (
                f"refusing to use {resolved} as a workspace: it is (or is inside) a home directory. "
                "Point the tool at the project you want isolated."
            )
    if resolved == resolved.anchor or str(resolved) == "/":
        return f"refusing to use {resolved} as a workspace"

    try:
        project = Path(session_workspace()).expanduser().resolve()
    except (OSError, RuntimeError):
        project = None
    if project is not None:
        # The session's project root (its repo root when it has one) bounds what we will touch.
        try:
            root = Path(os.path.realpath(project))
        except OSError:
            root = project
        if not (resolved == root or root in resolved.parents):
            return (
                f"refusing workspace {resolved}: it is outside the session's project "
                f"({root}). Run the tool against the project the session is working in."
            )
    return None


def resolve_requested_workspace(args: dict[str, Any]) -> tuple[str | None, str | None]:
    """Return ``(workspace, error)`` for a tool call's ``workspace`` argument."""
    explicit = args.get("workspace")
    if not (isinstance(explicit, str) and explicit.strip()):
        return session_workspace(), None
    problem = is_forbidden_workspace(Path(explicit.strip()))
    if problem:
        return None, problem
    return explicit.strip(), None


def _type_error(key: str, value: Any, expected: str) -> str:
    return f"{key} must be {expected}, got {type(value).__name__}"


def _check_optional_str(args: dict[str, Any], key: str) -> str | None:
    """None when *key* is absent/empty or a string; the error message otherwise."""
    value = args.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, str):
        return None
    return _type_error(key, value, "a string")


def _check_optional_bool(args: dict[str, Any], key: str) -> str | None:
    value = args.get(key)
    if value is None or isinstance(value, bool):
        return None
    return _type_error(key, value, "true or false")


def _check_optional_int(args: dict[str, Any], key: str) -> str | None:
    value = args.get(key)
    if value is None or (isinstance(value, int) and not isinstance(value, bool)):
        return None
    return _type_error(key, value, "an integer")


def _check_files_list(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        return "files must be an array of non-empty repo-relative paths"
    return None


class WorktreeTools:
    """Bundles the manager + ledger behind the worktree tool handlers."""

    def __init__(self, manager: WorktreeManager | None = None, ledger: Ledger | None = None) -> None:
        self.ledger = ledger or Ledger()
        self.manager = manager or WorktreeManager(self.ledger)
        self.racer = RaceRunner(self.manager, self.ledger)

    # -- worktree_create ---------------------------------------------------------

    def worktree_create(self, args: dict[str, Any], **kwargs: Any) -> str:
        try:
            for key in ("workspace", "task_id", "base"):
                problem = _check_optional_str(args, key)
                if problem:
                    return _err(problem)
            workspace, problem = resolve_requested_workspace(args)
            if problem:
                return _err(problem)
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
            for key in ("workspace", "worktree_id"):
                problem = _check_optional_str(args, key)
                if problem:
                    return _err(problem)
            problem = _check_optional_bool(args, "include_inactive")
            if problem:
                return _err(problem)

            worktree_id = args.get("worktree_id")
            if isinstance(worktree_id, str) and worktree_id.strip():
                return _ok(**self.manager.status(worktree_id.strip()))

            workspace: str | None = None
            include_inactive = bool(args.get("include_inactive", False))
            requested, problem = resolve_requested_workspace(args)
            if problem:
                return _err(problem)
            try:
                workspace = str(self.manager.peek_workspace(requested))
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
            problem = _check_optional_str(args, "worktree_id")
            if problem:
                return _err(problem)
            problem = _check_optional_bool(args, "force")
            if problem:
                return _err(problem)
            problem = _check_files_list(args.get("files"))
            if problem:
                return _err(problem)

            worktree_id = str(args.get("worktree_id") or "").strip()
            if not worktree_id:
                return _err("worktree_promote requires a worktree_id")
            force = bool(args.get("force", False))
            files = args.get("files")
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

    # -- worktree_race -----------------------------------------------------------

    def worktree_race(self, args: dict[str, Any], **kwargs: Any) -> str:
        try:
            candidates = args.get("candidates")
            if not isinstance(candidates, list):
                return _err("worktree_race requires a 'candidates' array of at least two entries")
            for key in ("workspace", "verify_command"):
                problem = _check_optional_str(args, key)
                if problem:
                    return _err(problem)
            for key in ("promote_winner", "keep_worktrees"):
                problem = _check_optional_bool(args, key)
                if problem:
                    return _err(problem)
            problem = _check_optional_int(args, "timeout")
            if problem:
                return _err(problem)

            workspace, problem = resolve_requested_workspace(args)
            if problem:
                return _err(problem)
            verify_command = args.get("verify_command")
            timeout = args.get("timeout", 120)
            result = self.racer.race(
                workspace, candidates,
                verify_command=(verify_command or None),
                timeout=timeout if isinstance(timeout, int) else 120,
                promote_winner=bool(args.get("promote_winner", False)),
                keep_worktrees=bool(args.get("keep_worktrees", False)),
            )
            _emit("race.completed", {"race_id": result["race_id"], "winner": result["winner"]})
            return _ok(**result)
        except WorktreeError as exc:
            return _err(str(exc))
        except Exception as exc:
            logger.warning("worktree_race failed: %s", exc, exc_info=True)
            return _err(f"worktree_race failed: {exc}")
