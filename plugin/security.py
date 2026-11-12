"""Security helpers for ``worktree-sandbox``.

Everything here is pure and dependency-free so it can be unit-tested in isolation:

* ``minimal_env``  — build a child environment from a small allowlist.
* ``is_sensitive_filename`` — decide whether a path must never be mirrored into a
  shadow repository, a diff, or a promotion backup.
* ``validate_worktree_id`` — reject ids that could escape the managed data directory.
* ``is_safe_relative_path`` — reject traversal / absolute / empty paths inside a repo.

This plugin isolates the *Git working tree*, not the whole filesystem (that is what
``bubblewrap`` / ``singularity`` do with a real OS sandbox). The stripping here limits
blast radius: a model-authored ``env`` dump or a runaway build cannot read provider keys
out of the shell environment it inherits, and credential files are never copied around.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from pathlib import Path

# Exact environment names that always carry a credential.
SECRET_ENV_EXACT: frozenset[str] = frozenset({
    "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY", "GOOGLE_API_KEY",
    "GEMINI_API_KEY", "DEEPSEEK_API_KEY", "GROQ_API_KEY", "MISTRAL_API_KEY",
    "XAI_API_KEY", "TOGETHER_API_KEY", "FIREWORKS_API_KEY", "COHERE_API_KEY",
    "PERPLEXITY_API_KEY", "REPLICATE_API_TOKEN", "HUGGING_FACE_HUB_TOKEN",
    "HF_TOKEN", "DEEPINFRA_API_KEY", "CEREBRAS_API_KEY", "SAMBANOVA_API_KEY",
    "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
    "GH_TOKEN", "GITHUB_TOKEN", "GITLAB_TOKEN", "BITBUCKET_TOKEN",
    "NPM_TOKEN", "PYPI_TOKEN", "CARGO_REGISTRY_TOKEN",
    "SLACK_TOKEN", "SLACK_BOT_TOKEN", "DISCORD_TOKEN", "TELEGRAM_BOT_TOKEN",
    "SSH_AUTH_SOCK", "GPG_AGENT_INFO", "DBUS_SESSION_BUS_ADDRESS",
    "HERMES_CA_BUNDLE",
})

# Suffix shapes that almost always name a credential.
_SECRET_SUFFIXES: tuple[str, ...] = (
    "_API_KEY", "_APIKEY", "_ACCESS_KEY", "_SECRET_KEY", "_SECRET",
    "_TOKEN", "_PASSWORD", "_PASSWD", "_PRIVATE_KEY", "_CREDENTIALS",
)

# Environment variables Hermes injects per-turn; they must not persist into the
# worktree shell or leak one session's identity into another.
_HERMES_SESSION_PREFIXES: tuple[str, ...] = (
    "HERMES_SESSION_", "HERMES_UI_SESSION_ID", "HERMES_CRON_", "HERMES_RPC_",
    "HERMES_DELEGATED_CHILD_CONTEXT", "HERMES_KERNEL_DIR", "AI_AGENT", "HERMES_AGENT",
)

# Names we deliberately keep even though they look sensitive-adjacent.
_ENV_KEEP: frozenset[str] = frozenset({"PATH", "HOME", "USER", "LOGNAME", "SHELL", "TMPDIR"})

# The child-environment allowlist. A denylist is the wrong shape here: core's own local backend
# strips more than a suffix list can express (``FAL_KEY``, ``API_SERVER_KEY``, ... end in none of
# our suffixes), so a vendor key we failed to enumerate would reach a model-authored command. Only
# these names (plus ``LC_*`` and our own ``HERMES_WORKTREE_*``) cross into a child process.
_BASE_ENV_ALLOWLIST: frozenset[str] = frozenset({
    "PATH", "HOME", "USER", "LOGNAME", "SHELL", "TERM", "TMPDIR", "PWD", "LANG",
})


def is_secret_env_name(name: str) -> bool:
    """Return whether *name* looks like a credential-bearing environment variable."""
    if name in _ENV_KEEP:
        return False
    if name in SECRET_ENV_EXACT:
        return True
    upper = name.upper()
    return any(upper.endswith(suffix) for suffix in _SECRET_SUFFIXES)


def _is_hermes_session_var(name: str) -> bool:
    return any(name == prefix or name.startswith(prefix) for prefix in _HERMES_SESSION_PREFIXES)


def minimal_env(extra: Mapping[str, str] | None = None) -> dict[str, str]:
    """Build a child-process environment from a small allowlist, not a denylist.

    Only ``PATH``/``HOME``/``USER``/``LOGNAME``/``SHELL``/``TERM``/``TMPDIR``/``PWD``/``LANG``,
    ``LC_*`` locales and our own ``HERMES_WORKTREE_*`` values are inherited; everything else —
    provider keys, tool keys, vendor credentials, Hermes's per-turn session identity — is absent
    from the environment a command or verification child can read. ``extra`` is merged last so
    callers can add the handful of variables their own child needs (``GIT_PAGER``, git identity).
    """
    env: dict[str, str] = {}
    for key, value in os.environ.items():
        if not isinstance(key, str) or not isinstance(value, str):
            continue
        if key in _BASE_ENV_ALLOWLIST or key.startswith(("LC_", "HERMES_WORKTREE_")):
            env[key] = value
    if extra:
        for key, value in extra.items():
            if isinstance(key, str) and isinstance(value, str):
                env[key] = value
    return env


def redacted_env_names(env: Mapping[str, str] | None = None) -> list[str]:
    """Names present in *env* (default: ``os.environ``) that the allowlist would drop.

    Used by the diagnostics/tests to prove a credential-shaped variable cannot reach a child.
    """
    source = os.environ if env is None else env
    return sorted(
        key for key, value in source.items()
        if isinstance(key, str) and isinstance(value, str)
        and key not in _BASE_ENV_ALLOWLIST
        and not key.startswith(("LC_", "HERMES_WORKTREE_"))
    )


# Filenames/patterns that must never be mirrored, diffed, or backed up verbatim.
_SENSITIVE_NAME_RE = re.compile(
    r"(?i)(^\.env(\.|$)|^\.envrc$|\.pem$|\.key$|\.p12$|\.pfx$|"
    r"(^|[._-])secret([._-]|$)|(^|[._-])token([._-]|$)|(^|[._-])credential([._-]|$)|"
    r"^credentials$|^credentials\.json$|"
    r"^id_(rsa|dsa|ecdsa|ed25519)$|^\.netrc$|^\.npmrc$|^\.pypirc$|"
    r"^\.git-credentials$|^authorized_keys$|^known_hosts$|"
    r"^auth\.json$|serviceaccount.*\.json$)"
)

# Directory names never mirrored into a shadow snapshot or diffed. The credential directories are
# not a mirroring preference: nothing inside them is ever a project source file.
SKIP_DIR_NAMES: frozenset[str] = frozenset({
    ".git", ".hg", ".svn", "node_modules", ".venv", "venv", "__pycache__",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox", "dist", "build",
    ".next", ".turbo", ".cache", "target", ".hermes", ".idea", ".vscode",
    ".ssh", ".aws", ".gnupg",
})

# Extensions that are binary / not worth mirroring as text.
_BINARY_SUFFIXES: frozenset[str] = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".zip", ".gz", ".tgz",
    ".tar", ".whl", ".so", ".dylib", ".dll", ".exe", ".bin", ".pyc", ".pyo", ".class",
    ".jar", ".mp3", ".mp4", ".mov", ".wav", ".woff", ".woff2", ".ttf", ".otf", ".db",
    ".sqlite", ".sqlite3", ".lock",
})


def is_sensitive_filename(name: str) -> bool:
    """Whether a file basename must be treated as a credential and never copied or diffed."""
    base = os.path.basename(name)
    return bool(_SENSITIVE_NAME_RE.search(base))


def should_skip_path(rel_path: str, *, max_bytes: int = 2 * 1024 * 1024) -> bool:
    """Whether a workspace-relative path should be excluded from shadow mirroring / diffs."""
    parts = [p for p in rel_path.replace("\\", "/").split("/") if p]
    if not parts:
        return True
    if any(part in SKIP_DIR_NAMES for part in parts[:-1]) or parts[-1] in SKIP_DIR_NAMES:
        return True
    if is_sensitive_filename(parts[-1]):
        return True
    _, ext = os.path.splitext(parts[-1])
    if ext.lower() in _BINARY_SUFFIXES:
        return True
    return False


_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}\Z")


def validate_worktree_id(worktree_id: str) -> str:
    """Validate a worktree id, raising ``ValueError`` on anything that could escape the data dir.

    ``\\Z`` (not ``$``) so a trailing newline cannot slip through — the same reason the catalog
    validator anchors its own identifiers with ``\\Z``.
    """
    if not isinstance(worktree_id, str) or not _ID_RE.match(worktree_id):
        raise ValueError(
            f"invalid worktree id {worktree_id!r}: expected 1-64 characters of [A-Za-z0-9_-]"
        )
    return worktree_id


def is_safe_relative_path(rel_path: str) -> bool:
    """Whether *rel_path* is a plain repo-relative path (no absolute, no ``..``, no empty segs)."""
    if not isinstance(rel_path, str) or not rel_path.strip():
        return False
    if rel_path.startswith(("/", "\\")):
        return False
    if re.match(r"^[A-Za-z]:", rel_path):  # Windows drive
        return False
    parts = rel_path.replace("\\", "/").split("/")
    return all(part not in ("", ".", "..") for part in parts)


def confine_to_root(root: str | Path, candidate: str | Path) -> Path:
    """Resolve *candidate* and require it to live under *root*; raise ``ValueError`` otherwise."""
    root_resolved = Path(root).resolve()
    target = (root_resolved / candidate).resolve() if not Path(candidate).is_absolute() else Path(candidate).resolve()
    if target != root_resolved and root_resolved not in target.parents:
        raise ValueError(f"path {candidate!r} escapes {root_resolved}")
    return target
