"""worktree-sandbox — transactional Git-worktree terminal backend + inspection tools for Hermes Agent.

Wiring only: the heavy lifting lives in ``manager.py`` (Git worktrees), ``provider.py``
(``terminal.backend: worktree``) and ``tools.py`` (the ``worktree_*`` tools). ``register(ctx)`` is
called once at startup and must stay fast. Hermes-only imports live *inside* ``register`` so the
core modules (``manager``/``storage``/``security``) can be unit-tested without a Hermes checkout.
"""

from __future__ import annotations

import logging

from . import schemas
from .manager import WorktreeManager
from .storage import Ledger
from .tools import WorktreeTools

logger = logging.getLogger(__name__)

TOOLSET = "worktree"
_PROMPT_SECTION_ID = "worktree-sandbox"


def register(ctx) -> None:
    """Wire the terminal backend, system-prompt section and worktree tools."""
    from .provider import WorktreeSandboxProvider, prompt_note

    ledger = Ledger()
    manager = WorktreeManager(ledger)
    tools = WorktreeTools(manager=manager, ledger=ledger)

    # terminal.backend: worktree
    provider = WorktreeSandboxProvider(get_config=ctx.get_config, manager=manager)
    ctx.register_terminal_environment_provider(provider)

    # Tell the model where its commands actually run.
    ctx.register_system_prompt_section(_PROMPT_SECTION_ID, prompt_note)

    # Inspection + promotion tools (declared in plugin.yaml provides_tools).
    ctx.register_tool(
        name="worktree_create", toolset=TOOLSET, schema=schemas.WORKTREE_CREATE,
        handler=tools.worktree_create, emoji="\U0001F333",
        description="Create or reuse an isolated Git worktree for a task.",
    )
    ctx.register_tool(
        name="worktree_status", toolset=TOOLSET, schema=schemas.WORKTREE_STATUS,
        handler=tools.worktree_status, emoji="\U0001F4CB",
        description="List worktrees and their changed files with +add/-del stats.",
    )
    ctx.register_tool(
        name="worktree_diff", toolset=TOOLSET, schema=schemas.WORKTREE_DIFF,
        handler=tools.worktree_diff, emoji="\U0001F50D",
        description="Unified diff of a worktree against its base commit.",
    )
    ctx.register_tool(
        name="worktree_promote", toolset=TOOLSET, schema=schemas.WORKTREE_PROMOTE,
        handler=tools.worktree_promote, emoji="\u2705",
        description="Apply a worktree's changes back into the user's checkout.",
    )

    logger.debug("worktree-sandbox registered: %d tools", len(schemas.ALL_SCHEMAS))
