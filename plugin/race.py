"""Speculative race arena: run competing changes in parallel worktrees and score them.

Each candidate gets its own isolated worktree. Changes are applied (from ``files`` and/or a
``command``), an optional verification command runs with a hard timeout and process-group kill,
and every candidate is scored on: did verification pass, how fast, and how small the diff is.
The winner can be promoted back into the user's checkout in the same call.

Everything is local and offline. ``run_demo_race`` seeds a self-contained project so a live demo
never depends on the network, a model call, or the user's own repository.
"""

from __future__ import annotations

import concurrent.futures
import os
import shlex
import shutil
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from .manager import WorktreeError, WorktreeManager
from .security import confine_to_root, is_safe_relative_path, sanitize_env
from .storage import Ledger

_MAX_OUTPUT_TAIL = 1200
_DEFAULT_TIMEOUT = 120


def _tail(text: str, limit: int = _MAX_OUTPUT_TAIL) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else "..." + text[-limit:]


def _run_bounded(cwd: Path, command: str, timeout: int) -> dict[str, Any]:
    """Run *command* in *cwd* with a timeout; kill the whole process group on expiry."""
    started = time.monotonic()
    env = sanitize_env(os.environ)
    env["GIT_PAGER"] = "cat"
    env["PAGER"] = "cat"
    try:
        proc = subprocess.Popen(
            ["bash", "-c", command], cwd=str(cwd), env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace",
            start_new_session=True,
        )
    except OSError as exc:
        return {"passed": False, "exit_code": None, "output": f"could not start: {exc}",
                "duration_ms": int((time.monotonic() - started) * 1000), "timed_out": False}

    timed_out = False
    try:
        output, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except OSError:
            proc.kill()
        try:
            output, _ = proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover - unkillable child
            output = ""
    duration_ms = int((time.monotonic() - started) * 1000)
    return {
        "passed": (not timed_out) and proc.returncode == 0,
        "exit_code": proc.returncode,
        "output": _tail(output),
        "duration_ms": duration_ms,
        "timed_out": timed_out,
    }


def score(passed: bool, duration_ms: int, added: int, deleted: int, changed_files: int) -> float:
    """Deterministic composite score: correctness dominates, then speed, minus diff sprawl."""
    base = 1000.0 if passed else 0.0
    speed = max(0.0, 200.0 - (duration_ms / 10.0))
    sprawl = min(100.0, changed_files * 2.0 + (added + deleted) / 20.0)
    return round(base + speed - sprawl, 2)


