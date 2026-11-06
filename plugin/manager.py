"""``WorktreeManager`` — transactional Git worktrees for Hermes Agent.

Every operation is deterministic and offline: it shells out to ``git`` on ``PATH`` with a
sanitized environment, confines all managed paths under
``$HERMES_HOME/plugin-data/worktree-sandbox/``, and never raises a bare exception into a
tool handler (callers get ``WorktreeError`` with a user-facing message).

The manager owns three responsibilities:

1. **Lifecycle** — create/register a worktree per task, reuse it across turns, discard and prune.
2. **Inspection** — file-level change list plus ``+added`` / ``-deleted`` line stats and a
   unified diff against the branch's base commit.
3. **Promotion** — copy a worktree's changed files back into the main checkout with a
   conflict check and a timestamped ``.bak`` backup, or refuse and report conflicts.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .security import (
    is_safe_relative_path,
    sanitize_env,
    validate_worktree_id,
)
from .storage import PLUGIN_NAME, Ledger

_GIT_TIMEOUT = 30
_MAX_DIFF_BYTES = 200_000


class WorktreeError(RuntimeError):
    """A user-facing worktree failure. Tool handlers convert this to JSON ``{"ok": false}``.

    Subclasses ``RuntimeError`` so a failure raised out of ``create_environment`` is handled by
    the same path other backends' infrastructure errors use.
    """


def _slug(task_id: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(task_id or "").strip().lower()).strip("-")
    return (cleaned[:32].strip("-") or "default")


class WorktreeManager:
    """Create, inspect, promote and dispose isolated Git worktrees."""

    def __init__(self, ledger: Ledger | None = None, data_dir: Any | None = None) -> None:
        self._ledger = ledger or Ledger()
        self._data_dir_override = data_dir

    # -- paths -------------------------------------------------------------------

    @property
    def ledger(self) -> Ledger:
        return self._ledger

    @property
    def data_dir(self) -> Path:
        if self._data_dir_override is not None:
            path = Path(self._data_dir_override)
            path.mkdir(parents=True, exist_ok=True)
            return path
        from plugins.plugin_storage import plugin_data_dir

        return plugin_data_dir(PLUGIN_NAME)

    def _subdir(self, name: str) -> Path:
        path = self.data_dir / name
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def worktrees_dir(self) -> Path:
        return self._subdir("worktrees")

    @property
    def scratch_root(self) -> Path:
        return self._subdir("scratch")

    @property
    def backups_root(self) -> Path:
        return self._subdir("backups")

    # -- git plumbing ------------------------------------------------------------

    def git_available(self) -> bool:
        return shutil.which("git") is not None

    def _git(
        self, args: list[str], cwd: Path, *, timeout: int = _GIT_TIMEOUT,
        check: bool = False, binary: bool = False,
    ) -> subprocess.CompletedProcess:
        env = sanitize_env(os.environ)
        env.setdefault("GIT_PAGER", "cat")
        env.setdefault("GIT_TERMINAL_PROMPT", "0")
        env.setdefault("GIT_CONFIG_NOSYSTEM", "0")
        try:
            proc = subprocess.run(
                ["git", *args], cwd=str(cwd), capture_output=True, timeout=timeout,
                env=env, stdin=subprocess.DEVNULL, text=not binary,
            )
        except FileNotFoundError as exc:
            raise WorktreeError("git is not installed or not on PATH") from exc
        except subprocess.TimeoutExpired as exc:
            raise WorktreeError(f"git {' '.join(args)} timed out after {timeout}s") from exc
        if check and proc.returncode != 0:
            stderr = proc.stderr if isinstance(proc.stderr, str) else (proc.stderr or b"").decode("utf-8", "replace")
            raise WorktreeError(f"git {' '.join(args)} failed: {stderr.strip()[:400]}")
        return proc

    def find_repo_root(self, path: Path) -> Path | None:
        """Return the Git top-level for *path*, or ``None`` when it is not inside a repo."""
        if not self.git_available():
            return None
        try:
            proc = self._git(["rev-parse", "--show-toplevel"], path)
        except WorktreeError:
            return None
        if proc.returncode != 0:
            return None
        out = (proc.stdout or "").strip()
        return Path(out) if out else None

    def _head_commit(self, repo_root: Path) -> str | None:
        proc = self._git(["rev-parse", "HEAD"], repo_root)
        out = (proc.stdout or "").strip()
        return out if proc.returncode == 0 and re.fullmatch(r"[0-9a-f]{40}", out) else None

    def _normalize_workspace(self, workspace: str | None) -> Path:
        raw = (workspace or "").strip() or os.getcwd()
        path = Path(raw).expanduser()
        try:
            path = path.resolve()
        except OSError as exc:
            raise WorktreeError(f"cannot resolve workspace {raw!r}: {exc}") from exc
        if not path.is_dir():
            raise WorktreeError(f"workspace is not a directory: {path}")
        return path

    def resolve_workspace(self, workspace: str | None) -> Path:
        """Return the Git repo root for *workspace*, raising a clear ``WorktreeError`` otherwise."""
        start = self._normalize_workspace(workspace)
        repo = self.find_repo_root(start)
        if repo is None:
            raise WorktreeError(
                f"{start} is not inside a Git repository. Run `git init` (and make an initial commit) "
                "in the project, or point the tool at a Git workspace."
            )
        return repo

    # -- identifiers -------------------------------------------------------------

    def _make_id(self, task_id: str, repo_root: Path) -> str:
        digest = hashlib.sha256(str(repo_root).encode("utf-8")).hexdigest()[:6]
        return validate_worktree_id(f"wt-{_slug(task_id)}-{digest}")

    def _branch_for(self, worktree_id: str) -> str:
        return f"hermes-wt/{worktree_id}"

    # -- create / reuse ----------------------------------------------------------

    def create_worktree(
        self, workspace: str | None, task_id: str = "default", *,
        base: str | None = None, reuse: bool = True,
    ) -> dict[str, Any]:
        repo_root = self.resolve_workspace(workspace)
        worktree_id = self._make_id(task_id, repo_root)

        if reuse:
            existing = self._ledger.get_worktree(worktree_id)
            if existing and existing.get("state") == "active" and Path(existing["path"]).is_dir():
                return self._describe(existing)

        base_commit = base or self._head_commit(repo_root)
        if base_commit is None:
            raise WorktreeError(
                "this repository has no commits yet; make an initial commit "
                "(`git add -A && git commit -m init`) before creating a worktree"
            )

        branch = self._branch_for(worktree_id)
        wt_path = self.worktrees_dir / worktree_id

        # Clean any stale directory / registration from an earlier run.
        self._git(["worktree", "prune"], repo_root)
        if wt_path.exists():
            shutil.rmtree(wt_path, ignore_errors=True)
        self._git(["branch", "-D", branch], repo_root)  # best-effort: reset a stale branch

        self._git(["worktree", "add", "-b", branch, "--force", str(wt_path), base_commit], repo_root, check=True)

        self._ledger.upsert_worktree(
            worktree_id=worktree_id, workspace=str(repo_root), path=str(wt_path), branch=branch,
            base_commit=base_commit, shadow=False, state="active",
        )
        self._ledger.record_event(worktree_id, "created", {"base_commit": base_commit, "branch": branch})
        record = self._ledger.get_worktree(worktree_id)
        assert record is not None
        return self._describe(record)

    def get_or_create(self, workspace: str | None, task_id: str = "default") -> dict[str, Any]:
        """Idempotent create used by the terminal-environment provider."""
        return self.create_worktree(workspace, task_id, reuse=True)

    def _describe(self, record: dict[str, Any]) -> dict[str, Any]:
        return {
            "worktree_id": record["id"],
            "path": record["path"],
            "branch": record["branch"],
            "workspace": record["workspace"],
            "base_commit": record.get("base_commit"),
            "shadow": bool(record.get("shadow")),
            "state": record.get("state", "active"),
        }

    # -- inspection --------------------------------------------------------------

    def _collect_changes(self, wt_path: Path) -> list[dict[str, Any]]:
        """Return ``[{path, status, added, deleted}]`` for a worktree vs its base commit."""
        # ``add -N`` (intent-to-add) makes untracked files appear in ``git diff HEAD`` as
        # full additions without staging their content; the index is reset afterwards.
        self._git(["add", "-N", "--", "."], wt_path)
        try:
            numstat = self._git(["diff", "--numstat", "HEAD"], wt_path).stdout or ""
            porcelain = self._git(["status", "--porcelain=v1"], wt_path).stdout or ""
        finally:
            self._git(["reset", "-q"], wt_path)

        stats: dict[str, tuple[int, int, bool]] = {}
        for line in numstat.splitlines():
            parts = line.split("\t")
            if len(parts) < 3:
                continue
            added_raw, deleted_raw, path = parts[0], parts[1], parts[2]
            binary = added_raw == "-" or deleted_raw == "-"
            try:
                added = int(added_raw) if not binary else 0
                deleted = int(deleted_raw) if not binary else 0
            except ValueError:
                added = deleted = 0
            stats[path] = (added, deleted, binary)

        changes: list[dict[str, Any]] = []
        for line in porcelain.splitlines():
            if len(line) < 4:
                continue
            code = line[:2]
            raw_path = line[3:]
            if " -> " in raw_path:  # rename / copy
                raw_path = raw_path.split(" -> ", 1)[1]
            path = raw_path.strip().strip('"')
            added, deleted, binary = stats.get(path, (0, 0, False))
            changes.append({
                "path": path, "status": _status_label(code),
                "added": added, "deleted": deleted, "binary": binary,
            })
        changes.sort(key=lambda item: item["path"])
        return changes

    def status(self, worktree_id: str) -> dict[str, Any]:
        record = self._require(worktree_id)
        wt_path = Path(record["path"])
        if not wt_path.is_dir():
            raise WorktreeError(f"worktree directory is missing: {wt_path}")
        files = self._collect_changes(wt_path)
        total_added = sum(f["added"] for f in files)
        total_deleted = sum(f["deleted"] for f in files)
        return {
            **self._describe(record),
            "clean": not files,
            "changed_files": len(files),
            "added": total_added,
            "deleted": total_deleted,
            "files": files,
        }

    def diff(self, worktree_id: str, *, path: str | None = None, max_bytes: int = _MAX_DIFF_BYTES) -> dict[str, Any]:
        record = self._require(worktree_id)
        wt_path = Path(record["path"])
        if not wt_path.is_dir():
            raise WorktreeError(f"worktree directory is missing: {wt_path}")
        args = ["diff", "HEAD"]
        if path:
            if not is_safe_relative_path(path):
                raise WorktreeError(f"unsafe diff path: {path!r}")
            args += ["--", path]
        self._git(["add", "-N", "--", "."], wt_path)
        try:
            proc = self._git(args, wt_path)
        finally:
            self._git(["reset", "-q"], wt_path)
        text = proc.stdout or ""
        truncated = len(text) > max_bytes
        if truncated:
            text = text[:max_bytes] + "\n...[diff truncated]"
        return {**self._describe(record), "diff": text, "truncated": truncated}

    # -- promotion ---------------------------------------------------------------

    def _git_show_bytes(self, repo: Path, commit: str | None, rel_path: str) -> bytes | None:
        if not commit:
            return None
        try:
            proc = self._git(["show", f"{commit}:{rel_path}"], repo, binary=True)
        except WorktreeError:
            return None
        if proc.returncode != 0:
            return None
        return proc.stdout if isinstance(proc.stdout, bytes) else (proc.stdout or "").encode()

    def promote(
        self, worktree_id: str, *, force: bool = False, files: Iterable[str] | None = None,
    ) -> dict[str, Any]:
        record = self._require(worktree_id)
        wt_path = Path(record["path"])
        repo = Path(record["workspace"])
        if not wt_path.is_dir():
            raise WorktreeError(f"worktree directory is missing: {wt_path}")
        if not repo.is_dir():
            raise WorktreeError(f"target workspace is missing: {repo}")

        wanted = {f for f in (files or []) if f}
        changes = self._collect_changes(wt_path)
        if wanted:
            changes = [c for c in changes if c["path"] in wanted]

        stamp = time.strftime("%Y%m%d-%H%M%S")
        backup_dir = self.backups_root / f"{worktree_id}-{stamp}"
        applied: list[str] = []
        deleted: list[str] = []
        conflicts: list[dict[str, str]] = []
        skipped: list[dict[str, str]] = []

        for change in changes:
            rel = change["path"]
            if not is_safe_relative_path(rel):
                conflicts.append({"path": rel, "reason": "path escapes the repository"})
                continue

            base_content = self._git_show_bytes(repo, record.get("base_commit"), rel)
            host_path = repo / rel
            host_content = host_path.read_bytes() if host_path.is_file() else None
            src_path = wt_path / rel
            wt_content = src_path.read_bytes() if src_path.is_file() else None

            # A host file changed since the worktree branched is a real conflict unless the
            # worktree's content already matches what is on the host.
            if not force and host_content is not None and host_content != base_content and host_content != wt_content:
                conflicts.append({"path": rel, "reason": "modified on the host since the worktree base"})
                continue

            try:
                if host_content is not None:
                    backup_path = backup_dir / rel
                    backup_path.parent.mkdir(parents=True, exist_ok=True)
                    backup_path.write_bytes(host_content)
            except OSError as exc:
                skipped.append({"path": rel, "reason": f"backup failed: {exc}"})
                continue

            try:
                if wt_content is None:
                    if host_path.exists():
                        host_path.unlink()
                    deleted.append(rel)
                else:
                    host_path.parent.mkdir(parents=True, exist_ok=True)
                    host_path.write_bytes(wt_content)
                    mode = src_path.stat().st_mode & 0o777
                    try:
                        os.chmod(host_path, mode)
                    except OSError:
                        pass
                    applied.append(rel)
            except OSError as exc:
                skipped.append({"path": rel, "reason": f"write failed: {exc}"})

        if conflicts:
            self._ledger.set_state(worktree_id, "active")
        elif applied or deleted:
            self._ledger.set_state(worktree_id, "promoted")
        self._ledger.record_event(worktree_id, "promoted", {
            "applied": applied, "deleted": deleted,
            "conflicts": [c["path"] for c in conflicts], "force": force,
        })

        return {
            **self._describe({**record, "state": "active"}),
            "ok": not conflicts and not skipped,
            "applied": applied,
            "deleted": deleted,
            "conflicts": conflicts,
            "skipped": skipped,
            "backup_dir": str(backup_dir) if backup_dir.exists() else None,
        }

    # -- teardown ----------------------------------------------------------------

    def list_worktrees(self, *, workspace: str | None = None, include_inactive: bool = False) -> list[dict[str, Any]]:
        state = None if include_inactive else "active"
        rows = self._ledger.list_worktrees(workspace=workspace, state=state)
        described: list[dict[str, Any]] = []
        for row in rows:
            try:
                view = self.status(row["id"])
                described.append({
                    "worktree_id": view["worktree_id"], "path": view["path"], "branch": view["branch"],
                    "workspace": view["workspace"], "state": view["state"], "clean": view["clean"],
                    "changed_files": view["changed_files"], "added": view["added"], "deleted": view["deleted"],
                    "base_commit": view["base_commit"],
                })
            except WorktreeError:
                described.append({**self._describe(row), "clean": True, "changed_files": 0, "added": 0, "deleted": 0})
        return described

    def discard(self, worktree_id: str) -> dict[str, Any]:
        record = self._require(worktree_id)
        wt_path = Path(record["path"])
        repo = Path(record["workspace"])
        if repo.is_dir():
            self._git(["worktree", "remove", "--force", str(wt_path)], repo)
            self._git(["worktree", "prune"], repo)
            self._git(["branch", "-D", record["branch"]], repo)
        if wt_path.exists():
            shutil.rmtree(wt_path, ignore_errors=True)
        self._ledger.set_state(worktree_id, "discarded")
        self._ledger.record_event(worktree_id, "discarded", None)
        return {"worktree_id": worktree_id, "state": "discarded"}

    def prune(self, max_worktrees: int = 20) -> dict[str, Any]:
        try:
            limit = max(1, int(max_worktrees))
        except (TypeError, ValueError):
            limit = 20
        active = self._ledger.list_worktrees(state="active")
        removed: list[str] = []
        for row in active[limit:]:  # oldest last (list is created_at DESC)
            try:
                if self.status(row["id"])["clean"]:
                    self.discard(row["id"])
                    removed.append(row["id"])
            except WorktreeError:
                continue
        return {"removed": removed, "kept": len(active) - len(removed)}

    # -- helpers -----------------------------------------------------------------

    def _require(self, worktree_id: str) -> dict[str, Any]:
        try:
            validate_worktree_id(worktree_id)
        except ValueError as exc:
            raise WorktreeError(str(exc)) from exc
        record = self._ledger.get_worktree(worktree_id)
        if record is None:
            raise WorktreeError(f"unknown worktree id {worktree_id!r}")
        return record


_STATUS_LABELS = {
    "??": "untracked", "A ": "added", "AM": "added", "AD": "added",
    " D": "deleted", "D ": "deleted", " M": "modified", "M ": "modified",
    "MM": "modified", "R ": "renamed", "RM": "renamed", " C": "copied", "C ": "copied",
    "UU": "conflicted",
}


def _status_label(code: str) -> str:
    return _STATUS_LABELS.get(code, _STATUS_LABELS.get(code[0] + " ", "modified"))
