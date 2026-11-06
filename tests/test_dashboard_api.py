"""Tests for the dashboard backend routes (``plugin/dashboard/plugin_api.py``).

The routes are plain async functions, so they are exercised directly rather than through a live
FastAPI server. A fake core is injected so no Hermes install and no real ``plugin-data`` is needed.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")

from helpers import PLUGIN_DIR  # noqa: E402

API_PATH = PLUGIN_DIR / "dashboard" / "plugin_api.py"


def _load_api_module():
    spec = importlib.util.spec_from_file_location("worktree_sandbox_api_under_test", API_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def api(manager, ledger):
    module = _load_api_module()
    from worktree_sandbox import race as race_module
    from worktree_sandbox.manager import WorktreeError

    # Shape matches what ``_load_core()`` builds in production (module, not instance).
    module._core = {
        "manager": manager,
        "ledger": ledger,
        "race": race_module,
        "WorktreeError": WorktreeError,
        "run_demo_race": race_module.run_demo_race,
        "purge_demo_projects": race_module.purge_demo_projects,
    }
    return module


def run(coro):
    return asyncio.run(coro)


def test_status_empty(api) -> None:
    payload = run(api.status())
    assert payload["ok"] is True
    assert payload["count"] == 0
    assert payload["backend"] == "worktree"


def test_create_list_status_diff_promote_discard(api, git_repo: Path) -> None:
    created = run(api.create_worktree({"workspace": str(git_repo), "task_id": "api"}))
    assert created["ok"] is True
    wid = created["worktree_id"]

    Path(created["path"]).joinpath("api_file.txt").write_text("from api\n", encoding="utf-8")

    listing = run(api.list_worktrees(workspace=str(git_repo)))
    assert listing["count"] == 1
    assert listing["changed_files"] == 1
    assert listing["added"] == 1

    detail = run(api.worktree_detail(wid))
    assert detail["ok"] is True and detail["files"][0]["path"] == "api_file.txt"

    diff = run(api.worktree_diff(wid))
    assert "from api" in diff["diff"]

    stat = run(api.status(workspace=str(git_repo)))
    assert stat["dirty"] == 1 and stat["added"] == 1

    promoted = run(api.promote(wid, {}))
    assert promoted["ok"] is True
    assert (git_repo / "api_file.txt").read_text(encoding="utf-8") == "from api\n"

    discarded = run(api.discard(wid))
    assert discarded["state"] in ("discarded", "promoted")
    assert (git_repo / "api_file.txt").exists()


def test_promote_conflict_returns_ok_false(api, git_repo: Path) -> None:
    created = run(api.create_worktree({"workspace": str(git_repo), "task_id": "conflict"}))
    Path(created["path"]).joinpath("app.py").write_text("wt\n", encoding="utf-8")
    (git_repo / "app.py").write_text("host\n", encoding="utf-8")

    payload = run(api.promote(created["worktree_id"], {}))
    assert payload["ok"] is False
    assert payload["conflicts"][0]["path"] == "app.py"


def test_unknown_worktree_maps_to_400(api) -> None:
    with pytest.raises(fastapi.HTTPException) as info:
        run(api.worktree_detail("wt-nope-000000"))
    assert info.value.status_code == 400
    assert "unknown worktree" in info.value.detail


def test_race_requires_candidates(api) -> None:
    with pytest.raises(fastapi.HTTPException) as info:
        run(api.race({"workspace": "/tmp"}))
    assert info.value.status_code == 400


def test_race_endpoint(api, git_repo: Path) -> None:
    payload = run(api.race({
        "workspace": str(git_repo),
        "candidates": [
            {"label": "winner", "files": {"w.txt": "w\n"}},
            {"label": "loser", "files": {"l.txt": "l\n"}},
        ],
        "verify_command": "test -f w.txt",
    }))
    assert payload["ok"] is True
    assert payload["winner"] == "winner"


def test_race_detail_and_events(api, git_repo: Path) -> None:
    race = run(api.race({
        "workspace": str(git_repo),
        "candidates": [{"label": "a", "files": {"a": "1"}}, {"label": "b", "files": {"b": "2"}}],
        "verify_command": "true",
    }))
    detail = run(api.race_detail(race["race_id"]))
    assert detail["ok"] is True
    assert detail["race"]["winner"] == race["winner"]

    events = run(api.events(limit=10))
    assert events["ok"] is True and isinstance(events["events"], list)

    with pytest.raises(fastapi.HTTPException) as info:
        run(api.race_detail("race-missing"))
    assert info.value.status_code == 404


def test_demo_endpoint(api) -> None:
    payload = run(api.demo({}))
    assert payload["ok"] is True
    assert payload["winner"] == "careful"


def test_config_endpoint(api) -> None:
    payload = run(api.config())
    assert payload["ok"] is True
    assert isinstance(payload["settings"], dict)


def test_router_has_expected_routes(api) -> None:
    paths = {route.path for route in api.router.routes}
    for expected in ("/status", "/worktrees", "/worktrees/{worktree_id}",
                     "/worktrees/{worktree_id}/diff", "/worktrees/{worktree_id}/promote",
                     "/race", "/demo", "/races/{race_id}", "/events", "/config"):
        assert expected in paths, f"missing route {expected}"


def test_injected_ledger_receives_race_records(api, ledger) -> None:
    payload = run(api.demo({}))
    record = ledger.get_race(payload["race_id"])
    assert record is not None
    assert record["winner"] == payload["winner"]
