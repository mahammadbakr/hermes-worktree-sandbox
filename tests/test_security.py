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


def test_sanitize_env_strips_secrets_and_session_identity() -> None:
    env = {
        "PATH": "/usr/bin",
        "OPENAI_API_KEY": "sk-leak",
        "MY_TOKEN": "leak",
        "HERMES_SESSION_ID": "sess-1",
        "HERMES_RPC_TOKEN": "leak",
        "SAFE": "keep",
    }
    cleaned = security.sanitize_env(env)
    assert cleaned == {"PATH": "/usr/bin", "SAFE": "keep"}


def test_sanitize_env_ignores_non_string_values() -> None:
    cleaned = security.sanitize_env({"A": "b", "BAD": None, "N": 3})  # type: ignore[dict-item]
    assert cleaned == {"A": "b"}


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
