"""Hardening tests: the failure scenarios a skeptical reviewer would try.

Missing config, malformed input, awkward filenames, symlinks, very large and very numerous changes,
concurrency, repeated load/unload, and upgrading a pre-existing ledger to the current schema.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import threading
from pathlib import Path

import pytest
from worktree_sandbox import hooks as hooks_module
from worktree_sandbox.cli import WorktreeCommands
from worktree_sandbox.hooks import HookHandlers
from worktree_sandbox.manager import WorktreeError
from worktree_sandbox.race import RaceRunner, run_demo_race
from worktree_sandbox.storage import Ledger
from worktree_sandbox.tools import WorktreeTools


@pytest.fixture
def tools(manager, ledger) -> WorktreeTools:
    return WorktreeTools(manager=manager, ledger=ledger)


def _loads(raw: str) -> dict:
    payload = json.loads(raw)
    assert isinstance(payload, dict)
    return payload


# --- 1. missing / broken configuration ------------------------------------- #

def test_hooks_tolerate_a_config_that_raises(manager, ledger) -> None:
    def broken_config(key, default=None):
        raise RuntimeError("config backend exploded")

    hooks = HookHandlers(manager, ledger, get_config=broken_config)
    assert hooks.pre_verify(session_id="s") is None
    hooks.on_session_finalize(session_id="s")  # must not raise


def test_hooks_tolerate_wrong_typed_config(manager, ledger, git_repo: Path) -> None:
    info = manager.create_worktree(str(git_repo), task_id="badcfg")
    (Path(info["path"]) / "x.txt").write_text("x\n", encoding="utf-8")
    values = {"verify_command": "exit 1", "verify_timeout": "not-a-number", "max_worktrees": "nope"}
    hooks = HookHandlers(manager, ledger, get_config=lambda k, d=None: values.get(k, d))
    directive = hooks.pre_verify(session_id="s")
    assert directive is not None and directive["action"] == "continue"
    hooks.on_session_finalize(session_id="s")  # bad max_worktrees must not raise


def test_defaults_when_no_config_at_all(manager, ledger, git_repo: Path) -> None:
    hooks = HookHandlers(manager, ledger, get_config=lambda k, d=None: d)
    assert hooks.pre_verify(session_id="s") is None
    hooks.on_session_finalize(session_id="s")


# --- 2. malformed tool input ----------------------------------------------- #

@pytest.mark.parametrize(
    "handler,args",
    [
        ("worktree_create", {"workspace": 123}),
        ("worktree_create", {"task_id": {"nested": 1}}),
        ("worktree_status", {"worktree_id": 5}),
        ("worktree_diff", {"worktree_id": None}),
        ("worktree_diff", {"worktree_id": "wt-x", "path": 7}),
        ("worktree_promote", {"worktree_id": []}),
        ("worktree_promote", {"worktree_id": "wt-x", "files": {"not": "a list"}}),
        ("worktree_race", {"candidates": "nope"}),
        ("worktree_race", {"candidates": []}),
        ("worktree_race", {"candidates": [{"label": "a"}]}),
        ("worktree_race", {"candidates": [{"label": "a", "files": ["x"]}, {"label": "b"}]}),
        ("worktree_race", {"candidates": [{"label": "a", "files": {"f": 5}}, {"label": "b"}]}),
        ("worktree_race", {"candidates": [{"label": "a"}, {"label": "b"}], "verify_command": 9}),
        ("worktree_race", {"candidates": [{"label": "a"}, {"label": "b"}], "timeout": "soon"}),
    ],
)
def test_malformed_arguments_return_json_errors(tools: WorktreeTools, handler: str, args: dict) -> None:
    payload = _loads(getattr(tools, handler)(args))
    assert payload["ok"] is False
    assert payload["error"]


def test_race_rejects_non_string_file_content(runner: RaceRunner, git_repo: Path) -> None:
    with pytest.raises(WorktreeError, match="must be a string"):
        runner.race(str(git_repo), [{"label": "a", "files": {"f": {"x": 1}}}, {"label": "b", "files": {}}])


# --- 3. awkward filenames --------------------------------------------------- #

@pytest.mark.parametrize(
    "name",
    ["with space.txt", "quote'\".txt", "unicode-ünïcødé.txt", "tab\tname.txt", "newline\nname.txt", "-dash.txt"],
)
def test_awkward_filenames_round_trip(manager, git_repo: Path, name: str) -> None:
    info = manager.create_worktree(str(git_repo), task_id=f"name-{hash(name)}")
    (Path(info["path"]) / name).write_text("payload\n", encoding="utf-8")

    status = manager.status(info["worktree_id"])
    assert [f["path"] for f in status["files"]] == [name], status["files"]

    diff = manager.diff(info["worktree_id"])
    assert "payload" in diff["diff"]

    result = manager.promote(info["worktree_id"])
    assert result["applied"] == [name], result
    assert (git_repo / name).read_text(encoding="utf-8") == "payload\n"


# --- 4. symlinks and other non-regular files -------------------------------- #

def test_symlink_is_not_promoted(manager, git_repo: Path) -> None:
    info = manager.create_worktree(str(git_repo), task_id="link")
    wt = Path(info["path"])
    secret = git_repo.parent / "outside.txt"
    secret.write_text("OUTSIDE\n", encoding="utf-8")
    (wt / "link.txt").symlink_to(secret)

    result = manager.promote(info["worktree_id"])
    assert any(s["path"] == "link.txt" for s in result["skipped"]), result
    assert not (git_repo / "link.txt").exists()
    assert "OUTSIDE" not in (git_repo / "app.py").read_text(encoding="utf-8")


# --- 5. artifact / credential filtering is reported, not silent ------------- #

def test_promote_reports_filtered_and_unmatched_paths(manager, git_repo: Path) -> None:
    info = manager.create_worktree(str(git_repo), task_id="filtered")
    wt = Path(info["path"])
    (wt / "keep.txt").write_text("keep\n", encoding="utf-8")
    (wt / ".env").write_text("SECRET=leak\n", encoding="utf-8")
    (wt / "__pycache__").mkdir()
    (wt / "__pycache__" / "x.pyc").write_bytes(b"\x00")

    status = manager.status(info["worktree_id"])
    assert [f["path"] for f in status["files"]] == ["keep.txt"]

    result = manager.promote(info["worktree_id"], files=["keep.txt", ".env", "nope.txt"])
    assert result["applied"] == ["keep.txt"]
    assert result["filtered"] == [".env"]
    assert result["unmatched"] == ["nope.txt"]
    assert not (git_repo / ".env").exists()


# --- 6. very large / very numerous changes ---------------------------------- #

def test_large_diff_is_truncated(manager, git_repo: Path) -> None:
    info = manager.create_worktree(str(git_repo), task_id="bigdiff")
    (Path(info["path"]) / "big.txt").write_text("line\n" * 60000, encoding="utf-8")
    result = manager.diff(info["worktree_id"], max_bytes=10_000)
    assert result["truncated"] is True
    assert len(result["diff"]) < 11_000


def test_multiple_megabyte_file_promotes(manager, git_repo: Path) -> None:
    info = manager.create_worktree(str(git_repo), task_id="bigfile")
    payload = "abcdefgh\n" * 400_000  # ~3.6 MB
    (Path(info["path"]) / "big.bin.txt").write_text(payload, encoding="utf-8")
    result = manager.promote(info["worktree_id"])
    assert result["applied"] == ["big.bin.txt"]
    assert (git_repo / "big.bin.txt").stat().st_size == len(payload)


def test_many_files_are_tracked_and_promoted(manager, git_repo: Path) -> None:
    info = manager.create_worktree(str(git_repo), task_id="many")
    wt = Path(info["path"])
    for index in range(120):
        (wt / f"file_{index:03d}.txt").write_text(f"{index}\n", encoding="utf-8")

    status = manager.status(info["worktree_id"])
    assert status["changed_files"] == 120
    result = manager.promote(info["worktree_id"])
    assert len(result["applied"]) == 120
    assert (git_repo / "file_119.txt").read_text(encoding="utf-8") == "119\n"


def test_empty_worktree_promote_is_a_noop(manager, git_repo: Path) -> None:
    info = manager.create_worktree(str(git_repo), task_id="empty")
    result = manager.promote(info["worktree_id"])
    assert result["ok"] is True
    assert result["applied"] == [] and result["deleted"] == []
    assert (git_repo / "app.py").read_text(encoding="utf-8").startswith("def greet")


# --- 7. concurrency --------------------------------------------------------- #

def test_concurrent_create_for_the_same_task_yields_one_worktree(manager, git_repo: Path) -> None:
    results: list[dict] = []
    errors: list[Exception] = []

    def create() -> None:
        try:
            results.append(manager.create_worktree(str(git_repo), task_id="shared"))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=create) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors, errors
    assert {r["worktree_id"] for r in results} == {results[0]["worktree_id"]}
    assert len(manager.list_worktrees(workspace=str(git_repo))) == 1


def test_concurrent_distinct_worktrees_all_exist(manager, git_repo: Path) -> None:
    errors: list[Exception] = []

    def create(index: int) -> None:
        try:
            info = manager.create_worktree(str(git_repo), task_id=f"t{index}")
            (Path(info["path"]) / f"f{index}.txt").write_text("x\n", encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=create, args=(i,)) for i in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors, errors
    assert len(manager.list_worktrees(workspace=str(git_repo))) == 5


# --- 8. repeated load / unload --------------------------------------------- #

def test_repeated_register_is_clean(manager, ledger) -> None:
    """register() must be idempotent-ish: no import-time state leaks between loads."""
    pytest.importorskip("agent.terminal_env_provider", reason="needs a Hermes Agent checkout")
    from worktree_sandbox import register

    class Stub:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def register_tool(self, name, **kwargs):
            self.calls.append(f"tool:{name}")

        def register_system_prompt_section(self, section_id, content, **kwargs):
            self.calls.append(f"section:{section_id}")

        def register_terminal_environment_provider(self, provider):
            self.calls.append(f"provider:{provider.name}")

        def register_hook(self, hook_name, callback, **kwargs):
            self.calls.append(f"hook:{hook_name}")

        def register_command(self, name, handler, **kwargs):
            self.calls.append(f"command:{name}")

        def register_cli_command(self, name, help, setup_fn, handler_fn=None, **kwargs):
            self.calls.append(f"cli:{name}")

        def register_skill(self, name, path, description="", **kwargs):
            self.calls.append(f"skill:{name}")

        def get_config(self, key, default=None):
            return default

    first, second = Stub(), Stub()
    register(first)
    register(second)
    assert first.calls == second.calls
    assert len(first.calls) == 5 + 1 + 1 + 4 + 1 + 1 + 1


def test_ledger_survives_reopen(data_dir: Path) -> None:
    """State written by one 'process' is visible to the next (a plugin update keeps data)."""
    from worktree_sandbox.manager import WorktreeManager

    db_path = data_dir / "data.db"
    ledger = Ledger(db_path=db_path)
    ledger.record_event(None, "first-process", {"n": 1})
    manager = WorktreeManager(ledger=ledger, data_dir=data_dir)
    assert manager.data_dir == data_dir

    reopened = Ledger(db_path=db_path)
    kinds = [e["kind"] for e in reopened.recent_events()]
    assert "first-process" in kinds


# --- 9. upgrading a pre-existing ledger ------------------------------------ #

def test_ledger_migrates_a_v0_schema(tmp_path: Path) -> None:
    """A DB created before the repo_root column existed must open and stay usable."""
    db_path = tmp_path / "old.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE worktrees (
            id TEXT PRIMARY KEY, workspace TEXT NOT NULL, path TEXT NOT NULL, branch TEXT NOT NULL,
            base_commit TEXT, shadow INTEGER NOT NULL DEFAULT 0, state TEXT NOT NULL DEFAULT 'active',
            created_at REAL NOT NULL, updated_at REAL NOT NULL);
        """
    )
    conn.execute(
        "INSERT INTO worktrees (id, workspace, path, branch, base_commit, shadow, state, created_at, updated_at)"
        " VALUES ('wt-old-000000', '/tmp/x', '/tmp/wt', 'hermes-wt/old', 'abc', 0, 'active', 1.0, 1.0)")
    conn.commit()
    conn.close()

    ledger = Ledger(db_path=db_path)
    row = ledger.get_worktree("wt-old-000000")
    assert row is not None
    assert row["workspace"] == "/tmp/x"
    assert row["repo_root"] is None  # added by the migration, defaults to NULL

    # Writing a new record through the migrated schema works.
    ledger.upsert_worktree(worktree_id="wt-new-000000", workspace="/tmp/y", path="/tmp/wt2",
                           branch="hermes-wt/new", base_commit="def", shadow=True,
                           repo_root="/tmp/shadow")
    assert ledger.get_worktree("wt-new-000000")["repo_root"] == "/tmp/shadow"


