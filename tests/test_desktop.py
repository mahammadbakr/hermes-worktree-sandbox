"""Desktop surface checks.

Catalog rule 8: a ``desktop/plugin.js`` runs in the Desktop renderer with the app's authority, so a
listed plugin may only use the plugin SDK. These checks run the same lints Hermes runs at admission
(`hermes_cli.plugin_validate_desktop`), plus a static guard that works without a Hermes checkout.
"""

from __future__ import annotations

import re

import pytest
from helpers import HERMES_AVAILABLE, PLUGIN_DIR

DESKTOP_JS = PLUGIN_DIR / "desktop" / "plugin.js"


def test_desktop_plugin_exists() -> None:
    assert DESKTOP_JS.is_file(), f"missing {DESKTOP_JS}"


def test_only_sdk_imports() -> None:
    source = DESKTOP_JS.read_text(encoding="utf-8")
    specifiers = re.findall(r"from\s+['\"]([^'\"]+)['\"]", source)
    assert specifiers, "expected at least one import"
    allowed = {"@hermes/plugin-sdk", "react", "react/jsx-runtime"}
    assert set(specifiers) <= allowed, f"unexpected import specifiers: {set(specifiers) - allowed}"


def test_no_jsx_syntax() -> None:
    """Disk plugins load uncompiled, so JSX syntax would fail to parse."""
    source = DESKTOP_JS.read_text(encoding="utf-8")
    # A JSX element would be a bare `<Tag` or a closing `</Tag`; comparisons use spaces (`a < b`).
    assert not re.search(r"<[A-Za-z][\w.]*[\s/>]", source), "JSX syntax found in a disk plugin"


@pytest.mark.parametrize(
    "pattern,label",
    [
        (r"(?<![\w$.])eval\(", "eval("),
        (r"\bnew\s+Function\(", "new Function("),
        (r"\bimport\(", "dynamic import("),
        (r"<script\b", "<script"),
        (r"\bdocument\.(querySelector|getElementById|getElementsBy)", "document DOM reach"),
        (r"createElement\(\s*['\"]script", "script element creation"),
        (r"\b(?:window|globalThis)\.hermesDesktop\b", "raw hermesDesktop bridge"),
    ],
)
def test_forbidden_constructs_absent(pattern: str, label: str) -> None:
    source = DESKTOP_JS.read_text(encoding="utf-8")
    assert not re.search(pattern, source), f"found forbidden construct: {label}"


def test_disposes_its_own_timers_and_listeners() -> None:
    source = DESKTOP_JS.read_text(encoding="utf-8")
    assert "ctx.setInterval(" in source
    assert "ctx.onEvent(" in source
    assert "window.setInterval(" not in source
    assert "window.addEventListener(" not in source


def test_uses_theme_variables_not_hardcoded_colors() -> None:
    source = DESKTOP_JS.read_text(encoding="utf-8")
    hardcoded = re.findall(r"['\"]#[0-9a-fA-F]{3,8}['\"]|['\"]rgb\(", source)
    assert not hardcoded, f"hardcoded colors: {hardcoded[:5]}"
    assert "var(--ui-text-secondary)" in source


def test_default_enabled_is_false() -> None:
    """The desktop half ships opt-in; it inventories but stays off until the user enables it."""
    assert re.search(r"defaultEnabled:\s*false", DESKTOP_JS.read_text(encoding="utf-8"))


@pytest.mark.skipif(not HERMES_AVAILABLE, reason="Hermes Agent checkout not on sys.path")
def test_desktop_surface_lint_clean() -> None:
    from hermes_cli.plugin_validate_desktop import desktop_review_findings, desktop_surface_hits

    refusals = desktop_surface_hits(PLUGIN_DIR)
    assert refusals == [], "\n".join(refusals)
    cues = desktop_surface_hits(PLUGIN_DIR, desktop_review_findings)
    assert cues == [], "\n".join(cues)


@pytest.mark.skipif(not HERMES_AVAILABLE, reason="Hermes Agent checkout not on sys.path")
def test_dashboard_manifest_declares_api() -> None:
    import json

    manifest = json.loads((PLUGIN_DIR / "dashboard" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["name"] == "worktree-sandbox"
    assert manifest["api"] == "plugin_api.py"
    assert (PLUGIN_DIR / "dashboard" / manifest["api"]).is_file()
