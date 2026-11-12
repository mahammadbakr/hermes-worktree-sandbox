"""Unit tests for the pure security helpers."""

from __future__ import annotations

import pytest
from worktree_sandbox import security


@pytest.mark.parametrize(
    "name,expected",
    [
        ("OPENAI_API_KEY", True),
        ("ANTHROPIC_API_KEY", True),
        ("MY_SERVICE_TOKEN", True),
        ("DB_PASSWORD", True),
        ("AWS_SECRET_ACCESS_KEY", True),
        ("SSH_AUTH_SOCK", True),
        ("PATH", False),
        ("HOME", False),
        ("FOO", False),
        ("LANG", False),
        ("GIT_PAGER", False),
    ],
)
def test_is_secret_env_name(name: str, expected: bool) -> None:
    assert security.is_secret_env_name(name) is expected


def test_minimal_env_is_an_allowlist(monkeypatch) -> None:
    """Only the documented names cross into a child; everything else is dropped."""
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("HOME", "/Users/x")
    monkeypatch.setenv("LANG", "en_GB.UTF-8")
    monkeypatch.setenv("LC_ALL", "en_GB.UTF-8")
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.setenv("HERMES_WORKTREE_ID", "wt-1")
    # Names the old suffix denylist let through, plus the per-turn session identity.
    monkeypatch.setenv("FAL_KEY", "leak")
    monkeypatch.setenv("API_SERVER_KEY", "leak")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-leak")
    monkeypatch.setenv("MY_TOKEN", "leak")
    monkeypatch.setenv("PYTHONPATH", "/leak")
    monkeypatch.setenv("HERMES_SESSION_ID", "sess-1")
    monkeypatch.setenv("SOME_UNLISTED_SETTING", "leak")

    env = security.minimal_env()
    assert env["PATH"] == "/usr/bin"
    assert env["HOME"] == "/Users/x"
    assert env["LANG"] == "en_GB.UTF-8"
    assert env["LC_ALL"] == "en_GB.UTF-8"
    assert env["TERM"] == "xterm-256color"
    assert env["HERMES_WORKTREE_ID"] == "wt-1"
    for leaked in ("FAL_KEY", "API_SERVER_KEY", "OPENAI_API_KEY", "MY_TOKEN",
                   "PYTHONPATH", "HERMES_SESSION_ID", "SOME_UNLISTED_SETTING"):
        assert leaked not in env, f"{leaked} leaked into the child environment"


def test_minimal_env_merges_caller_extras() -> None:
    env = security.minimal_env({"GIT_PAGER": "cat", "GIT_TERMINAL_PROMPT": "0"})
    assert env["GIT_PAGER"] == "cat"
    assert env["GIT_TERMINAL_PROMPT"] == "0"


def test_redacted_env_names_reports_what_is_dropped() -> None:
    dropped = security.redacted_env_names({"PATH": "/usr/bin", "FAL_KEY": "x", "LC_TIME": "C"})
    assert dropped == ["FAL_KEY"]


@pytest.mark.parametrize("value", ["", "../x", "a/b", "a b", "x" * 65, "id\n"])
def test_validate_worktree_id_rejects(value: str) -> None:
    with pytest.raises(ValueError):
        security.validate_worktree_id(value)


@pytest.mark.parametrize("value", ["wt-1", "wt_abc-123", "A" * 64])
def test_validate_worktree_id_accepts(value: str) -> None:
    assert security.validate_worktree_id(value) == value


@pytest.mark.parametrize("value", ["a/b.py", "src/x", "file.txt"])
def test_is_safe_relative_path_accepts(value: str) -> None:
    assert security.is_safe_relative_path(value)


@pytest.mark.parametrize("value", ["", "/etc/passwd", "../x", "a/../b", "a//b", "C:\\x"])
def test_is_safe_relative_path_rejects(value: str) -> None:
    assert not security.is_safe_relative_path(value)


@pytest.mark.parametrize(
    "name,expected",
    [
        (".env", True),
        (".env.local", True),
        ("server.pem", True),
        ("id_rsa", True),
        ("auth.json", True),
        ("my_token.json", True),
        ("credentials.json", True),
        # Review feedback: these were missing from the never-mirror list.
        ("credentials", True),
        (".git-credentials", True),
        ("authorized_keys", True),
        ("known_hosts", True),
        ("app.py", False),
        ("README.md", False),
    ],
)
def test_is_sensitive_filename(name: str, expected: bool) -> None:
    assert security.is_sensitive_filename(name) is expected


@pytest.mark.parametrize(
    "path,expected",
    [
        ("node_modules/react/index.js", True),
        (".git/config", True),
        (".env", True),
        ("assets/logo.png", True),
        # Review feedback: the credential directories.
        (".ssh/id_ed25519", True),
        (".ssh/config", True),
        (".aws/credentials", True),
        (".gnupg/secring.gpg", True),
        (".git-credentials", True),
        ("src/main.py", False),
        ("README.md", False),
    ],
)
def test_should_skip_path(path: str, expected: bool) -> None:
    assert security.should_skip_path(path) is expected


def test_confine_to_root_blocks_escape(tmp_path) -> None:
    with pytest.raises(ValueError):
        security.confine_to_root(tmp_path, "../outside")

    inside = security.confine_to_root(tmp_path, "sub/file.txt")
    assert str(inside).startswith(str(tmp_path.resolve()))
