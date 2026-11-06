# TODO — `hermes-worktree-sandbox`

## Milestone 0: Research, Plan & Repository Scaffold
- [x] Research Hermes plugin developer guide, 19 sub-guides, and 1,063 catalog plugins (`RESEARCH.md`)
- [x] Select Idea 1 (`hermes-worktree-sandbox`) and write `PLAN.md`
- [x] Create git repository scaffold (`LICENSE`, `.gitignore`, `.env.example`, `pytest.ini`, `.github/workflows/ci.yml`, `CHANGELOG.md`, `TODO.md`, `DEMO.md`, `README.md`, `plugin.yaml`)

## Milestone 1: Vertical Slice (Core Provider, Worktree Engine & SQLite Ledger)
- [ ] Implement `storage.py`: WAL-mode SQLite ledger (`plugin_db("worktree-sandbox")`) tracking worktree sessions, tool mutations, and race runs
- [ ] Implement `manager.py`: `WorktreeManager` with real `git worktree` lifecycle, shadow-repo fallback for non-Git directories, diff/stat calculation, conflict-safe promotion with `.bak` backup snapshots, and worktree pruning
- [ ] Implement `provider.py`: `WorktreeSandboxProvider(TerminalEnvironmentProvider)` + `WorktreeEnvironment(BaseEnvironment)` (`uses_host_filesystem = False`, secret env stripping, isolated `TMPDIR`, `is_available()`, `probe()`, `doctor_checks()`, `setup_instructions()`)
- [ ] Implement `schemas.py`, `tools.py`, and `__init__.py` (`register(ctx)`)
- [ ] Verify vertical slice loads in real Hermes (`hermes_cli.plugin_validate.validate_plugin_dir`) and passes unit tests

## Milestone 2: Speculative Race Arena, Hooks & Slash/CLI Commands
- [ ] Implement `worktree_race` parallel multi-worktree candidate evaluator + built-in demo seed (`run_demo_race`)
- [ ] Implement lifecycle hooks (`on_session_start`, `post_tool_call`, `pre_verify`, `on_session_finalize`) with live `broadcast_plugin_event` notifications
- [ ] Implement `cli.py` for in-session `/worktree` slash command (with `ctx.ask_choice` interactive prompts) and `hermes worktree` CLI subcommands (`status`, `list`, `diff`, `promote`, `discard`, `race`, `demo`, `prune`)
- [ ] Add unit tests for hooks, slash commands, CLI commands, and race arena

## Milestone 3: Unified Desktop UI (`desktop/plugin.js`) & FastAPI Backend (`dashboard/plugin_api.py`)
- [ ] Create `dashboard/manifest.json` and `dashboard/plugin_api.py` mounting `/api/plugins/worktree-sandbox/*` (`GET /status`, `GET /worktrees`, `GET /diff/{id}`, `POST /create`, `POST /promote`, `POST /discard`, `POST /race`, `POST /demo`)
- [ ] Create `desktop/plugin.js` using `@hermes/plugin-sdk`, `react`, and `react/jsx-runtime` (Right-hand Worktree & Arena Inspector pane, Status Bar live diff chip, ⌘K Palette commands, and `::worktree-card` inline transcript directive)
- [ ] Verify `desktop/plugin.js` passes `hermes_cli.plugin_validate_desktop.check_desktop_surface` with zero errors and zero warnings

## Milestone 4: End-to-End Integration Tests, Documentation Polish & Catalog Entry
- [ ] Write `tests/test_hermes_integration.py` running `validate_plugin_dir`, `scan_plugin_payloads.py`, and `validate_plugin_catalog.py`
- [ ] Generate `catalog-entry/worktree-sandbox.yaml` ready for PR submission to `NousResearch/hermes-agent`
- [ ] Finalize `README.md` with complete quickstart, architecture, configuration reference, security disclosure, and troubleshooting
