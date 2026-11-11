"""Tests for ``WorktreeSandboxProvider`` / ``WorktreeEnvironment`` — require a Hermes checkout.

Set ``HERMES_AGENT_REPO=/path/to/hermes-agent`` to enable them.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from helpers import HERMES_AVAILABLE

pytestmark = pytest.mark.skipif(
    not HERMES_AVAILABLE, reason="Hermes Agent checkout not on sys.path (set HERMES_AGENT_REPO)"
)


def _make_provider(manager):
    from worktree_sandbox.provider import WorktreeSandboxProvider

    return WorktreeSandboxProvider(get_config=lambda key, default=None: default, manager=manager)


def test_provider_availability_and_probe(manager) -> None:
    provider = _make_provider(manager)
    assert provider.name == "worktree"
    assert provider.is_available() is True
    status, detail = provider.probe()
    assert status == "ready", detail
    assert provider.is_container is False  # approvals stay on
    assert provider.skip_container_guards is False
    rows = provider.doctor_checks()
    assert any(label == "git" for _ok, label, _detail in rows)


def test_environment_runs_commands_in_worktree(manager, git_repo: Path) -> None:
    provider = _make_provider(manager)
    env = provider.create_environment(cwd=str(git_repo), timeout=30, task_id="env")

    assert env.uses_host_filesystem is False
    assert Path(env.worktree_path) != git_repo
    assert Path(env.cwd).resolve() == Path(env.worktree_path).resolve()

    result = env.execute("pwd")
    assert result["returncode"] == 0
    assert str(Path(env.worktree_path).resolve()) in result["output"]

    # Writing through the environment only touches the worktree.
    env.execute("printf 'env-wrote\\n' > env_file.txt && cat env_file.txt")
    assert (Path(env.worktree_path) / "env_file.txt").read_text().strip() == "env-wrote"
    assert not (git_repo / "env_file.txt").exists()


def test_environment_strips_secret_env(manager, git_repo: Path, monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-not-leak")
    monkeypatch.setenv("MY_CUSTOM_TOKEN", "tok-should-not-leak")
    monkeypatch.setenv("HERMES_SESSION_ID", "sess-secret")
    provider = _make_provider(manager)
    env = provider.create_environment(cwd=str(git_repo), timeout=30, task_id="secrets")

    result = env.execute("env")
    output = result["output"]
    assert "sk-should-not-leak" not in output
    assert "tok-should-not-leak" not in output
    assert "sess-secret" not in output
    # A benign variable survives.
    assert "PATH=" in output


def test_environment_cwd_persists_across_commands(manager, git_repo: Path) -> None:
    provider = _make_provider(manager)
    env = provider.create_environment(cwd=str(git_repo), timeout=30, task_id="cwd")
    wt = Path(env.worktree_path)
    (wt / "sub").mkdir()
    env.execute("cd sub")
    result = env.execute("pwd")
    assert result["output"].strip().endswith("/sub")


def test_environment_remaps_host_cwd_into_worktree(manager, git_repo: Path) -> None:
    """Regression: Hermes's terminal tool passes the session's host cwd on every call."""
    provider = _make_provider(manager)
    env = provider.create_environment(cwd=str(git_repo), timeout=30, task_id="remap")
    result = env.execute("pwd", cwd=str(git_repo))
    shown = Path(result["output"].strip()).resolve()
    assert shown == Path(env.worktree_path).resolve()
    assert shown != git_repo.resolve()


def test_environment_remaps_subdirectory_cwd(manager, git_repo: Path) -> None:
    import subprocess

    sub = git_repo / "pkg"
    sub.mkdir()
    (sub / "mod.py").write_text("X = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=str(git_repo), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "pkg"], cwd=str(git_repo), check=True, capture_output=True)

    provider = _make_provider(manager)
    env = provider.create_environment(cwd=str(git_repo), timeout=30, task_id="remapsub")
    result = env.execute("pwd", cwd=str(sub))
    shown = Path(result["output"].strip()).resolve()
    assert shown.name == "pkg"
    assert str(Path(env.worktree_path).resolve()) in str(shown)


def test_environment_confines_cwd_outside_workspace(manager, git_repo: Path) -> None:
    provider = _make_provider(manager)
    env = provider.create_environment(cwd=str(git_repo), timeout=30, task_id="confine")
    result = env.execute("pwd", cwd="/tmp")
    assert Path(result["output"].strip()).resolve() == Path(env.worktree_path).resolve()


def test_writes_with_host_cwd_stay_off_the_host(manager, git_repo: Path) -> None:
    """The exact failure mode the remap prevents: a write with the host cwd set."""
    provider = _make_provider(manager)
    env = provider.create_environment(cwd=str(git_repo), timeout=30, task_id="hostcwd")
    env.execute("printf 'data\\n' > host_cwd_write.txt", cwd=str(git_repo))
    assert (Path(env.worktree_path) / "host_cwd_write.txt").exists()
    assert not (git_repo / "host_cwd_write.txt").exists()


def test_environment_timeout_is_enforced(manager, git_repo: Path) -> None:
    provider = _make_provider(manager)
    env = provider.create_environment(cwd=str(git_repo), timeout=30, task_id="slow")
    result = env.execute("sleep 5", timeout=1)
    assert result["returncode"] == 124
    assert result.get("hermes_timed_out") is True


def test_environment_handles_stdin(manager, git_repo: Path) -> None:
    provider = _make_provider(manager)
    env = provider.create_environment(cwd=str(git_repo), timeout=30, task_id="stdin")
    result = env.execute("cat", stdin_data="hello stdin\n")
    assert "hello stdin" in result["output"]


def test_environment_maps_subdirectory_cwd(manager, git_repo: Path) -> None:
    sub = git_repo / "pkg"
    sub.mkdir()
    (sub / "mod.py").write_text("X = 1\n", encoding="utf-8")
    import subprocess

    subprocess.run(["git", "add", "-A"], cwd=str(git_repo), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "add pkg"], cwd=str(git_repo), check=True, capture_output=True)

    provider = _make_provider(manager)
    env = provider.create_environment(cwd=str(sub), timeout=30, task_id="sub")
    assert Path(env.cwd).name == "pkg"
    assert str(Path(env.worktree_path)) in env.cwd


def test_create_environment_uses_shadow_repo_for_non_git(manager, tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "main.py").write_text("VALUE = 1\n", encoding="utf-8")
    provider = _make_provider(manager)
    env = provider.create_environment(cwd=str(plain), timeout=30, task_id="shadow")
    assert (Path(env.worktree_path) / "main.py").read_text(encoding="utf-8") == "VALUE = 1\n"
    result = env.execute("printf 'VALUE = 2\\n' > main.py")
    assert result["returncode"] == 0
    assert (plain / "main.py").read_text(encoding="utf-8") == "VALUE = 1\n"


def test_prompt_note_mentions_isolation() -> None:
    from worktree_sandbox.provider import prompt_note

    note = prompt_note()
    assert "worktree" in note.lower()
    assert "not modified" in note.lower() or "untouched" in note.lower()


def test_register_wires_surfaces() -> None:
    """register() should register the provider, a prompt section, the tools, hooks and commands."""
    from worktree_sandbox import register

    recorded = {"tools": [], "sections": [], "providers": [], "hooks": [], "commands": [], "cli": [], "skills": []}

    class Stub:
        def register_tool(self, name, **kwargs):
            recorded["tools"].append(name)

        def register_system_prompt_section(self, section_id, content, **kwargs):
            recorded["sections"].append(section_id)

        def register_terminal_environment_provider(self, provider):
            recorded["providers"].append(provider.name)

        def register_hook(self, hook_name, callback, **kwargs):
            recorded["hooks"].append(hook_name)

        def register_command(self, name, handler, **kwargs):
            recorded["commands"].append(name)

        def register_cli_command(self, name, help, setup_fn, handler_fn=None, **kwargs):
            recorded["cli"].append(name)

        def register_skill(self, name, path, description="", **kwargs):
            recorded["skills"].append(name)

        def get_config(self, key, default=None):
            return default

    register(Stub())
    assert set(recorded["tools"]) == {
        "worktree_create", "worktree_status", "worktree_diff", "worktree_promote", "worktree_race",
    }
    assert recorded["sections"] == ["worktree-sandbox"]
    assert recorded["providers"] == ["worktree"]
    assert set(recorded["hooks"]) == {
        "on_session_start", "post_tool_call", "pre_verify", "on_session_finalize",
    }
    assert recorded["commands"] == ["sandbox"]
    assert recorded["cli"] == ["sandbox"]
    assert recorded["skills"] == ["worktree-sandbox"]


@pytest.mark.skipif(os.environ.get("CI") == "true", reason="writes to the real HERMES_HOME")
def test_unified_file_tools_route_through_environment(manager, git_repo: Path) -> None:
    """A file written by the agent's write_file lands in the worktree, not the checkout."""
    import subprocess

    provider = _make_provider(manager)
    env = provider.create_environment(cwd=str(git_repo), timeout=30, task_id="ftools")
    # Simulate what write_file does: it executes inside the environment.
    env.execute("mkdir -p generated && printf 'data\\n' > generated/out.txt")
    assert (Path(env.worktree_path) / "generated" / "out.txt").exists()
    assert not (git_repo / "generated").exists()
    status = subprocess.run(["git", "status", "--porcelain"], cwd=str(git_repo), capture_output=True, text=True)
    assert status.stdout.strip() == ""
