"""Unit tests for ``WorktreeManager`` (no Hermes checkout required)."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
from worktree_sandbox.manager import WorktreeError


def _host_status(repo: Path) -> str:
    import subprocess

    return subprocess.run(
        ["git", "status", "--porcelain"], cwd=str(repo), capture_output=True, text=True
    ).stdout


def test_create_worktree_leaves_host_clean(manager, git_repo: Path) -> None:
    info = manager.create_worktree(str(git_repo), task_id="t1")
    assert info["worktree_id"].startswith("wt-")
    assert Path(info["path"]).is_dir()
    assert info["branch"] == f"hermes-wt/{info['worktree_id']}"
    assert _host_status(git_repo).strip() == ""


def test_create_is_idempotent_per_task(manager, git_repo: Path) -> None:
    first = manager.create_worktree(str(git_repo), task_id="t1")
    second = manager.create_worktree(str(git_repo), task_id="t1")
    assert first["worktree_id"] == second["worktree_id"]
    assert first["path"] == second["path"]


def test_changes_are_isolated_from_host(manager, git_repo: Path) -> None:
    info = manager.create_worktree(str(git_repo), task_id="edit")
    wt = Path(info["path"])
    (wt / "app.py").write_text("def greet():\n    return 'hello world'\n", encoding="utf-8")
    (wt / "new_file.txt").write_text("brand new\n", encoding="utf-8")

    status = manager.status(info["worktree_id"])
    assert status["changed_files"] == 2
    paths = {f["path"] for f in status["files"]}
    assert paths == {"app.py", "new_file.txt"}
    assert status["added"] >= 2 and status["deleted"] >= 1
    assert status["clean"] is False

    # Host must be untouched.
    assert _host_status(git_repo).strip() == ""
    assert "hello world" not in (git_repo / "app.py").read_text(encoding="utf-8")
    assert not (git_repo / "new_file.txt").exists()


def test_diff_contains_changes(manager, git_repo: Path) -> None:
    info = manager.create_worktree(str(git_repo), task_id="diff")
    wt = Path(info["path"])
    (wt / "app.py").write_text("def greet():\n    return 'changed'\n", encoding="utf-8")
    result = manager.diff(info["worktree_id"])
    assert "changed" in result["diff"]
    assert result["truncated"] is False


def test_status_clean_when_no_changes(manager, git_repo: Path) -> None:
    info = manager.create_worktree(str(git_repo), task_id="clean")
    status = manager.status(info["worktree_id"])
    assert status["clean"] is True
    assert status["changed_files"] == 0


def test_promote_applies_changes_with_backup(manager, git_repo: Path) -> None:
    info = manager.create_worktree(str(git_repo), task_id="promote")
    wt = Path(info["path"])
    (wt / "app.py").write_text("def greet():\n    return 'promoted'\n", encoding="utf-8")
    (wt / "added.txt").write_text("new\n", encoding="utf-8")

    result = manager.promote(info["worktree_id"])
    assert result["ok"] is True
    assert "app.py" in result["applied"] and "added.txt" in result["applied"]
    assert (git_repo / "added.txt").read_text(encoding="utf-8") == "new\n"
    assert "promoted" in (git_repo / "app.py").read_text(encoding="utf-8")
    # A backup of the previous app.py was written.
    assert result["backup_dir"] is not None
    assert (Path(result["backup_dir"]) / "app.py").read_text(encoding="utf-8").startswith("def greet")


def test_promote_delete_removes_host_file(manager, git_repo: Path) -> None:
    info = manager.create_worktree(str(git_repo), task_id="delete")
    wt = Path(info["path"])
    (wt / "README.md").unlink()
    result = manager.promote(info["worktree_id"])
    assert "README.md" in result["deleted"]
    assert not (git_repo / "README.md").exists()


def test_promote_reports_conflict_and_refuses(manager, git_repo: Path) -> None:
    info = manager.create_worktree(str(git_repo), task_id="conflict")
    wt = Path(info["path"])
    (wt / "app.py").write_text("def greet():\n    return 'worktree'\n", encoding="utf-8")
    # Host file changes after the worktree branched.
    (git_repo / "app.py").write_text("def greet():\n    return 'host-change'\n", encoding="utf-8")

    result = manager.promote(info["worktree_id"])
    assert result["ok"] is False
    assert [c["path"] for c in result["conflicts"]] == ["app.py"]
    # Refused: the host edit is preserved untouched.
    assert "host-change" in (git_repo / "app.py").read_text(encoding="utf-8")


def test_promote_force_overwrites_but_backs_up(manager, git_repo: Path) -> None:
    info = manager.create_worktree(str(git_repo), task_id="force")
    wt = Path(info["path"])
    (wt / "app.py").write_text("def greet():\n    return 'worktree'\n", encoding="utf-8")
    (git_repo / "app.py").write_text("def greet():\n    return 'host-change'\n", encoding="utf-8")

    result = manager.promote(info["worktree_id"], force=True)
    assert result["ok"] is True
    assert "worktree" in (git_repo / "app.py").read_text(encoding="utf-8")
    assert result["backup_dir"] is not None
    assert "host-change" in (Path(result["backup_dir"]) / "app.py").read_text(encoding="utf-8")


def test_promote_subset_of_files(manager, git_repo: Path) -> None:
    info = manager.create_worktree(str(git_repo), task_id="subset")
    wt = Path(info["path"])
    (wt / "app.py").write_text("def greet():\n    return 'one'\n", encoding="utf-8")
    (wt / "extra.py").write_text("X = 1\n", encoding="utf-8")

    result = manager.promote(info["worktree_id"], files=["extra.py"])
    assert result["applied"] == ["extra.py"]
    assert not (git_repo / "app.py").read_text(encoding="utf-8").count("one")


def test_discard_removes_worktree(manager, git_repo: Path) -> None:
    info = manager.create_worktree(str(git_repo), task_id="discard")
    path = Path(info["path"])
    assert path.is_dir()
    result = manager.discard(info["worktree_id"])
    assert result["state"] == "discarded"
    assert not path.exists()
    assert manager.list_worktrees(workspace=str(git_repo)) == []


def test_list_worktrees_reports_stats(manager, git_repo: Path) -> None:
    info = manager.create_worktree(str(git_repo), task_id="listed")
    (Path(info["path"]) / "x.txt").write_text("a\nb\n", encoding="utf-8")
    rows = manager.list_worktrees(workspace=str(git_repo))
    assert len(rows) == 1
    assert rows[0]["worktree_id"] == info["worktree_id"]
    assert rows[0]["changed_files"] == 1
    assert rows[0]["added"] == 2


def test_prune_removes_older_clean_worktrees(manager, git_repo: Path) -> None:
    first = manager.create_worktree(str(git_repo), task_id="one")
    time.sleep(0.01)
    manager.create_worktree(str(git_repo), task_id="two")
    time.sleep(0.01)
    manager.create_worktree(str(git_repo), task_id="three")

    result = manager.prune(max_worktrees=2)
    assert len(result["removed"]) >= 1
    remaining = manager.list_worktrees(workspace=str(git_repo))
    assert len(remaining) <= 2
    assert first["worktree_id"] not in {r["worktree_id"] for r in remaining}


def test_prune_keeps_dirty_worktrees(manager, git_repo: Path) -> None:
    dirty = manager.create_worktree(str(git_repo), task_id="dirty")
    (Path(dirty["path"]) / "wip.txt").write_text("wip\n", encoding="utf-8")
    time.sleep(0.01)
    manager.create_worktree(str(git_repo), task_id="clean")

    manager.prune(max_worktrees=1)
    remaining = {r["worktree_id"] for r in manager.list_worktrees(workspace=str(git_repo))}
    assert dirty["worktree_id"] in remaining


def test_non_git_workspace_uses_shadow_repo(manager, tmp_path: Path) -> None:
    """A plain folder is mirrored into a private shadow repo so isolation still works."""
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "main.py").write_text("VALUE = 1\n", encoding="utf-8")

    info = manager.create_worktree(str(plain), task_id="shadow")
    assert info["shadow"] is True
    assert info["workspace"] == str(plain.resolve())
    wt = Path(info["path"])
    assert (wt / "main.py").read_text(encoding="utf-8") == "VALUE = 1\n"

    # A change inside the shadow worktree is promoted back into the real folder.
    (wt / "main.py").write_text("VALUE = 2\n", encoding="utf-8")
    result = manager.promote(info["worktree_id"])
    assert result["ok"] is True
    assert (plain / "main.py").read_text(encoding="utf-8") == "VALUE = 2\n"


def test_shadow_mirror_skips_credentials(manager, tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "keep.py").write_text("X = 1\n", encoding="utf-8")
    (plain / ".env").write_text("SECRET=leak\n", encoding="utf-8")
    (plain / "server.pem").write_text("KEY\n", encoding="utf-8")

    info = manager.create_worktree(str(plain), task_id="noleak")
    wt = Path(info["path"])
    assert (wt / "keep.py").exists()
    assert not (wt / ".env").exists()
    assert not (wt / "server.pem").exists()


def test_peek_workspace_has_no_side_effects(manager, tmp_path: Path) -> None:
    plain = tmp_path / "quiet"
    plain.mkdir()
    before = list(manager.shadow_root.iterdir()) if manager.shadow_root.is_dir() else []
    assert manager.peek_workspace(str(plain)) == plain.resolve()
    after = list(manager.shadow_root.iterdir()) if manager.shadow_root.is_dir() else []
    assert before == after


def test_repo_without_commits_raises(manager, tmp_path: Path) -> None:
    import subprocess

    repo = tmp_path / "empty"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=str(repo), check=True, capture_output=True)
    with pytest.raises(WorktreeError, match="no commits yet"):
        manager.create_worktree(str(repo), task_id="x")


@pytest.mark.parametrize("bad_id", ["../../etc", "", "a/b", "x" * 100])
def test_status_rejects_bad_ids(manager, bad_id: str) -> None:
    with pytest.raises(WorktreeError):
        manager.status(bad_id)


def test_status_unknown_id_raises(manager) -> None:
    with pytest.raises(WorktreeError, match="unknown worktree"):
        manager.status("wt-nope-000000")


def test_diff_rejects_traversal_path(manager, git_repo: Path) -> None:
    info = manager.create_worktree(str(git_repo), task_id="trav")
    with pytest.raises(WorktreeError, match="unsafe diff path"):
        manager.diff(info["worktree_id"], path="../../etc/passwd")


def test_status_when_directory_missing(manager, git_repo: Path, tmp_path: Path) -> None:
    import shutil

    info = manager.create_worktree(str(git_repo), task_id="gone")
    shutil.rmtree(info["path"])
    with pytest.raises(WorktreeError, match="missing"):
        manager.status(info["worktree_id"])


def test_worktree_is_separate_directory(manager, git_repo: Path) -> None:
    info = manager.create_worktree(str(git_repo), task_id="sep")
    wt = Path(info["path"]).resolve()
    assert not str(wt).startswith(str(git_repo.resolve()))
    assert (wt / ".git").exists() or (wt / ".git").is_file()
    assert os.access(wt, os.W_OK)
