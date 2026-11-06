"""Best-effort event push to connected Hermes Desktop / TUI clients."""

from __future__ import annotations

import importlib.util
import logging

logger = logging.getLogger(__name__)

PLUGIN_ID = "worktree-sandbox"

#: Whether this process can deliver a plugin event at all. ``broadcast_plugin_event`` logs a
#: warning **with a traceback** when there is no ``tui_gateway`` in the process (plain
#: ``hermes chat``, cron, the validator), so a plugin that emitted unconditionally would spam
#: every CLI session. Detected once and cached.
_GATEWAY_PRESENT: bool | None = None


def gateway_present() -> bool:
    global _GATEWAY_PRESENT
    if _GATEWAY_PRESENT is None:
        try:
            _GATEWAY_PRESENT = importlib.util.find_spec("tui_gateway.server") is not None
        except (ImportError, ValueError):
            _GATEWAY_PRESENT = False
    return _GATEWAY_PRESENT


def emit(event: str, payload: dict | None = None) -> None:
    """Broadcast ``plugin.<PLUGIN_ID>.<event>`` to every connected client; never raises.

    Delivery is fire-and-forget, and a silent no-op in a process with no gateway (a plain
    ``hermes chat``, cron, the validator) where there is nobody to deliver to.
    """
    if not gateway_present():
        return
    try:
        from hermes_cli.plugin_events import broadcast_plugin_event

        broadcast_plugin_event(PLUGIN_ID, event, payload or {})
    except Exception:  # pragma: no cover - no client / older core
        logger.debug("worktree-sandbox: broadcast of %s failed", event, exc_info=True)
