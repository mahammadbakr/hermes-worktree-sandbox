"""Shadow Git repositories for workspaces that are not (yet) under Git.

The worktree backend needs a commit to branch from. When the user's folder is not a Git
repository we mirror its text files into a private repo under
``$HERMES_HOME/plugin-data/worktree-sandbox/shadow-repos/<hash>/`` and branch from there, so
isolation still works with zero setup. Promotion writes back into the *original* folder, never
into the shadow repo.

Mirroring is deliberately conservative: credential-shaped names, binary files, dependency
directories and anything larger than ``max_file_bytes`` are skipped (they are also absent from
diffs and backups). The shadow copy therefore contains source text, not secrets or vendored trees.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import time
from pathlib import Path

from .security import minimal_env, should_skip_path

_MAX_FILES = 5000
_MAX_FILE_BYTES = 2 * 1024 * 1024
_MAX_TOTAL_BYTES = 200 * 1024 * 1024


class ShadowRepoError(RuntimeError):
    """The shadow repository could not be prepared."""


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    env = minimal_env()
    env.update({
        "GIT_AUTHOR_NAME": "worktree-sandbox", "GIT_AUTHOR_EMAIL": "worktree-sandbox@localhost",
        "GIT_COMMITTER_NAME": "worktree-sandbox", "GIT_COMMITTER_EMAIL": "worktree-sandbox@localhost",
        "GIT_CONFIG_NOSYSTEM": "1",
    })
    try:
        return subprocess.run(
            ["git", *args], cwd=str(cwd), capture_output=True, text=True,
            timeout=60, env=env, stdin=subprocess.DEVNULL,
        )
    except FileNotFoundError as exc:
        raise ShadowRepoError("git is not installed or not on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise ShadowRepoError(f"git {' '.join(args)} timed out") from exc


def shadow_repo_path(shadow_root: Path, workspace: Path) -> Path:
    digest = hashlib.sha256(str(workspace.resolve()).encode("utf-8")).hexdigest()[:16]
    return Path(shadow_root) / digest


def _iter_source_files(workspace: Path):
    """Yield ``(abs_path, rel_posix, size)`` for mirrorable files, bounded and deterministic."""
    count = 0
    total = 0
    for root, dirs, files in os.walk(workspace):
        dirs[:] = sorted(d for d in dirs if not should_skip_path(d + "/x", max_bytes=_MAX_FILE_BYTES))
        for name in sorted(files):
            abs_path = Path(root) / name
            rel = abs_path.relative_to(workspace).as_posix()
            if should_skip_path(rel, max_bytes=_MAX_FILE_BYTES):
                continue
            try:
                if abs_path.is_symlink() or not abs_path.is_file():
                    continue
                size = abs_path.stat().st_size
            except OSError:
                continue
            if size > _MAX_FILE_BYTES:
                continue
            count += 1
            total += size
            if count > _MAX_FILES or total > _MAX_TOTAL_BYTES:
                return
            yield abs_path, rel, size


def sync_shadow_repo(shadow_root: Path, workspace: Path) -> tuple[Path, int]:
    """Mirror *workspace* into its shadow repo and commit. Returns ``(repo_path, file_count)``."""
    repo = shadow_repo_path(shadow_root, workspace)
    repo.mkdir(parents=True, exist_ok=True)
    if not (repo / ".git").exists():
        proc = _git(["init", "-b", "main"], repo)
        if proc.returncode != 0:
            raise ShadowRepoError(f"git init failed: {proc.stderr.strip()[:300]}")
        _git(["config", "user.email", "worktree-sandbox@localhost"], repo)
        _git(["config", "user.name", "worktree-sandbox"], repo)

    # Clear the working tree (keep .git) so deleted source files disappear from the snapshot.
    for entry in repo.iterdir():
        if entry.name == ".git":
            continue
        if entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry, ignore_errors=True)
        else:
            try:
                entry.unlink()
            except OSError:
                pass

    copied = 0
    for abs_path, rel, _size in _iter_source_files(workspace):
        dest = repo / rel
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(abs_path, dest)
            copied += 1
        except OSError:
            continue

    _git(["add", "-A"], repo)
    proc = _git(["commit", "--allow-empty", "-m", f"shadow snapshot {time.strftime('%Y-%m-%dT%H:%M:%S')}"], repo)
    if proc.returncode != 0:
        raise ShadowRepoError(f"shadow commit failed: {proc.stderr.strip()[:300]}")
    return repo, copied
