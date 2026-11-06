"""Real Hermes admission validation — runs the same checks catalog CI runs.

Requires a Hermes Agent checkout (``HERMES_AGENT_REPO``).
"""

from __future__ import annotations

import json

import pytest
from helpers import HERMES_AVAILABLE, PLUGIN_DIR

pytestmark = pytest.mark.skipif(
    not HERMES_AVAILABLE, reason="Hermes Agent checkout not on sys.path (set HERMES_AGENT_REPO)"
)


@pytest.fixture(scope="module")
def report():
    from hermes_cli.plugin_validate import validate_plugin_dir

    return validate_plugin_dir(PLUGIN_DIR)


def test_validation_passes(report) -> None:
    assert report.ok, json.dumps(report.to_dict(), indent=2)
    failed = [name for name, ok, _detail in report.checks if not ok]
    assert failed == []


def test_declared_capabilities_match_registrations(report) -> None:
    checks = {name: (ok, detail) for name, ok, detail in report.checks}
    for kind in ("declared tools", "declared hooks", "declared middleware"):
        assert kind in checks, checks.keys()
        ok, detail = checks[kind]
        assert ok, f"{kind}: {detail}"


def test_no_private_core_import_warnings(report) -> None:
    offenders = [w for w in report.warnings if "private core" in w]
    assert offenders == [], "\n".join(offenders)


def test_no_desktop_surface_violations(report) -> None:
    checks = {name: (ok, detail) for name, ok, detail in report.checks}
    if "desktop surface" in checks:
        ok, detail = checks["desktop surface"]
        assert ok, detail


def test_security_scan_not_dangerous(report) -> None:
    checks = {name: (ok, detail) for name, ok, detail in report.checks}
    if "security scan" in checks:
        ok, detail = checks["security scan"]
        assert ok, detail
