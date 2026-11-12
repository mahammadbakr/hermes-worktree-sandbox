"""Tests for the ``worktree_*`` tool handlers: valid JSON, no raising, correct flow."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from worktree_sandbox.storage import Ledger
from worktree_sandbox.tools import WorktreeTools


@pytest.fixture
def tools(manager, ledger) -> WorktreeTools:
    return WorktreeTools(manager=manager, ledger=ledger)


def _loads(raw: str) -> dict:
    assert isinstance(raw, str)
    payload = json.loads(raw)
    assert isinstance(payload, dict)
    return payload


def test_create_then_status_then_diff_then_promote(tools: WorktreeTools, git_repo: Path) -> None:
    created = _loads(tools.worktree_create({"workspace": str(git_repo), "task_id": "flow"}))
    assert created["ok"] is True
    worktree_id = created["worktree_id"]

    Path(created["path"]).joinpath("feature.py").write_text("VALUE = 42\n", encoding="utf-8")

    status = _loads(tools.worktree_status({"worktree_id": worktree_id}))
    assert status["ok"] is True
    assert status["changed_files"] == 1

    diff = _loads(tools.worktree_diff({"worktree_id": worktree_id}))
    assert diff["ok"] is True and "VALUE = 42" in diff["diff"]

    promoted = _loads(tools.worktree_promote({"worktree_id": worktree_id}))
    assert promoted["ok"] is True
    assert (git_repo / "feature.py").read_text(encoding="utf-8") == "VALUE = 42\n"


def test_status_lists_all_when_no_id(tools: WorktreeTools, git_repo: Path) -> None:
    _loads(tools.worktree_create({"workspace": str(git_repo), "task_id": "a"}))
    listed = _loads(tools.worktree_status({"workspace": str(git_repo)}))
    assert listed["ok"] is True
    assert listed["count"] >= 1
    assert all("worktree_id" in row for row in listed["worktrees"])


def test_status_outside_the_project_is_refused(tools: WorktreeTools, tmp_path: Path) -> None:
    """A workspace the model names outside the session's project is refused, not listed."""
    outside = tmp_path / "nowhere"
    outside.mkdir()
    listed = _loads(tools.worktree_status({"workspace": str(outside)}))
    assert listed["ok"] is False
    assert "outside the session's project" in listed["error"]


def test_status_does_not_create_shadow_repo(tools: WorktreeTools, tmp_path: Path, monkeypatch) -> None:
    quiet = tmp_path / "quiet"
    quiet.mkdir()
    monkeypatch.chdir(quiet)  # the session's project, so the workspace is allowed
    manager = tools.manager
    before = list(manager.shadow_root.iterdir()) if manager.shadow_root.is_dir() else []
    listed = _loads(tools.worktree_status({}))
    assert listed["ok"] is True
    after = list(manager.shadow_root.iterdir()) if manager.shadow_root.is_dir() else []
    assert before == after


@pytest.mark.parametrize(
    "handler,args",
    [
        ("worktree_diff", {}),
        ("worktree_diff", {"worktree_id": 123}),
        ("worktree_promote", {}),
        ("worktree_promote", {"worktree_id": "wt-x", "files": "not-a-list"}),
    ],
)
def test_bad_input_returns_error_not_raise(tools: WorktreeTools, handler: str, args: dict) -> None:
    payload = _loads(getattr(tools, handler)(args))
    assert payload["ok"] is False
    assert payload["error"]


def test_unknown_worktree_id_is_clean_error(tools: WorktreeTools) -> None:
    payload = _loads(tools.worktree_status({"worktree_id": "wt-missing-000000"}))
    assert payload["ok"] is False
    assert "unknown worktree" in payload["error"]


def test_create_on_non_git_workspace_uses_shadow_repo(tools: WorktreeTools, tmp_path: Path,
                                                      monkeypatch) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "main.py").write_text("X = 1\n", encoding="utf-8")
    monkeypatch.chdir(plain)  # the session's project
    payload = _loads(tools.worktree_create({"workspace": str(plain), "task_id": "shadow"}))
    assert payload["ok"] is True
    assert payload["shadow"] is True


def test_promote_conflict_reports_paths(tools: WorktreeTools, git_repo: Path) -> None:
    created = _loads(tools.worktree_create({"workspace": str(git_repo), "task_id": "c"}))
    Path(created["path"]).joinpath("app.py").write_text("worktree\n", encoding="utf-8")
    (git_repo / "app.py").write_text("host\n", encoding="utf-8")

    payload = _loads(tools.worktree_promote({"worktree_id": created["worktree_id"]}))
    assert payload["ok"] is False
    assert payload["conflicts"][0]["path"] == "app.py"


def test_handlers_never_raise_on_manager_failure(tools: WorktreeTools, monkeypatch, tmp_path) -> None:
    from worktree_sandbox import manager as manager_module

    def boom(*_args, **_kwargs):
        raise RuntimeError("kaboom")

    monkeypatch.chdir(tmp_path)  # a valid session project, so the failure is the only error
    monkeypatch.setattr(manager_module.WorktreeManager, "list_worktrees", boom)
    payload = _loads(tools.worktree_status({}))
    assert payload["ok"] is False
    assert "kaboom" in payload["error"]


def test_ledger_records_events(manager, ledger: Ledger, tools: WorktreeTools, git_repo: Path) -> None:
    created = _loads(tools.worktree_create({"workspace": str(git_repo), "task_id": "evt"}))
    events = ledger.recent_events(created["worktree_id"])
    assert any(e["kind"] == "created" for e in events)
    assert any(e["kind"] == "tool:create" for e in events)
