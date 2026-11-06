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

## Milestone 2: Speculative Race Arena, Hooks & Slash/CLI Commands
- [ ] Implement `worktree_race` parallel multi-worktree candidate evaluator + built-in demo seed (`run_demo_race`)
- [ ] Implement shadow-Git fallback for non-Git workspaces
- [ ] Implement lifecycle hooks (`on_session_start`, `post_tool_call`, `pre_verify`, `on_session_finalize`) with live `broadcast_plugin_event` notifications
- [ ] Implement `plugin/cli.py` for in-session `/worktree` slash command (with `ctx.ask_choice` interactive prompts) and `hermes worktree` CLI subcommands
- [ ] Add unit tests for hooks, slash commands, CLI commands, and race arena

## Milestone 3: Unified Desktop UI (`desktop/plugin.js`) & FastAPI Backend (`dashboard/plugin_api.py`)
- [ ] Create `dashboard/manifest.json` and `dashboard/plugin_api.py` mounting `/api/plugins/worktree-sandbox/*` (`GET /status`, `GET /worktrees`, `GET /diff/{id}`, `POST /create`, `POST /promote`, `POST /discard`, `POST /race`, `POST /demo`)
- [ ] Create `desktop/plugin.js` using `@hermes/plugin-sdk`, `react`, and `react/jsx-runtime` (Right-hand Worktree & Arena Inspector pane, Status Bar live diff chip, ⌘K Palette commands, and `::worktree-card` inline transcript directive)
- [ ] Verify `desktop/plugin.js` passes `hermes_cli.plugin_validate_desktop.check_desktop_surface` with zero errors and zero warnings

## Milestone 4: End-to-End Integration Tests, Documentation Polish & Catalog Entry
- [ ] Write `tests/test_hermes_integration.py` running `validate_plugin_dir`, `scan_plugin_payloads.py`, and `validate_plugin_catalog.py`
- [ ] Generate `catalog-entry/worktree-sandbox.yaml` ready for PR submission to `NousResearch/hermes-agent`
- [ ] Finalize `README.md` with complete quickstart, architecture, configuration reference, security disclosure, and troubleshooting
