"""Test helpers shared by ``conftest.py`` and the test modules.

Lives in its own module so test files can ``from helpers import HERMES_AVAILABLE`` without
re-executing ``conftest.py``. ``pythonpath = tests`` in ``pytest.ini`` makes it importable under
``--import-mode=importlib`` (required because this repo's root directory name contains a dash,
which pytest's default ``prepend`` import mode cannot turn into a package name).
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

PLUGIN_DIR = Path(__file__).resolve().parents[1] / "plugin"
PACKAGE_NAME = "worktree_sandbox"

# Optional: point at a Hermes Agent checkout so the integration tests can run.
_HERMES_REPO = os.environ.get("HERMES_AGENT_REPO", "")
if _HERMES_REPO and _HERMES_REPO not in sys.path:
    sys.path.insert(0, _HERMES_REPO)

try:  # pragma: no cover - environment probe
    import agent.terminal_env_provider  # noqa: F401

    HERMES_AVAILABLE = True
except Exception:  # pragma: no cover
    HERMES_AVAILABLE = False


def load_plugin_package():
    """Load the plugin as a package, the way Hermes loads a directory plugin."""
    spec = importlib.util.spec_from_file_location(
        PACKAGE_NAME, PLUGIN_DIR / "__init__.py", submodule_search_locations=[str(PLUGIN_DIR)]
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[PACKAGE_NAME] = module
    spec.loader.exec_module(module)
    return module


plugin_pkg = load_plugin_package()

HERMES_SKIP_REASON = "Hermes Agent checkout not on sys.path (set HERMES_AGENT_REPO)"


def require_hermes() -> None:
    if not HERMES_AVAILABLE:
        pytest.skip(HERMES_SKIP_REASON, allow_module_level=True)


def require_git() -> None:
    import shutil

    if shutil.which("git") is None:
        pytest.skip("git is not on PATH")
