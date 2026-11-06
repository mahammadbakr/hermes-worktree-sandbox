"""Best-effort event push to connected Hermes Desktop / TUI clients."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

PLUGIN_ID = "worktree-sandbox"


def emit(event: str, payload: dict | None = None) -> None:
    """Broadcast ``plugin.<PLUGIN_ID>.<event>`` to every connected client; never raises.

    Delivery is fire-and-forget and a no-op when no Desktop/TUI client is attached (a plain
    `hermes chat`, cron, or the validator), which is exactly what we want.
    """
    try:
        from hermes_cli.plugin_events import broadcast_plugin_event

        broadcast_plugin_event(PLUGIN_ID, event, payload or {})
    except Exception:  # pragma: no cover - no client / older core
        logger.debug("worktree-sandbox: broadcast of %s failed", event, exc_info=True)
