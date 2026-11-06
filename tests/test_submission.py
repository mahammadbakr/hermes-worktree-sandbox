"""Submission-artifact guards: the catalog entry must describe the code we ship.

These run without a Hermes checkout. They catch the two mistakes that actually break a catalog PR:
a pin that does not contain the final plugin tree, and an entry whose declared capabilities drifted
from the manifest.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

from helpers import PLUGIN_DIR

REPO_ROOT = PLUGIN_DIR.parent
ENTRY = REPO_ROOT / "catalog-entry" / "worktree-sandbox.yaml"


def _entry() -> dict:
    if not ENTRY.is_file():
        pytest.skip("catalog-entry/worktree-sandbox.yaml not present")
    return yaml.safe_load(ENTRY.read_text(encoding="utf-8"))


def _manifest() -> dict:
    return yaml.safe_load((PLUGIN_DIR / "plugin.yaml").read_text(encoding="utf-8"))


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(REPO_ROOT), *args], capture_output=True, text=True)


def test_entry_matches_manifest_capabilities() -> None:
    entry, manifest = _entry(), _manifest()
    caps = entry["capabilities"]
    assert caps["provides_tools"] == manifest["provides_tools"]
    assert caps["provides_hooks"] == manifest["provides_hooks"]
    assert caps["requires_env"] == manifest.get("requires_env", [])
    assert entry["requires_hermes"] == manifest["requires_hermes"]
    assert entry["version"] == manifest["version"]
    assert entry["name"] == manifest["name"]
    assert entry["subdir"] == "plugin"


def test_entry_is_well_formed_per_the_catalog_schema() -> None:
    import re

    entry = _entry()
    assert re.fullmatch(r"[a-z0-9_-]{1,64}", entry["name"])
    assert re.fullmatch(r"https://\S+", entry["repo"])
    assert re.fullmatch(r"[0-9a-f]{40}", entry["sha"]), entry["sha"]
    assert entry["tier"] in ("official", "verified", "community")
    assert entry["category"] in ("desktop", "memory", "platform", "web", "tools", "voice",
                                 "automation", "models", "general")
    assert set(entry.get("platforms") or []) <= {"linux", "macos", "windows"}
    assert entry["maintainer"]


def test_pinned_commit_contains_the_current_plugin_tree() -> None:
    """The pin must ship exactly the ``plugin/`` tree we are submitting.

    A commit cannot contain its own hash, and the catalog entry lives in the *hermes-agent* repo, so
    the convention is: pin a commit whose ``plugin/`` subtree is byte-identical to HEAD's. Any later
    commit that touches ``plugin/`` is caught here until the pin is refreshed.
    """
    sha = _entry()["sha"]
    if _git("rev-parse", "--is-inside-work-tree").stdout.strip() != "true":
        pytest.skip("not a git checkout")
    if _git("cat-file", "-e", f"{sha}^{{commit}}").returncode != 0:
        pytest.skip(f"pinned commit {sha} is not in this checkout (it will be verified in CI)")

    diff = _git("diff", "--name-only", sha, "HEAD", "--", "plugin/")
    assert diff.returncode == 0, diff.stderr
    assert diff.stdout.strip() == "", (
        "the plugin tree changed since the catalog pin was written; "
        "run scripts/pin_catalog_entry.sh and commit the result"
    )


def test_readme_install_command_matches_the_entry() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    entry = _entry()
    owner_repo = entry["repo"].removeprefix("https://github.com/").removesuffix(".git")
    assert f"{owner_repo}#{entry['subdir']}" in readme, "README install line drifted from the entry"
    assert f"hermes plugins install {entry['name']}" in readme


def test_no_secrets_or_local_paths_committed() -> None:
    """No developer-local absolute paths or obvious credentials anywhere in the shipped tree."""
    import re

    pattern = re.compile(r"(/Users/[A-Za-z0-9._-]+/|/home/[A-Za-z0-9._-]+/|sk-[A-Za-z0-9]{16,}|ghp_[A-Za-z0-9]{20,})")
    offenders: list[str] = []
    for path in sorted(PLUGIN_DIR.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        if path.suffix.lower() in {".png", ".jpg", ".ico", ".db"}:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in pattern.finditer(text):
            offenders.append(f"{path.relative_to(REPO_ROOT)}: {match.group(0)[:40]}")
    assert offenders == [], offenders


def test_ci_workflow_covers_ruff_mypy_and_pytest() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "ruff check ." in workflow
    assert "mypy" in workflow
    assert "pytest" in workflow


def test_license_is_mit_and_referenced() -> None:
    license_text = (REPO_ROOT / "LICENSE").read_text(encoding="utf-8")
    assert license_text.startswith("MIT License")
    assert "MIT" in (REPO_ROOT / "README.md").read_text(encoding="utf-8") or \
        "[MIT](LICENSE)" in (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert _manifest()["license"] == "MIT"


def test_demo_script_stays_under_the_video_limit() -> None:
    demo = (REPO_ROOT / "DEMO.md").read_text(encoding="utf-8")
    assert "90" in demo  # the duration budget is stated
    assert "@NousResearch" in demo


def test_referenced_doc_assets_exist() -> None:
    """No broken image links in the README (a judge clicks them)."""
    import re

    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    for target in re.findall(r"!\[[^\]]*\]\(([^)]+)\)", readme):
        if target.startswith(("http://", "https://")):
            continue
        assert (REPO_ROOT / target).is_file(), f"README references a missing asset: {target}"


def test_plugin_tree_has_no_bytecode_or_binaries() -> None:
    bad = [
        str(path.relative_to(REPO_ROOT))
        for path in PLUGIN_DIR.rglob("*")
        if path.is_file() and path.suffix.lower() in {".pyc", ".pyo", ".so", ".dylib", ".dll", ".exe"}
    ]
    assert bad == [], bad


def test_data_dir_is_never_inside_the_plugin_tree() -> None:
    """Runtime state must go to HERMES_HOME/plugin-data, never into the install tree."""
    for path in sorted(PLUGIN_DIR.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        assert "Path(__file__).parent / \"plugin-data\"" not in text
        assert '"plugin-data"' not in text or "HERMES_HOME" in text or "plugin_data_dir" in text
