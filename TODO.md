# TODO — `hermes-worktree-sandbox`

## Milestone 0: Research, Plan & Repository Scaffold
- [x] Research Hermes plugin developer guide, 19 sub-guides, and 1,063 catalog plugins (`RESEARCH.md`)
- [x] Select Idea 1 (`hermes-worktree-sandbox`) and write `PLAN.md`
- [x] Create git repository scaffold (`LICENSE`, `.gitignore`, `.env.example`, `pytest.ini`, `.github/workflows/ci.yml`, `CHANGELOG.md`, `TODO.md`, `DEMO.md`, `README.md`, `plugin.yaml`)

## Milestone 1: Vertical Slice (Core Provider, Worktree Engine & SQLite Ledger) — DONE
- [x] Implement `plugin/storage.py`: WAL-mode SQLite ledger tracking worktree sessions, mutation events, and races
- [x] Implement `plugin/manager.py`: `WorktreeManager` with real `git worktree` lifecycle, diff/stat calculation, conflict-safe promotion with `.bak` backups, discard, and pruning
- [x] Implement `plugin/provider.py`: `WorktreeSandboxProvider(TerminalEnvironmentProvider)` + `WorktreeEnvironment(BaseEnvironment)` (`uses_host_filesystem = False`, secret env stripping, isolated `TMPDIR`, host-cwd remapping, `is_available()`, `probe()`, `doctor_checks()`, `setup_instructions()`)
- [x] Implement `plugin/schemas.py`, `plugin/tools.py`, and `plugin/__init__.py` (`register(ctx)`)
- [x] Add `plugin/security.py` (credential-env scrubbing, sensitive-filename filter, path/id validation)
- [x] Verify: 103 tests pass, Ruff clean, `hermes plugins validate` equivalent passes with 0 errors / 0 warnings, `scripts/vertical_slice.py` passes against a real Hermes `PluginManager`
- [ ] Deferred to M2: shadow-Git fallback for non-Git directories (currently a clear error)

**Milestone 1 notes / risks:**
- The plugin lives in `plugin/` and the catalog entry will carry `subdir: plugin`. This keeps the repo
  root out of pytest's package chain (a dashed directory name cannot be a Python package) and matches
  the catalog's own monorepo pattern. Manual install: `hermes plugins install <owner>/<repo>#plugin`.
- Hermes's terminal tool passes the *session* cwd to `execute()`; the environment remaps any host
  path under the workspace into the worktree (regression-tested). Without it isolation silently failed.
- Isolation is **working-tree isolation**, not an OS sandbox: `bubblewrap` remains the plugin for
  kernel-level confinement. Documented in the README.

## Milestone 2: Speculative Race Arena, Hooks & Slash/CLI Commands — DONE
- [x] Implement `plugin/race.py`: `worktree_race` parallel evaluator (thread pool, hard timeouts with process-group kill, deterministic scoring) + built-in offline demo seed (`run_demo_race`)
- [x] Implement shadow-Git fallback for non-Git workspaces (`plugin/shadow.py`) with credential/binary/artifact exclusion and promotion back into the real folder
- [x] Implement `plugin/hooks.py`: `on_session_start`, `post_tool_call` (throttled, emits Desktop events), `pre_verify` (optional verification gate), `on_session_finalize` (bounded prune)
- [x] Implement `plugin/cli.py`: `/sandbox` slash command (interactive picker, unattended-safe) and `hermes worktree` CLI
- [x] Serialize Git mutations so parallel race candidates cannot collide on `git worktree add`
- [x] Exclude build artifacts and credential-shaped files from change reports, diffs and promotion
- [x] 148 tests pass, Ruff clean, `hermes plugins validate` passes with 0 errors / 0 warnings, vertical slice passes in real Hermes

**Milestone 2 notes / risks:**
- **Name collision found and fixed:** Hermes already ships a built-in `/worktree` slash command
  (session worktrees), so the plugin registers `/sandbox` instead. `hermes worktree` (CLI) is free.
- The demo was originally framed as "regex vs state machine, faster wins". That was wrong — a Python
  state machine is *slower* than C `re.findall`, so the demo now races on **correctness**, which is
  the real value prop ("the arena found the implementation that passes your tests").

## Milestone 3: Unified Desktop UI (`desktop/plugin.js`) & FastAPI Backend (`dashboard/plugin_api.py`)
- [ ] `dashboard/manifest.json` + `dashboard/plugin_api.py` (`/api/plugins/worktree-sandbox/*`)
- [ ] `desktop/plugin.js`: docked Worktree/Arena pane, status-bar diff chip, ⌘K commands, `::worktree-card` transcript directive
- [ ] Verify `check_desktop_surface` passes with zero errors and zero warnings

## Milestone 4: End-to-End Integration Tests, Documentation Polish & Catalog Entry
- [ ] Write `tests/test_hermes_integration.py` running `validate_plugin_dir`, `scan_plugin_payloads.py`, and `validate_plugin_catalog.py`
- [ ] Generate `catalog-entry/worktree-sandbox.yaml` ready for PR submission to `NousResearch/hermes-agent`
- [ ] Finalize `README.md` with complete quickstart, architecture, configuration reference, security disclosure, and troubleshooting