class RaceRunner:
    def __init__(self, manager: WorktreeManager, ledger: Ledger | None = None) -> None:
        self.manager = manager
        self.ledger = ledger or manager.ledger

    # -- public ----------------------------------------------------------------

    def race(
        self, workspace: str | None, candidates: list[dict[str, Any]], *,
        verify_command: str | None = None, timeout: int = _DEFAULT_TIMEOUT,
        promote_winner: bool = False, keep_worktrees: bool = False,
        label: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(candidates, list) or len(candidates) < 2:
            raise WorktreeError("worktree_race needs at least two candidates")
        if len(candidates) > 5:
            raise WorktreeError("worktree_race accepts at most 5 candidates")

        try:
            limit = max(5, min(int(timeout), 900))
        except (TypeError, ValueError):
            limit = _DEFAULT_TIMEOUT

        race_id = f"race-{uuid.uuid4().hex[:10]}"
        prepared: list[dict[str, Any]] = []
        for index, candidate in enumerate(candidates):
            if not isinstance(candidate, dict):
                raise WorktreeError(f"candidate {index} must be an object")
            files = candidate.get("files") or {}
            if not isinstance(files, dict):
                raise WorktreeError(f"candidate {index}: 'files' must be an object of path -> content")
            for rel, content in files.items():
                if not isinstance(rel, str) or not rel.strip():
                    raise WorktreeError(f"candidate {index}: file keys must be non-empty strings")
                if not isinstance(content, str):
                    raise WorktreeError(
                        f"candidate {index}: content for {rel!r} must be a string, "
                        f"got {type(content).__name__}")
            prepared.append({
                "label": str(candidate.get("label") or f"candidate-{index + 1}")[:40],
                "files": files,
                "command": candidate.get("command") or None,
                "setup_command": candidate.get("setup_command") or None,
            })

        started = time.monotonic()
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(prepared))) as pool:
            futures = {
                pool.submit(self._run_candidate, workspace, race_id, index, cand, verify_command, limit):
                    (index, cand)
                for index, cand in enumerate(prepared)
            }
            results: list[dict[str, Any]] = []
            for future in concurrent.futures.as_completed(futures):
                results.append(future.result())

        results.sort(key=lambda r: (-r["score"], r["duration_ms"], r["label"]))
        winner = results[0] if results else None
        promoted = None
        if promote_winner and winner and winner.get("worktree_id") and winner.get("passed"):
            try:
                promoted = self.manager.promote(winner["worktree_id"])
            except WorktreeError as exc:
                promoted = {"ok": False, "error": str(exc)}

        if not keep_worktrees:
            for result in results:
                if result.get("worktree_id") and not (promoted and result is winner):
                    try:
                        self.manager.discard(result["worktree_id"])
                    except WorktreeError:
                        pass

        payload: dict[str, Any] = {
            "ok": True,
            "race_id": race_id,
            "label": label,
            "winner": winner["label"] if winner else None,
            "winner_score": winner["score"] if winner else None,
            "verify_command": verify_command,
            "duration_ms": int((time.monotonic() - started) * 1000),
            "results": results,
            "promoted": promoted,
        }
        self.ledger.record_race(
            race_id=race_id, workspace=str(workspace or ""),
            spec={"candidates": [c["label"] for c in prepared], "verify_command": verify_command},
            result={"results": results}, winner=payload["winner"],
        )
        self.ledger.record_event(winner.get("worktree_id") if winner else None, "race.completed", {
            "race_id": race_id, "winner": payload["winner"],
        })
        return payload

    # -- internals -------------------------------------------------------------

    def _run_candidate(
        self, workspace: str | None, race_id: str, index: int, candidate: dict[str, Any],
        verify_command: str | None, timeout: int,
    ) -> dict[str, Any]:
        label = candidate["label"]
        result: dict[str, Any] = {
            "label": label, "worktree_id": None, "passed": False, "exit_code": None,
            "duration_ms": 0, "added": 0, "deleted": 0, "changed_files": 0,
            "score": 0.0, "error": None, "output": "", "timed_out": False,
        }
        try:
            info = self.manager.create_worktree(
                workspace, task_id=f"{race_id}-{index}-{label}", reuse=False)
        except WorktreeError as exc:
            result["error"] = str(exc)
            return result

        result["worktree_id"] = info["worktree_id"]
        wt = Path(info["path"])

        # 1. Apply declarative file changes.
        try:
            for rel, content in (candidate["files"] or {}).items():
                if not is_safe_relative_path(rel):
                    raise WorktreeError(f"candidate {label}: unsafe path {rel!r}")
                target = confine_to_root(wt, rel)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(str(content), encoding="utf-8")
        except (WorktreeError, OSError) as exc:
            result["error"] = f"could not apply files: {exc}"
            return result

        # 2. Optional setup command (e.g. install deps / scaffold).
        if candidate["setup_command"]:
            setup = _run_bounded(wt, candidate["setup_command"], timeout)
            if not setup["passed"]:
                result.update(error="setup command failed", output=setup["output"],
                              exit_code=setup["exit_code"], timed_out=setup["timed_out"])
                return result

        # 3. Candidate command (e.g. the agent's own edit script).
        if candidate["command"]:
            run = _run_bounded(wt, candidate["command"], timeout)
            result.update(exit_code=run["exit_code"], output=run["output"], timed_out=run["timed_out"])
            if not run["passed"]:
                result["error"] = "candidate command failed"
                self._fill_stats(result, info["worktree_id"])
                result["score"] = score(False, run["duration_ms"], result["added"],
                                        result["deleted"], result["changed_files"])
                result["duration_ms"] = run["duration_ms"]
                return result

        # 4. Verification (the thing that decides pass/fail).
        if verify_command:
            run = _run_bounded(wt, verify_command, timeout)
            result.update(
                passed=run["passed"], exit_code=run["exit_code"], output=run["output"],
                duration_ms=run["duration_ms"], timed_out=run["timed_out"],
            )
        else:
            result.update(passed=True, duration_ms=0)

        self._fill_stats(result, info["worktree_id"])
        result["score"] = score(result["passed"], result["duration_ms"], result["added"],
                               result["deleted"], result["changed_files"])
        return result

    def _fill_stats(self, result: dict[str, Any], worktree_id: str) -> None:
        try:
            status = self.manager.status(worktree_id)
            result["added"] = status["added"]
            result["deleted"] = status["deleted"]
            result["changed_files"] = status["changed_files"]
        except WorktreeError:
            pass


# --------------------------------------------------------------------------- #
# Demo seed — a self-contained, offline race used by `/worktree demo`
# --------------------------------------------------------------------------- #

