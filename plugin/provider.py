"""``terminal.backend: worktree`` — commands run inside an isolated Git worktree.

``WorktreeSandboxProvider`` implements ``agent.terminal_env_provider.TerminalEnvironmentProvider``
and hands Hermes a ``WorktreeEnvironment`` (a ``tools.environments.base.BaseEnvironment`` subclass
with ``uses_host_filesystem = False``). Because the file tools route through the environment's
``execute()``, ``read_file`` / ``write_file`` / ``patch`` / ``search_files`` and ``terminal`` /
``execute_code`` all operate on the worktree's files, never the main checkout.

Precision on what this is: **working-tree isolation**, not an OS sandbox. The worktree is a real
directory on this host, so a command can still read other absolute paths; what it cannot do is
mutate the user's checkout, and what we strip is the inherited credential environment plus
Hermes's per-turn session identity. ``bubblewrap`` (Linux) is the plugin for kernel-level sandboxing.
"""

from __future__ import annotations

import logging
import os
import shutil
import threading
from pathlib import Path
from typing import Any

from agent.terminal_env_provider import TerminalEnvironmentProvider
from tools.environments.base import BaseEnvironment

from .manager import WorktreeError, WorktreeManager
from .security import SECRET_ENV_EXACT, sanitize_env

logger = logging.getLogger(__name__)

BACKEND_NAME = "worktree"


def _which_bash() -> str:
    return shutil.which("bash") or "/bin/bash"


def _pipe_stdin(proc: Any, data: str) -> None:
    """Write *data* to ``proc.stdin`` on a daemon thread (mirrors Hermes's own helper).

    The base class joins ``proc._hermes_stdin_thread`` and reads ``proc._hermes_stdin_errors``
    after the process exits, so we set both.
    """
    errors: list[str] = []

    def _write() -> None:
        try:
            if proc.stdin is not None:
                proc.stdin.write(data)
                proc.stdin.close()
        except Exception as exc:  # BrokenPipeError when the child never reads
            errors.append(str(exc))

    proc._hermes_stdin_errors = errors
    thread = threading.Thread(target=_write, daemon=True)
    proc._hermes_stdin_thread = thread
    thread.start()


