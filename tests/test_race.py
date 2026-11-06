"""Tests for the speculative race arena and the offline demo seed."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from worktree_sandbox.manager import WorktreeError
from worktree_sandbox.race import RaceRunner, demo_candidates, run_demo_race, score


@pytest.fixture
def runner(manager) -> RaceRunner:
    return RaceRunner(manager)


def test_score_prefers_correctness() -> None:
    assert score(True, 100, 1, 0, 1) > score(False, 1, 1, 0, 1)


def test_score_prefers_faster_and_smaller() -> None:
    assert score(True, 10, 1, 0, 1) > score(True, 500, 1, 0, 1)
    assert score(True, 10, 1, 0, 1) > score(True, 10, 400, 400, 40)


def test_race_picks_the_passing_candidate(runner: RaceRunner, git_repo: Path) -> None:
    result = runner.race(
        str(git_repo),
        [
            {"label": "good", "files": {"out.txt": "good\n"}},
            {"label": "bad", "files": {"out.txt": "bad\n"}},
        ],
        verify_command="grep -q good out.txt",
    )
    assert result["ok"] is True
    assert result["winner"] == "good"
    labels = {row["label"]: row for row in result["results"]}
    assert labels["good"]["passed"] is True
    assert labels["bad"]["passed"] is False
    assert labels["good"]["score"] > labels["bad"]["score"]
    # Candidate worktrees are discarded by default.
    assert runner.manager.list_worktrees(workspace=str(git_repo)) == []


def test_race_promotes_winner(runner: RaceRunner, git_repo: Path) -> None:
    result = runner.race(
        str(git_repo),
        [
            {"label": "keep", "files": {"chosen.txt": "chosen\n"}},
            {"label": "drop", "files": {"other.txt": "other\n"}},
        ],
        verify_command="test -f chosen.txt",
        promote_winner=True,
    )
    assert result["winner"] == "keep"
    assert (git_repo / "chosen.txt").read_text(encoding="utf-8") == "chosen\n"
    assert result["promoted"]["ok"] is True


def test_race_keeps_worktrees_when_asked(runner: RaceRunner, git_repo: Path) -> None:
    runner.race(
        str(git_repo),
        [{"label": "a", "files": {"a.txt": "a\n"}}, {"label": "b", "files": {"b.txt": "b\n"}}],
        verify_command="true", keep_worktrees=True,
    )
    assert len(runner.manager.list_worktrees(workspace=str(git_repo))) == 2


def test_race_rejects_too_few_candidates(runner: RaceRunner, git_repo: Path) -> None:
    with pytest.raises(WorktreeError, match="at least two candidates"):
        runner.race(str(git_repo), [{"label": "only", "files": {}}])


def test_race_rejects_too_many_candidates(runner: RaceRunner, git_repo: Path) -> None:
    candidates = [{"label": f"c{i}", "files": {}} for i in range(6)]
    with pytest.raises(WorktreeError, match="at most 5"):
        runner.race(str(git_repo), candidates)


def test_race_reports_unsafe_path(runner: RaceRunner, git_repo: Path) -> None:
    result = runner.race(
        str(git_repo),
        [{"label": "evil", "files": {"../escape.txt": "x"}}, {"label": "ok", "files": {"a.txt": "a"}}],
        verify_command="true",
    )
    evil = next(r for r in result["results"] if r["label"] == "evil")
    assert evil["error"] and "unsafe path" in evil["error"]
    assert result["winner"] == "ok"


def test_race_records_in_ledger(runner: RaceRunner, ledger, git_repo: Path) -> None:
    result = runner.race(
        str(git_repo),
        [{"label": "a", "files": {"a.txt": "a"}}, {"label": "b", "files": {"b.txt": "b"}}],
        verify_command="true",
    )
    record = ledger.get_race(result["race_id"])
    assert record is not None
    assert record["winner"] == result["winner"]
    assert record["result"]["results"]


def test_race_timeout_is_handled(runner: RaceRunner, git_repo: Path) -> None:
    result = runner.race(
        str(git_repo),
        [{"label": "slow", "files": {"a.txt": "a"}}, {"label": "fast", "files": {"b.txt": "b"}}],
        verify_command="sleep 4",
        timeout=5,
    )
    labels = {row["label"]: row for row in result["results"]}
    # Both sleep, so the race still completes with results (the timeout covers each candidate).
    assert set(labels) == {"slow", "fast"}
    assert all(row["exit_code"] is not None for row in labels.values())


def test_demo_race_is_offline_and_deterministic(runner: RaceRunner) -> None:
    result = run_demo_race(runner.manager)
    assert result["ok"] is True
    labels = {row["label"] for row in result["results"]}
    assert labels == {"quick-split", "careful"}
    # The arena must find the candidate that actually passes the test suite.
    by_label = {row["label"]: row for row in result["results"]}
    assert by_label["careful"]["passed"] is True
    assert by_label["quick-split"]["passed"] is False
    assert result["winner"] == "careful"
    assert result["verify_command"].endswith("-m unittest -q test_parser")


def test_demo_candidates_shape() -> None:
    candidates = demo_candidates()
    assert len(candidates) == 2
    assert all("parser.py" in c["files"] for c in candidates)


def test_demo_seed_files_exist(manager) -> None:
    from worktree_sandbox.race import seed_demo_project

    project = seed_demo_project(manager.data_dir / "demo" / "unit")
    assert (project / "parser.py").exists()
    assert (project / "test_parser.py").exists()
    assert sys.executable  # the demo verify command uses the running interpreter