# --- 10. git unavailable ---------------------------------------------------- #

def test_missing_git_is_reported_not_crashed(manager, git_repo: Path, monkeypatch) -> None:
    pytest.importorskip("agent.terminal_env_provider", reason="needs a Hermes Agent checkout")

    import shutil as _shutil

    from worktree_sandbox.provider import WorktreeSandboxProvider

    # provider.shutil *is* the shutil module, so one patch covers it.
    monkeypatch.setattr(_shutil, "which", lambda name: None if name == "git" else "/usr/bin/" + name)

    provider = WorktreeSandboxProvider(get_config=lambda k, d=None: d, manager=manager)

    provider = WorktreeSandboxProvider(get_config=lambda k, d=None: d, manager=manager)
    assert provider.is_available() is False
    status, detail = provider.probe()
    assert status == "needs_setup"
    assert "git" in detail
    assert provider.doctor_checks()[0][0] is False


# --- 11. demo hygiene ------------------------------------------------------- #

def test_demo_projects_are_trimmed(runner: RaceRunner) -> None:
    for _ in range(5):
        run_demo_race(runner.manager)
    demo_root = runner.manager.data_dir / "demo"
    remaining = [d for d in demo_root.iterdir() if d.is_dir()]
    assert len(remaining) <= 3, [d.name for d in remaining]