class WorktreeEnvironment(BaseEnvironment):
    """Runs every command with cwd pinned to an isolated Git worktree and a scrubbed environment."""

    # Route Hermes's file tools through execute() so they see the worktree, not the host.
    uses_host_filesystem = False
    # Not the local host backend: keep host-specific hints/paths out of the agent's context.
    is_local = False

    def __init__(
        self, *, worktree_id: str, worktree_path: str, workspace_root: str,
        scratch_dir: str, cwd: str, timeout: int, env: dict | None = None,
    ) -> None:
        self.worktree_id = worktree_id
        self.worktree_path = worktree_path
        self.workspace_root = workspace_root
        self.scratch_dir = scratch_dir
        super().__init__(cwd=cwd, timeout=timeout, env=env or {})
        # Capture a snapshot of the scrubbed environment once; later commands source it.
        self.init_session()

    # -- environment -------------------------------------------------------------

    def get_temp_dir(self) -> str:
        return self.scratch_dir

    def _runtime_env(self) -> dict[str, str]:
        env = sanitize_env(os.environ)
        env["TMPDIR"] = self.scratch_dir
        env["PWD"] = self.worktree_path
        env["HERMES_WORKTREE_ID"] = self.worktree_id
        env["HERMES_WORKTREE_ROOT"] = self.worktree_path
        env["HERMES_WORKSPACE_ROOT"] = self.workspace_root
        env.setdefault("GIT_PAGER", "cat")
        env.setdefault("PAGER", "cat")
        env.setdefault("TERM", "dumb")
        return env

    # -- cwd confinement ---------------------------------------------------------

    def _remap_cwd(self, cwd: str) -> str:
        """Translate a *host* cwd under the workspace into the equivalent worktree path.

        Hermes's terminal tool tracks the session/terminal cwd and passes it to
        ``execute(cwd=...)`` on every call, so without this a command would silently run in
        the user's real checkout (with our scrubbed env) and the isolation would be a lie.
        A cwd outside the workspace is confined to the worktree root — never followed out.
        """
        if not cwd or not isinstance(cwd, str):
            # Empty cwd: let the base class use its tracked cwd (which lives in the worktree).
            return ""
        try:
            target = Path(cwd).expanduser()
            resolved = target.resolve()
        except (OSError, RuntimeError):
            return self.worktree_path
        try:
            worktree = Path(self.worktree_path).resolve()
            workspace = Path(self.workspace_root).resolve()
        except (OSError, RuntimeError):
            return self.worktree_path
        if resolved == worktree or worktree in resolved.parents:
            return str(resolved)
        try:
            rel = resolved.relative_to(workspace)
        except ValueError:
            return self.worktree_path  # outside the workspace: confine, never escape
        mapped = worktree / rel
        return str(mapped) if mapped.is_dir() else self.worktree_path

    def execute(self, command: str, cwd: str = "", **kwargs):
        """Run *command* in the worktree, remapping the caller's host cwd first."""
        return super().execute(command, cwd=self._remap_cwd(cwd), **kwargs)

    # -- subprocess --------------------------------------------------------------

    def _run_bash(self, cmd_string: str, *, login: bool = False, timeout: int = 120,
                  stdin_data: str | None = None):
        """Spawn ``bash -c`` in the worktree.

        ``login`` is intentionally ignored: a login shell would source the user's rc files and
        could re-introduce credentials the user exported there, defeating the scrub. ``login``
        is already applied by the caller for its own reasons and we keep the flag for signature
        compatibility. ``bash -c`` with no ``BASH_ENV`` sources nothing.
        """
        import subprocess

        argv = [_which_bash(), "-c", cmd_string]
        proc = subprocess.Popen(
            argv,
            text=True,
            env=self._runtime_env(),
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.PIPE if stdin_data is not None else subprocess.DEVNULL,
            start_new_session=True,
            cwd=self.worktree_path,
        )
        try:
            proc._hermes_pgid = os.getpgid(proc.pid)
        except OSError:
            proc._hermes_pgid = None
        if stdin_data is not None:
            _pipe_stdin(proc, stdin_data)
        return proc

    def _kill_process(self, proc) -> None:
        """Terminate the whole process group so a stray build/server cannot outlive the command."""
        pgid = getattr(proc, "_hermes_pgid", None)
        if pgid:
            try:
                import signal

                os.killpg(pgid, signal.SIGTERM)
                return
            except OSError:
                pass
        try:
            proc.kill()
        except OSError:
            pass

    def _force_kill_process(self, proc) -> None:
        pgid = getattr(proc, "_hermes_pgid", None)
        if pgid:
            try:
                import signal

                os.killpg(pgid, signal.SIGKILL)
                return
            except OSError:
                pass
        try:
            proc.kill()
        except OSError:
            pass

    def cleanup(self) -> None:
        """Nothing to tear down: the worktree persists for promotion. ``__del__`` calls this."""
        return None


