"""Tests for the `/worktree` slash command and `hermes worktree` CLI dispatch."""

from __future__ import annotations

import argparse
from pathlib import Path

from worktree_sandbox.cli import USAGE, WorktreeCommands, make_cli_handler, make_slash_handler, setup_parser


def _commands(manager) -> WorktreeCommands:
    return WorktreeCommands(manager)


def test_status_with_no_worktrees_is_helpful(manager) -> None:
    text = _commands(manager).status()
    assert "No managed worktrees" in text
    assert "demo" in text


def test_status_lists_worktrees(manager, git_repo: Path) -> None:
    info = manager.create_worktree(str(git_repo), task_id="cli")
    (Path(info["path"]) / "x.txt").write_text("x\n", encoding="utf-8")
    text = _commands(manager).status(str(git_repo))
    assert info["worktree_id"] in text
    assert "dirty" in text


def test_diff_output(manager, git_repo: Path) -> None:
    info = manager.create_worktree(str(git_repo), task_id="clidiff")
    (Path(info["path"]) / "x.txt").write_text("hello\n", encoding="utf-8")
    text = _commands(manager).diff(info["worktree_id"])
    assert "hello" in text


def test_promote_output_includes_backup(manager, git_repo: Path) -> None:
    info = manager.create_worktree(str(git_repo), task_id="clipromote")
    (Path(info["path"]) / "x.txt").write_text("hello\n", encoding="utf-8")
    text = _commands(manager).promote(info["worktree_id"])
    assert "Promoted" in text
    assert (git_repo / "x.txt").exists()


def test_promote_conflict_message_suggests_force(manager, git_repo: Path) -> None:
    info = manager.create_worktree(str(git_repo), task_id="cliconflict")
    (Path(info["path"]) / "app.py").write_text("wt\n", encoding="utf-8")
    (git_repo / "app.py").write_text("host\n", encoding="utf-8")
    text = _commands(manager).promote(info["worktree_id"])
    assert "REFUSED" in text
    assert "--force" in text


def test_discard_and_prune_output(manager, git_repo: Path) -> None:
    info = manager.create_worktree(str(git_repo), task_id="clidiscard")
    assert "Discarded" in _commands(manager).discard(info["worktree_id"])
    assert "Nothing to prune" in _commands(manager).prune(5)


def test_demo_command_reports_leaderboard(manager) -> None:
    text = _commands(manager).demo()
    assert "Demo race complete" in text
    assert "careful" in text
    assert "quick-split" in text
    assert "winner: careful" in text


def test_dispatch_unknown_verb(manager) -> None:
    text = _commands(manager).dispatch("frobnicate", [])
    assert "Unknown verb" in text


def test_dispatch_help(manager) -> None:
    assert _commands(manager).dispatch("help", []) == USAGE


def test_dispatch_error_is_user_facing(manager) -> None:
    text = _commands(manager).dispatch("diff", ["wt-missing-000000"])
    assert text.startswith("worktree:")


def test_slash_handler_unattended_missing_id_returns_usage(manager) -> None:
    class Ctx:
        def ask_choice(self, question, choices):
            return None

    handler = make_slash_handler(Ctx(), _commands(manager))
    assert handler("diff") == USAGE


def test_slash_handler_uses_picker(manager, git_repo: Path) -> None:
    info = manager.create_worktree(str(git_repo), task_id="pick")
    (Path(info["path"]) / "x.txt").write_text("x\n", encoding="utf-8")

    class Ctx:
        def ask_choice(self, question, choices):
            assert choices and choices[0]["value"] == info["worktree_id"]
            return choices[0]["value"]

    handler = make_slash_handler(Ctx(), _commands(manager))
    text = handler("diff")
    assert info["worktree_id"] in text


def test_slash_handler_bare_returns_status(manager) -> None:
    handler = make_slash_handler(type("C", (), {"ask_choice": lambda *_: None})(), _commands(manager))
    assert "worktrees" in handler("").lower()


def test_slash_handler_never_raises(manager) -> None:
    handler = make_slash_handler(type("C", (), {"ask_choice": lambda *_: None})(), _commands(manager))
    assert isinstance(handler("promote"), str)


def test_cli_parser_and_handler(manager, git_repo: Path, capsys) -> None:
    info = manager.create_worktree(str(git_repo), task_id="cli-parser")
    (Path(info["path"]) / "x.txt").write_text("x\n", encoding="utf-8")

    parser = argparse.ArgumentParser(prog="hermes worktree")
    setup_parser(parser)  # Hermes hands setup_fn the plugin's own subparser
    handler = make_cli_handler(_commands(manager))

    args = parser.parse_args(["status", "--workspace", str(git_repo)])
    assert handler(args) == 0
    out = capsys.readouterr().out
    assert info["worktree_id"] in out

    args = parser.parse_args(["promote", info["worktree_id"]])
    assert handler(args) == 0
    assert "Promoted" in capsys.readouterr().out


def test_cli_demo_flag(manager, capsys) -> None:
    parser = argparse.ArgumentParser(prog="hermes worktree")
    setup_parser(parser)
    handler = make_cli_handler(_commands(manager))
    args = parser.parse_args(["demo", "--reset"])
    assert handler(args) == 0
    assert "Demo race complete" in capsys.readouterr().out
