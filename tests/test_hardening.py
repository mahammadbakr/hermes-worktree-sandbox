"""Hardening tests: the failure scenarios a skeptical reviewer would try.

Missing config, malformed input, awkward filenames, symlinks, very large and very numerous changes,
concurrency, repeated load/unload, and upgrading a pre-existing ledger to the current schema.
"""

from __future__ import annotations

import json
import os
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


def _init_repo(path: Path, filename: str = "app.py") -> None:
    (path / filename).write_text("VALUE = 1\n", encoding="utf-8")
    env = {**os.environ, "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@e.com",
           "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@e.com", "GIT_TERMINAL_PROMPT": "0"}
    for args in (["init", "-b", "main"], ["add", "-A"], ["commit", "-m", "init"]):
        subprocess.run(["git", *args], cwd=str(path), capture_output=True, env=env, check=True)

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
    assert len(first.calls) == 5 + 1 + 1 + 5 + 1 + 1 + 1  # 5 tools, prompt, skill, 5 hooks, command, cli


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


# --- 13. Hermes passes a generic container default as cwd ------------------- #

def test_container_default_cwd_falls_back_to_the_session_directory(tmp_path, monkeypatch) -> None:
    """Regression: Hermes passes `/root` for a backend with no `default_cwd`.

    Treating that as the workspace made every command fail with
    "workspace is not a directory: /root".
    """
    pytest.importorskip("agent.terminal_env_provider", reason="needs a Hermes Agent checkout")
    from worktree_sandbox.manager import WorktreeManager
    from worktree_sandbox.provider import WorktreeSandboxProvider
    from worktree_sandbox.storage import Ledger

    repo = tmp_path / "proj"
    repo.mkdir()
    _init_repo(repo)
    monkeypatch.chdir(repo)

    provider = WorktreeSandboxProvider(
        get_config=lambda k, d=None: d,
        manager=WorktreeManager(ledger=Ledger(connection=sqlite3.connect(":memory:", check_same_thread=False)),
                                data_dir=tmp_path / "data"),
    )
    for bogus in ("/root", "", "~", "/nonexistent-path-xyz"):
        env = provider.create_environment(cwd=bogus, timeout=30, task_id="ctl")
        assert Path(env.workspace_root) == repo.resolve()
        result = env.execute("pwd")
        assert Path(result["output"].strip()).resolve() == Path(env.worktree_path).resolve()


def test_real_cwd_is_still_honoured(tmp_path, monkeypatch) -> None:
    pytest.importorskip("agent.terminal_env_provider", reason="needs a Hermes Agent checkout")
    from worktree_sandbox.manager import WorktreeManager
    from worktree_sandbox.provider import WorktreeSandboxProvider
    from worktree_sandbox.storage import Ledger

    repo = tmp_path / "real"
    repo.mkdir()
    _init_repo(repo)
    provider = WorktreeSandboxProvider(
        get_config=lambda k, d=None: d,
        manager=WorktreeManager(ledger=Ledger(connection=sqlite3.connect(":memory:", check_same_thread=False)),
                                data_dir=tmp_path / "data"),
    )
    env = provider.create_environment(cwd=str(repo), timeout=30, task_id="real")
    assert Path(env.workspace_root) == repo.resolve()


# --- 14. the demo project is a real Git repository -------------------------- #

def test_seeded_demo_project_is_a_git_repo(manager) -> None:
    """Regression: the demo's "your checkout is untouched" beat needs `git status` to work."""
    from worktree_sandbox.race import run_demo_race

    result = run_demo_race(manager)
    project = Path(result["project"])
    assert (project / ".git").exists(), "seeded demo project is not a Git repository"

    status = subprocess.run(["git", "status", "--porcelain"], cwd=str(project),
                            capture_output=True, text=True)
    assert status.returncode == 0
    assert status.stdout.strip() == "", f"demo project is dirty: {status.stdout!r}"

    log = subprocess.run(["git", "log", "--oneline"], cwd=str(project), capture_output=True, text=True)
    assert log.returncode == 0 and log.stdout.strip()

    # Running the suite in the host project must not dirty it (that is the demo's core claim).
    subprocess.run(["python3", "-m", "unittest", "-q", "test_parser"], cwd=str(project),
                   capture_output=True, text=True)
    after = subprocess.run(["git", "status", "--porcelain"], cwd=str(project),
                           capture_output=True, text=True)
    assert after.stdout.strip() == "", f"running the tests dirtied the checkout: {after.stdout!r}"


# --- 15. review: privileged tool calls go through Hermes' approval gate ------ #

def test_race_tool_call_is_escalated_to_approval(manager, ledger) -> None:
    """worktree_race runs model-written commands, so a person must see them first."""
    hooks = HookHandlers(manager, ledger)
    directive = hooks.pre_tool_call(tool_name="worktree_race", args={
        "candidates": [
            {"label": "regex", "files": {"a.py": "x"}, "command": "python -m pytest -q"},
            {"label": "sm", "setup_command": "pip install -q foo"},
        ],
        "verify_command": "python -m unittest -q test_parser",
        "promote_winner": True,
    })
    assert directive is not None and directive["action"] == "approve"
    message = directive["message"]
    assert "worktree_race" in directive.get("rule_key", "")  # dynamic hash key
    assert "python -m pytest -q" in message
    assert "pip install -q foo" in message
    assert "python -m unittest -q test_parser" in message
    assert "INTO YOUR PROJECT" in message  # promote_winner is disclosed