class WorktreeSandboxProvider(TerminalEnvironmentProvider):
    """``terminal.backend: worktree`` — each task gets its own transactional Git worktree."""

    name = BACKEND_NAME
    display_name = "Worktree Sandbox"

    # Commands run on this host; the worktree is a real directory, so keep host context but
    # keep the dangerous-command approval gate ON (is_container=False -> skip_container_guards False).
    is_remote = False
    is_container = False
    session_isolated_when_nonpersistent = True

    def __init__(self, get_config: Any | None = None, manager: WorktreeManager | None = None) -> None:
        self._get_config = get_config
        self._manager = manager or WorktreeManager()

    @property
    def manager(self) -> WorktreeManager:
        return self._manager

    @property
    def description(self) -> str:
        return "Run commands in an isolated Git worktree, leaving your checkout untouched until you promote."

    @property
    def env_description(self) -> str:
        return "an isolated Git worktree on this machine"

    @property
    def strip_env_keys(self) -> frozenset:
        # Cooperative hint to core's subprocess env cleanup; our own scrub is the real guard.
        return frozenset(SECRET_ENV_EXACT)

    def is_available(self) -> bool:
        """Cheap, offline: is git installed and is the platform supported?"""
        import sys

        if not (sys.platform.startswith("linux") or sys.platform == "darwin"):
            return False
        return shutil.which("git") is not None and shutil.which("bash") is not None

    def check_requirements(self, config: dict[str, Any]) -> bool:
        if not self.is_available():
            logger.error(
                "worktree backend unavailable: needs `git` and `bash` on PATH on macOS or Linux")
            return False
        return True

    def probe(self) -> tuple[str, str]:
        import sys

        if not (sys.platform.startswith("linux") or sys.platform == "darwin"):
            return ("unavailable", "The worktree backend supports macOS and Linux.")
        if shutil.which("git") is None:
            return ("needs_setup", "git was not found on PATH. Install Git (xcode-select --install, or apt install git).")
        if shutil.which("bash") is None:
            return ("needs_setup", "bash was not found on PATH.")
        return ("ready", "")

    def doctor_checks(self) -> list[tuple[bool, str, str]]:
        rows: list[tuple[bool, str, str]] = []
        git = shutil.which("git")
        rows.append((bool(git), "git", f"({git})" if git else "(not found on PATH)"))
        bash = shutil.which("bash")
        rows.append((bool(bash), "bash", f"({bash})" if bash else "(not found on PATH)"))
        try:
            data_dir = str(self._manager.data_dir)
            rows.append((True, "plugin data dir", f"({data_dir})"))
        except Exception as exc:  # pragma: no cover - defensive
            rows.append((False, "plugin data dir", f"(unavailable: {exc})"))
        return rows

    def setup_instructions(self) -> list[str]:
        return [
            "Worktree Sandbox runs every command and file edit in an isolated Git worktree.",
            "Select it for a project with: hermes config set terminal.backend worktree",
            "Your main checkout is untouched until you promote a worktree:",
            "  /worktree status      — list worktrees and their diff stats",
            "  /worktree promote <id> — apply a worktree's changes back to your checkout",
        ]

    def create_environment(
        self, *, cwd: str, timeout: int, task_id: str = "default", image: str | None = None,
        container_config: dict[str, Any] | None = None, **kwargs: Any,
    ) -> WorktreeEnvironment:
        requested = (cwd or "").strip()
        if requested in ("", "~"):
            requested = os.getcwd()
        try:
            info = self._manager.get_or_create(requested, task_id=task_id)
        except WorktreeError as exc:
            # A clear, actionable message; Hermes surfaces it as a degraded result and retries
            # rather than crashing the turn.
            raise WorktreeError(f"worktree backend could not start: {exc}") from exc

        worktree_path = Path(info["path"])
        if not worktree_path.is_dir():
            raise WorktreeError(f"worktree directory disappeared: {worktree_path}")

        # Map the requested cwd into the worktree (subdirectory when possible).
        start = str(worktree_path)
        try:
            repo_root = Path(info["workspace"])
            rel = Path(requested).resolve().relative_to(repo_root)
            candidate = worktree_path / rel
            if candidate.is_dir():
                start = str(candidate)
        except (ValueError, OSError):
            start = str(worktree_path)

        scratch = self._manager.scratch_root / info["worktree_id"]
        scratch.mkdir(parents=True, exist_ok=True)

        return WorktreeEnvironment(
            worktree_id=info["worktree_id"],
            worktree_path=str(worktree_path),
            workspace_root=str(info["workspace"]),
            scratch_dir=str(scratch),
            cwd=start,
            timeout=timeout,
        )


def prompt_note(session_info: Any = None) -> str:
    """System-prompt section explaining the working tree boundary (registered by the plugin)."""
    return (
        "Terminal backend: **worktree sandbox**. Your `terminal` and `execute_code` commands, and the "
        "`read_file` / `write_file` / `patch` / `search_files` file tools, operate inside an isolated Git "
        "worktree — the user's main checkout is NOT modified. The plugin's `worktree_status`, `worktree_diff` "
        "and `worktree_promote` tools inspect and apply those changes. Report changes you make as pending in "
        "the worktree, and tell the user their project files are unchanged until they promote."
    )


__all__ = ["WorktreeSandboxProvider", "WorktreeEnvironment", "prompt_note"]
