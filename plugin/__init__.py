"""worktree-sandbox — transactional Git-worktree terminal backend + speculative arena for Hermes Agent.

Wiring only: the heavy lifting lives in ``manager.py`` (Git worktrees), ``provider.py``
(``terminal.backend: worktree``), ``race.py`` (the speculative arena), ``hooks.py`` (lifecycle) and
``cli.py`` (``/sandbox`` + ``hermes sandbox``). ``register(ctx)`` is called once at startup and must
stay fast. Hermes-only imports live *inside* ``register`` so the core modules can be unit-tested
without a Hermes checkout.
"""

from __future__ import annotations

import logging
from pathlib import Path

from . import schemas
from .cli import WorktreeCommands, make_cli_handler, make_slash_handler, setup_parser
from .hooks import HookHandlers
from .manager import WorktreeManager
from .storage import Ledger
from .tools import WorktreeTools

logger = logging.getLogger(__name__)

TOOLSET = "worktree"
_PROMPT_SECTION_ID = "worktree-sandbox"


def register(ctx) -> None:
    """Wire the terminal backend, system-prompt section, tools, hooks and commands."""
    from .provider import WorktreeSandboxProvider, prompt_note

    ledger = Ledger()
    manager = WorktreeManager(ledger)
    tools = WorktreeTools(manager=manager, ledger=ledger)
    commands = WorktreeCommands(manager, ledger)
    hooks = HookHandlers(manager, ledger, get_config=ctx.get_config)

    # terminal.backend: worktree — tell the provider about new worktrees so hooks can find them.
    provider = WorktreeSandboxProvider(
        get_config=ctx.get_config, manager=manager, on_created=hooks.on_worktree_created)
    ctx.register_terminal_environment_provider(provider)

    # Tell the model where its commands actually run.
    ctx.register_system_prompt_section(_PROMPT_SECTION_ID, prompt_note)

    # Ship the workflow guide so the agent knows how to use the arena and the directive.
    try:
        skill_md = Path(__file__).parent / "skills" / "worktree-sandbox" / "SKILL.md"
        if skill_md.is_file():
            ctx.register_skill(
                "worktree-sandbox", skill_md,
                "Isolate edits in a Git worktree, review/promote the diff, and race competing solutions.")
    except Exception:  # pragma: no cover - a skill is a bonus, never a load failure
        logger.debug("worktree-sandbox: bundled skill not registered", exc_info=True)

    # Tools (declared 1:1 in plugin.yaml provides_tools).
    registrations = (
        ("worktree_create", schemas.WORKTREE_CREATE, tools.worktree_create, "\U0001F333",
         "Create or reuse an isolated Git worktree for a task."),
        ("worktree_status", schemas.WORKTREE_STATUS, tools.worktree_status, "\U0001F4CB",
         "List worktrees and their changed files with +add/-del stats."),
        ("worktree_diff", schemas.WORKTREE_DIFF, tools.worktree_diff, "\U0001F50D",
         "Unified diff of a worktree against its base commit."),
        ("worktree_promote", schemas.WORKTREE_PROMOTE, tools.worktree_promote, "\u2705",
         "Apply a worktree's changes back into the user's checkout."),
        ("worktree_race", schemas.WORKTREE_RACE, tools.worktree_race, "\U0001F3C1",
         "Race competing solutions in parallel worktrees, verify and score them."),
    )
    for name, schema, handler, emoji, description in registrations:
        ctx.register_tool(name=name, toolset=TOOLSET, schema=schema, handler=handler,
                          emoji=emoji, description=description)

    # Lifecycle hooks (declared 1:1 in plugin.yaml provides_hooks).
    # pre_tool_call is the approval gate for our own privileged tools: it escalates
    # worktree_race (model-written commands) and worktree_promote (writes into the real project)
    # to Hermes' human-approval prompt.
    ctx.register_hook("pre_tool_call", hooks.pre_tool_call)
    ctx.register_hook("on_session_start", hooks.on_session_start)
    ctx.register_hook("post_tool_call", hooks.post_tool_call)
    ctx.register_hook("pre_verify", hooks.pre_verify)
    ctx.register_hook("on_session_finalize", hooks.on_session_finalize)

    # In-session slash command (CLI, TUI, Desktop and every messaging gateway).
    # NOTE: Hermes ships its own `/worktree` (session worktrees), so we register `/sandbox`.
    ctx.register_command(
        "sandbox", make_slash_handler(ctx, commands),
        description="Inspect, promote or discard isolated worktrees; run the demo race",
        args_hint="[status|list|diff <id>|promote <id>|discard <id>|prune|demo]",
    )

    # `hermes sandbox ...`
    # NOTE: core already owns `hermes worktree` (session-worktree audit/reclaim), so the CLI
    # command shares the slash command's name instead.
    ctx.register_cli_command(
        name="sandbox", help="Manage isolated Git worktrees and run the demo race",
        setup_fn=setup_parser, handler_fn=make_cli_handler(commands),
        description="Inspect and promote isolated Git worktrees created by terminal.backend: worktree.",
    )

    logger.debug("worktree-sandbox registered: %d tools, 4 hooks, /sandbox + hermes sandbox",
                 len(schemas.ALL_SCHEMAS))