_DEMO_BASE_PARSER = '''"""Tiny header parser (the version with a bug to fix)."""


def parse_header(line):
    items = {}
    for part in line.split(";"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        items[key] = value
    return items
'''

_DEMO_TEST = '''import unittest

from parser import parse_header


class ParseHeaderTests(unittest.TestCase):
    def test_simple(self):
        self.assertEqual(parse_header("a=1; b=2"), {"a": "1", "b": "2"})

    def test_ignores_noise(self):
        self.assertEqual(parse_header(" a = 1 ;; junk; b=2 "), {"a": "1", "b": "2"})

    def test_empty(self):
        self.assertEqual(parse_header(""), {})

    def test_mixed_case_keys(self):
        self.assertEqual(parse_header("Content-Type=text/plain"), {"content-type": "text/plain"})

    def test_repeated_keys_last_wins(self):
        self.assertEqual(parse_header("a=1; a=2"), {"a": "2"})

    def test_value_may_contain_equals(self):
        self.assertEqual(parse_header("token=a=b"), {"token": "a=b"})


class ThroughputTests(unittest.TestCase):
    def test_throughput(self):
        parse_header("a=1; b=2; c=3")
        for _ in range(2000):
            parse_header("alpha=1; beta=2; gamma=3")
'''

# Candidate A: the obvious tidy-up. Trims keys and skips junk, but never normalises key case.
_DEMO_TRIM_ONLY = '''"""Candidate A: trims and skips noise, but keeps key case as written."""


def parse_header(line):
    items = {}
    for part in line.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        key, value = part.split("=", 1)
        items[key.strip()] = value
    return items
'''

# Candidate B: also normalises key case and trims values, so every test passes.
_DEMO_CAREFUL = '''"""Candidate B: trims, drops noise, normalises key case and keeps "=" in values."""


def parse_header(line):
    items = {}
    for part in line.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        key, _, value = part.partition("=")
        items[key.strip().lower()] = value.strip()
    return items
'''


def seed_demo_project(root: Path) -> Path:
    """Write the demo project into *root* (idempotent) and return its path."""
    project = Path(root)
    project.mkdir(parents=True, exist_ok=True)
    (project / "parser.py").write_text(_DEMO_BASE_PARSER, encoding="utf-8")
    (project / "test_parser.py").write_text(_DEMO_TEST, encoding="utf-8")
    return project


def demo_candidates() -> list[dict[str, Any]]:
    return [
        {"label": "trim-only", "files": {"parser.py": _DEMO_TRIM_ONLY}},
        {"label": "careful", "files": {"parser.py": _DEMO_CAREFUL}},
    ]


def demo_verify_command() -> str:
    return f"{shlex.quote(sys.executable)} -m unittest -q test_parser"


def run_demo_race(manager: WorktreeManager, *, keep_worktrees: bool = False, keep_projects: int = 3) -> dict[str, Any]:
    """Run the built-in offline demo race and return its result.

    Seeded projects are trimmed to the newest ``keep_projects`` so repeated demos cannot grow the
    plugin data directory without bound.
    """
    _trim_demo_projects(manager, keep=keep_projects)
    stamp = time.strftime("%Y%m%d-%H%M%S") + f"-{uuid.uuid4().hex[:4]}"
    demo_root = manager.data_dir / "demo" / stamp
    project = seed_demo_project(demo_root)
    _trim_demo_projects(manager, keep=keep_projects)
    runner = RaceRunner(manager)
    result = runner.race(
        str(project), demo_candidates(),
        verify_command=demo_verify_command(), timeout=120,
        keep_worktrees=keep_worktrees, label="demo",
    )
    result["project"] = str(project)
    return result


def _trim_demo_projects(manager: WorktreeManager, *, keep: int) -> int:
    """Delete all but the newest *keep* seeded demo projects; returns how many were removed."""
    root = manager.data_dir / "demo"
    if not root.is_dir():
        return 0
    try:
        children = sorted((c for c in root.iterdir() if c.is_dir()), key=lambda c: c.name)
    except OSError:
        return 0
    removed = 0
    for child in children[:-max(1, keep)]:
        shutil.rmtree(child, ignore_errors=True)
        removed += 1
    return removed


def purge_demo_projects(manager: WorktreeManager) -> int:
    """Remove every seeded demo project (used by `hermes worktree demo --reset`)."""
    root = manager.data_dir / "demo"
    if not root.is_dir():
        return 0
    removed = 0
    for child in root.iterdir():
        if child.is_dir():
            shutil.rmtree(child, ignore_errors=True)
            removed += 1
    return removed