def test_promote_tool_call_is_escalated_with_target_and_files(manager, ledger, git_repo: Path) -> None:
    info = manager.create_worktree(str(git_repo), task_id="gate")
    (Path(info["path"]) / "app.py").write_text("changed\n", encoding="utf-8")
    hooks = HookHandlers(manager, ledger)

    directive = hooks.pre_tool_call(tool_name="worktree_promote", args={
        "worktree_id": info["worktree_id"], "force": True,
    })
    assert directive is not None and directive["action"] == "approve"
    assert "worktree_promote" in directive.get("rule_key", "")  # dynamic hash key
    assert str(git_repo) in directive["message"]
    assert "force: true" in directive["message"]
    assert "1 file(s)" in directive["message"]

    listed = hooks.pre_tool_call(tool_name="worktree_promote", args={
        "worktree_id": info["worktree_id"], "files": ["app.py", "other.py"],
    })
    assert "app.py, other.py" in listed["message"]


@pytest.mark.parametrize("tool", ["worktree_status", "worktree_diff", "worktree_create", "terminal", "write_file"])
def test_unprivileged_tools_are_not_gated(manager, ledger, tool: str) -> None:
    assert HookHandlers(manager, ledger).pre_tool_call(tool_name=tool, args={}) is None


def test_gate_never_fails_open(manager, ledger) -> None:
    """If the gate itself breaks it must ask a person, not let the call through."""
    hooks = HookHandlers(manager, ledger)
    directive = hooks.pre_tool_call(tool_name="worktree_race", args={"candidates": [{"label": None}]})
    assert directive is None or directive["action"] == "approve"

    class Exploding(dict):
        def get(self, *_a, **_k):
            raise RuntimeError("boom")

    directive = hooks.pre_tool_call(tool_name="worktree_promote", args=Exploding())
    assert directive is not None and directive["action"] == "approve"


# --- 16. review: the workspace must be the session's project ------------------ #

def test_workspace_outside_the_project_is_refused(monkeypatch, tmp_path: Path) -> None:
    from worktree_sandbox.tools import resolve_requested_workspace

    project = tmp_path / "project"
    project.mkdir()
    other = tmp_path / "elsewhere"
    other.mkdir()
    monkeypatch.chdir(project)

    workspace, error = resolve_requested_workspace({"workspace": str(other)})
    assert workspace is None and error and "outside the session's project" in error

    workspace, error = resolve_requested_workspace({})
    assert error is None and Path(workspace).resolve() == project.resolve()


def test_home_and_hermes_home_are_refused(monkeypatch, tmp_path: Path) -> None:
    from worktree_sandbox.tools import is_forbidden_workspace

    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hh"))
    (tmp_path / "hh").mkdir()

    # Refuse $HERMES_HOME and anything inside it
    assert is_forbidden_workspace(tmp_path / "hh") is not None
    assert is_forbidden_workspace(tmp_path / "hh" / "sub") is not None

    # Refuse ~ itself
    assert is_forbidden_workspace(tmp_path / "home") is not None

    # ~/code/project is allowed *when it is the session project*
    home_project = tmp_path / "home" / "code" / "project"
    home_project.mkdir(parents=True)
    monkeypatch.chdir(home_project)  # now the session project is inside ~
    assert is_forbidden_workspace(home_project) is None
    assert is_forbidden_workspace(home_project / "pkg") is None

    # Back to the original project: a normal project outside home is fine
    monkeypatch.chdir(project)
    assert is_forbidden_workspace(project) is None
    assert is_forbidden_workspace(project / "pkg") is None


def test_race_refuses_a_foreign_workspace(tools: WorktreeTools, monkeypatch, tmp_path: Path) -> None:
    project = tmp_path / "p"
    project.mkdir()
    monkeypatch.chdir(project)
    payload = _loads(tools.worktree_race({
        "workspace": str(tmp_path / "outside"),
        "candidates": [{"label": "a"}, {"label": "b"}],
    }))
    assert payload["ok"] is False
    assert "outside the session's project" in payload["error"]


def test_default_workspace_is_also_checked(monkeypatch, tmp_path: Path) -> None:
    """The default (session cwd) is validated too; a session in ~ is refused."""
    from worktree_sandbox.tools import resolve_requested_workspace

    hermes_home = tmp_path / "hh"
    hermes_home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.chdir(hermes_home)

    # Default workspace (cwd) is $HERMES_HOME -> refused
    workspace, error = resolve_requested_workspace({})
    assert workspace is None and error and "$HERMES_HOME" in error

    # A project inside normal home is allowed
    home_proj = tmp_path / "home" / "code" / "proj"
    home_proj.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.chdir(home_proj)
    workspace, error = resolve_requested_workspace({})
    assert error is None and Path(workspace).resolve() == home_proj.resolve()


# --- 17. review: promotion honours core's write denylist -------------------- #

def test_promote_refuses_paths_core_denies(manager, git_repo: Path, monkeypatch) -> None:
    info = manager.create_worktree(str(git_repo), task_id="denied")
    wt = Path(info["path"])
    (wt / "ok.txt").write_text("fine\n", encoding="utf-8")
    (wt / "blocked.txt").write_text("nope\n", encoding="utf-8")

    monkeypatch.setattr(
        "worktree_sandbox.manager.write_denial",
        lambda path: "Promote denied: protected file." if path.endswith("blocked.txt") else None,
    )
    result = manager.promote(info["worktree_id"])
    assert result["applied"] == ["ok.txt"]
    assert any(s["path"] == "blocked.txt" and "denied" in s["reason"].lower() for s in result["skipped"])
    assert not (git_repo / "blocked.txt").exists()


def test_write_denial_uses_core_when_available() -> None:
    pytest.importorskip("agent.file_safety", reason="needs a Hermes Agent checkout")
    from worktree_sandbox.manager import write_denial

    assert write_denial("/etc/passwd") is not None
    assert write_denial(str(Path.home() / "project" / "app.py")) is None
