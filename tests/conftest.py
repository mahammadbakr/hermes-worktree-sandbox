"""Shared pytest fixtures."""

from __future__ import annotations

import os
import sqlite3
import subprocess
from pathlib import Path

import pytest
from helpers import PLUGIN_DIR, require_git  # noqa: F401  (re-exported for test modules)

__all__ = ["PLUGIN_DIR"]


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args], cwd=str(repo), check=True, capture_output=True,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_AUTHOR_NAME": "Test",
             "GIT_AUTHOR_EMAIL": "test@example.com", "GIT_COMMITTER_NAME": "Test",
             "GIT_COMMITTER_EMAIL": "test@example.com"},
    )


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    path = tmp_path / "plugin-data"
    path.mkdir(parents=True, exist_ok=True)
    return path


@pytest.fixture
def ledger():
    from worktree_sandbox.storage import Ledger

    return Ledger(connection=sqlite3.connect(":memory:", check_same_thread=False))


@pytest.fixture
def manager(data_dir: Path, ledger):
    from worktree_sandbox.manager import WorktreeManager

    return WorktreeManager(ledger=ledger, data_dir=data_dir)


@pytest.fixture
def runner(manager):
    from worktree_sandbox.race import RaceRunner

    return RaceRunner(manager)


@pytest.fixture
def git_repo(tmp_path: Path, monkeypatch) -> Path:
    """A throwaway repo, with the process cwd inside it.

    The tool handlers refuse a `workspace` outside the session's project, so tests stand in the
    project the way a real session does.
    """
    require_git()
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "app.py").write_text("def greet():\n    return 'hi'\n", encoding="utf-8")
    (repo / "README.md").write_text("# Demo\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "init")
    monkeypatch.chdir(repo)
    return repo