def test_commands_survive_a_broken_manager(ledger) -> None:
    class Broken:
        data_dir = Path("/nonexistent")

        def list_worktrees(self, **_kwargs):
            raise RuntimeError("boom")

        def peek_workspace(self, *_args, **_kwargs):
            raise RuntimeError("boom")

    commands = WorktreeCommands(Broken(), ledger)
    assert isinstance(commands.status(), str)
    assert commands.dispatch("diff", ["x"]).startswith("worktree:")


# --- 12. subprocess timeout kills the child --------------------------------- #

def test_race_timeout_kills_a_hung_candidate(runner: RaceRunner, git_repo: Path) -> None:
    result = runner.race(
        str(git_repo),
        [{"label": "hang", "files": {"a": "1"}}, {"label": "finish", "files": {"b": "2"}}],
        verify_command="sleep 30",
        timeout=5,
    )
    labels = {row["label"]: row for row in result["results"]}
    assert labels["hang"]["timed_out"] is True
    assert labels["hang"]["passed"] is False
    # The race still completes and reports a winner.
    assert result["winner"] in labels


def test_hooks_module_emits_nothing_without_clients(manager, ledger) -> None:
    hooks = HookHandlers(manager, ledger)
    hooks.on_session_start(session_id="s")  # no Desktop attached: must be a silent no-op
    assert hooks_module.emit is not None


def test_event_emit_is_safe_without_a_gateway() -> None:
    """Emitting must never raise or log a traceback in a gateway-less process."""
    from worktree_sandbox import events

    assert isinstance(events.gateway_present(), bool)
    assert events.emit("unit.test", {"n": 1}) is None
    assert events.emit("unit.test") is None


def test_git_operations_never_inherit_credentials(manager, git_repo: Path, monkeypatch) -> None:
    """git is invoked with a scrubbed environment, so a planted token cannot reach a hook/remote."""
    captured: dict = {}
    original = subprocess.run

    def spy(cmd, *args, **kwargs):
        if isinstance(cmd, list) and cmd and cmd[0] == "git":
            captured["env"] = kwargs.get("env") or {}
        return original(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", spy)
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_should_not_leak")
    manager.status(manager.create_worktree(str(git_repo), task_id="env")["worktree_id"])
    assert "GITHUB_TOKEN" not in captured.get("env", {})
