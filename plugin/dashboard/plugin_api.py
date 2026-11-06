"""Backend routes for worktree-sandbox, mounted at ``/api/plugins/worktree-sandbox/``.

Hermes imports this file by path (``hermes_dashboard_plugin_worktree-sandbox``) and mounts the
``router`` object, so it cannot rely on the plugin's own package being importable. It therefore
bootstraps the shared core (``manager`` / ``storage`` / ``race``) by loading the plugin directory
the same way Hermes loads a directory plugin.

Everything here is a thin, defensive wrapper over that core: a ``WorktreeError`` becomes a 400 with
the user-facing message, anything else a 500 with a generic message (the traceback goes to the log).
The routes only ever touch the plugin's own data directory and the user's workspace; they add no
network access of their own.
"""

from __future__ import annotations

import importlib
import importlib.util
import logging
import sys
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)

router = APIRouter()

_PLUGIN_ROOT = Path(__file__).resolve().parents[1]
_PKG = "worktree_sandbox_runtime"

_core: dict[str, Any] | None = None


def _load_core() -> dict[str, Any]:
    """Load the plugin package under a private name and build the manager/ledger once."""
    if _PKG not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            _PKG, _PLUGIN_ROOT / "__init__.py", submodule_search_locations=[str(_PLUGIN_ROOT)]
        )
        if spec is None or spec.loader is None:  # pragma: no cover - defensive
            raise RuntimeError(f"cannot load worktree-sandbox from {_PLUGIN_ROOT}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[_PKG] = module
        spec.loader.exec_module(module)

    manager_mod = importlib.import_module(f"{_PKG}.manager")
    storage_mod = importlib.import_module(f"{_PKG}.storage")
    race_mod = importlib.import_module(f"{_PKG}.race")

    ledger = storage_mod.Ledger()
    manager = manager_mod.WorktreeManager(ledger)
    return {
        "manager": manager,
        "ledger": ledger,
        "race": race_mod,
        "WorktreeError": manager_mod.WorktreeError,
        "run_demo_race": race_mod.run_demo_race,
        "purge_demo_projects": race_mod.purge_demo_projects,
    }


def core() -> dict[str, Any]:
    global _core
    if _core is None:
        _core = _load_core()
    return _core


# --- helpers --------------------------------------------------------------- #

def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "count": len(rows),
        "dirty": sum(1 for r in rows if not r.get("clean")),
        "changed_files": sum(int(r.get("changed_files") or 0) for r in rows),
        "added": sum(int(r.get("added") or 0) for r in rows),
        "deleted": sum(int(r.get("deleted") or 0) for r in rows),
    }


def _fail(exc: Exception) -> HTTPException:
    if isinstance(exc, core()["WorktreeError"]):
        return HTTPException(status_code=400, detail=str(exc))
    logger.warning("worktree-sandbox API error: %s", exc, exc_info=True)
    return HTTPException(status_code=500, detail=f"worktree-sandbox: {exc}")


# --- routes ---------------------------------------------------------------- #

@router.get("/status")
async def status(workspace: str = "") -> dict[str, Any]:
    """Headline numbers for the Desktop status chip and pane header."""
    try:
        rows = core()["manager"].list_worktrees(workspace=workspace or None)
    except Exception as exc:  # noqa: BLE001 - surfaced as HTTP
        raise _fail(exc) from exc
    return {"ok": True, "backend": "worktree", **(_summary(rows))}


@router.get("/worktrees")
async def list_worktrees(workspace: str = "", include_inactive: bool = False) -> dict[str, Any]:
    try:
        rows = core()["manager"].list_worktrees(workspace=workspace or None, include_inactive=include_inactive)
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc) from exc
    return {"ok": True, "worktrees": rows, **_summary(rows)}


@router.post("/worktrees")
async def create_worktree(body: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = body or {}
    try:
        info = core()["manager"].create_worktree(
            payload.get("workspace"), task_id=str(payload.get("task_id") or "dashboard"),
            base=payload.get("base"),
        )
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc) from exc
    return {"ok": True, **info}


@router.get("/worktrees/{worktree_id}")
async def worktree_detail(worktree_id: str) -> dict[str, Any]:
    try:
        return {"ok": True, **core()["manager"].status(worktree_id)}
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc) from exc


@router.get("/worktrees/{worktree_id}/diff")
async def worktree_diff(worktree_id: str, path: str = "") -> dict[str, Any]:
    try:
        return {"ok": True, **core()["manager"].diff(worktree_id, path=path or None)}
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc) from exc


@router.post("/worktrees/{worktree_id}/promote")
async def promote(worktree_id: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = body or {}
    try:
        result = core()["manager"].promote(
            worktree_id, force=bool(payload.get("force")), files=payload.get("files"),
        )
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc) from exc
    if result.get("conflicts"):
        return {
            "ok": False,
            "error": "refused: files were modified on the host since the worktree base",
            **result,
        }
    return {"ok": True, **result}


@router.delete("/worktrees/{worktree_id}")
async def discard(worktree_id: str) -> dict[str, Any]:
    try:
        return {"ok": True, **core()["manager"].discard(worktree_id)}
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc) from exc


@router.post("/race")
async def race(body: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = body or {}
    candidates = payload.get("candidates")
    if not isinstance(candidates, list):
        raise HTTPException(status_code=400, detail="'candidates' must be an array of at least two entries")
    try:
        result = core()["race"].RaceRunner(core()["manager"], core()["ledger"]).race(
            payload.get("workspace"), candidates,
            verify_command=payload.get("verify_command") or None,
            timeout=payload.get("timeout") or 120,
            promote_winner=bool(payload.get("promote_winner")),
            keep_worktrees=bool(payload.get("keep_worktrees")),
            label=payload.get("label"),
        )
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc) from exc
    return {"ok": True, **result}


@router.post("/demo")
async def demo(body: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run the built-in offline demo race — the Desktop pane's one-click demo."""
    payload = body or {}
    try:
        if payload.get("reset"):
            core()["purge_demo_projects"](core()["manager"])
        result = core()["run_demo_race"](
            core()["manager"], keep_worktrees=bool(payload.get("keep_worktrees")))
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc) from exc
    return {"ok": True, **result}


@router.get("/races/{race_id}")
async def race_detail(race_id: str) -> dict[str, Any]:
    record = core()["ledger"].get_race(race_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"unknown race {race_id!r}")
    return {"ok": True, "race": record}


@router.get("/events")
async def events(limit: int = 50, worktree_id: str = "") -> dict[str, Any]:
    try:
        rows = core()["ledger"].recent_events(worktree_id or None, limit=limit)
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc) from exc
    return {"ok": True, "events": rows}


@router.get("/config")
async def config() -> dict[str, Any]:
    """Effective plugin settings, so the pane can show the verify command in use."""
    try:
        from hermes_cli.config import load_config_readonly

        entries = (load_config_readonly() or {}).get("plugins", {}).get("entries", {})
        settings = (entries.get("worktree-sandbox") or {}).get("settings") or {}
    except Exception:  # pragma: no cover - config unavailable
        settings = {}
    return {"ok": True, "settings": settings}
