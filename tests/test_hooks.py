"""Tests for the lifecycle hooks (throttling, verification gate, teardown pruning)."""

from __future__ import annotations

from pathlib import Path

import pytest
from worktree_sandbox import hooks as hooks_module
from worktree_sandbox.hooks import HookHandlers


@pytest.fixture
def emitted(monkeypatch) -> list[tuple[str, dict]]:
    sink: list[tuple[str, dict]] = []
    monkeypatch.setattr(hooks_module, "emit", lambda event, payload=None: sink.append((event, payload or {})))
    return sink


def _make_hooks(manager, ledger, config: dict | None = None) -> HookHandlers:
    values = config or {}
    return HookHandlers(manager, ledger, get_config=lambda key, default=None: values.get(key, default))


def test_session_start_records_and_emits(manager, ledger, emitted) -> None:
    hooks = _make_hooks(manager, ledger)
    hooks.on_session_start(session_id="s1", model="m", platform="cli")
    assert any(event == "session.started" for event, _ in emitted)
    assert any(e["kind"] == "session.start" for e in ledger.recent_events())


def test_post_tool_call_refreshes_stats(manager, ledger, emitted, git_repo: Path) -> None:
    info = manager.create_worktree(str(git_repo), task_id="t1")
    (Path(info["path"]) / "new.txt").write_text("x\n", encoding="utf-8")
    hooks = _make_hooks(manager, ledger)
    hooks.on_worktree_created("t1", info["worktree_id"])
    emitted.clear()

    hooks.post_tool_call(tool_name="write_file", task_id="t1")
    updates = [p for e, p in emitted if e == "updated"]
    assert updates and updates[0]["worktree_id"] == info["worktree_id"]
    assert updates[0]["changed_files"] == 1


def test_post_tool_call_ignores_non_mutating_tools(manager, ledger, emitted, git_repo: Path) -> None:
    info = manager.create_worktree(str(git_repo), task_id="t2")
    hooks = _make_hooks(manager, ledger)
    hooks.on_worktree_created("t2", info["worktree_id"])
    emitted.clear()
    hooks.post_tool_call(tool_name="read_file", task_id="t2")
    assert emitted == []


def test_post_tool_call_is_throttled(manager, ledger, emitted, git_repo: Path, monkeypatch) -> None:
    info = manager.create_worktree(str(git_repo), task_id="t3")
    hooks = _make_hooks(manager, ledger)
    hooks.on_worktree_created("t3", info["worktree_id"])

    calls = {"n": 0}
    original = type(manager).status

    def counting_status(self, worktree_id):
        calls["n"] += 1
        return original(self, worktree_id)

    monkeypatch.setattr(type(manager), "status", counting_status)
    for _ in range(4):
        hooks.post_tool_call(tool_name="terminal", task_id="t3")
    assert calls["n"] == 1


def test_post_tool_call_unknown_task_is_noop(manager, ledger, emitted) -> None:
    hooks = _make_hooks(manager, ledger)
    hooks.post_tool_call(tool_name="terminal", task_id="nope")
    assert emitted == []


def test_pre_verify_noop_without_config(manager, ledger, emitted, git_repo: Path) -> None:
    info = manager.create_worktree(str(git_repo), task_id="v1")
    (Path(info["path"]) / "x.txt").write_text("x\n", encoding="utf-8")
    hooks = _make_hooks(manager, ledger)
    assert hooks.pre_verify(session_id="s1") is None


def test_pre_verify_passes_when_command_succeeds(manager, ledger, emitted, git_repo: Path) -> None:
    info = manager.create_worktree(str(git_repo), task_id="v2")
    (Path(info["path"]) / "x.txt").write_text("x\n", encoding="utf-8")
    hooks = _make_hooks(manager, ledger, {"verify_command": "true"})
    assert hooks.pre_verify(session_id="s2") is None
    assert any(e == "verified" for e, _ in emitted)


def test_pre_verify_returns_continue_when_command_fails(manager, ledger, emitted, git_repo: Path) -> None:
    info = manager.create_worktree(str(git_repo), task_id="v3")
    (Path(info["path"]) / "x.txt").write_text("x\n", encoding="utf-8")
    hooks = _make_hooks(manager, ledger, {"verify_command": "exit 3"})
    directive = hooks.pre_verify(session_id="s3")
    assert isinstance(directive, dict)
    assert directive["action"] == "continue"
    assert "exit code 3" in directive["message"]


def test_pre_verify_runs_once_per_session(manager, ledger, emitted, git_repo: Path) -> None:
    info = manager.create_worktree(str(git_repo), task_id="v4")
    (Path(info["path"]) / "x.txt").write_text("x\n", encoding="utf-8")
    hooks = _make_hooks(manager, ledger, {"verify_command": "exit 1"})
    assert hooks.pre_verify(session_id="s4") is not None
    assert hooks.pre_verify(session_id="s4") is None  # only one nudge per session


def test_pre_verify_ignores_clean_worktrees(manager, ledger, emitted, git_repo: Path) -> None:
    manager.create_worktree(str(git_repo), task_id="v5")
    hooks = _make_hooks(manager, ledger, {"verify_command": "exit 1"})
    assert hooks.pre_verify(session_id="s5") is None


def test_session_finalize_prunes_beyond_limit(manager, ledger, emitted, git_repo: Path) -> None:
    import time

    for i in range(3):
        manager.create_worktree(str(git_repo), task_id=f"f{i}")
        time.sleep(0.01)
    hooks = _make_hooks(manager, ledger, {"max_worktrees": 1, "keep_on_exit": True})
    hooks.on_session_finalize(session_id="s6")
    assert len(manager.list_worktrees(workspace=str(git_repo))) <= 1


def test_session_finalize_discards_clean_when_not_keeping(manager, ledger, emitted, git_repo: Path) -> None:
    manager.create_worktree(str(git_repo), task_id="nokeep")
    hooks = _make_hooks(manager, ledger, {"keep_on_exit": False})
    hooks.on_session_finalize(session_id="s7")
    assert manager.list_worktrees(workspace=str(git_repo)) == []


def test_hooks_never_raise_on_broken_manager(ledger) -> None:
    class Broken:
        data_dir = Path("/nonexistent")

        def list_worktrees(self, **_kwargs):
            raise RuntimeError("boom")

        def prune(self, *_args, **_kwargs):
            raise RuntimeError("boom")

    hooks = HookHandlers(Broken(), ledger)
    hooks.on_session_finalize(session_id="x")  # must not raise
    hooks.post_tool_call(tool_name="terminal", task_id="x")
    assert hooks.pre_verify(session_id="x") is None
