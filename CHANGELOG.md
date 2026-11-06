# Changelog

All notable changes to `hermes-worktree-sandbox` (`worktree-sandbox`) are documented in this file.

## [0.1.0] - 2026-11-06

### Added
- Initial repository scaffold, architecture plan (`PLAN.md`), research documentation (`RESEARCH.md`), and 90-second demo script (`DEMO.md`).
- **Milestone 1 — vertical slice.** `plugin/` package with:
  - `provider.py`: `WorktreeSandboxProvider` (`terminal.backend: worktree`) and `WorktreeEnvironment`
    (a `BaseEnvironment` with `uses_host_filesystem = False`, scrubbed subprocess environment,
    private `TMPDIR`, process-group kill, and host-cwd → worktree remapping).
  - `manager.py`: `WorktreeManager` — create/reuse isolated Git worktrees, change/line-stat
    collection, unified diff, conflict-checked promotion with `.bak` backups, discard and prune.
  - `storage.py`: WAL-mode SQLite ledger (`$HERMES_HOME/plugin-data/worktree-sandbox/data.db`).
  - `security.py`: credential-env scrubbing, sensitive-filename filter, worktree-id and
    relative-path validation.
  - `schemas.py` / `tools.py` / `__init__.py`: four tools (`worktree_create`, `worktree_status`,
    `worktree_diff`, `worktree_promote`) and the plugin entry point.
- `scripts/vertical_slice.py`: end-to-end proof that runs the plugin inside a real Hermes
  `PluginManager` and drives the real `terminal` + `worktree_*` tools.
- 103 unit and integration tests, including real `hermes_cli.plugin_validate` admission checks.

### Milestone 2 — race arena, hooks and commands

- **`worktree_race`**: run 2–5 competing solutions in parallel isolated worktrees, verify each with
  a command (hard timeout, process-group kill), score on pass/fail + speed + diff size, and
  optionally promote the winner. Git mutations are serialized so parallel candidates cannot
  collide on `git worktree add`.
- **Built-in offline demo** (`/sandbox demo`, `hermes worktree demo`): seeds a self-contained
  project and races a failing `quick-split` parser against a passing `careful` parser — no network,
  no model call, no API key.
- **Shadow-Git fallback**: a folder that is not a Git repository is mirrored into a private shadow
  repo (credentials, binaries and dependency dirs excluded) so isolation works with zero setup;
  promotion always writes back into the real folder.
- **Lifecycle hooks**: `on_session_start`, `post_tool_call` (throttled live diff stats + Desktop
  events), `pre_verify` (optional `verify_command` gate that keeps the agent working when
  verification fails), `on_session_finalize` (bounded prune).
- **`/sandbox` slash command** and **`hermes worktree` CLI** sharing one verb dispatcher
  (`status|list|diff|promote|discard|prune|demo`), with an interactive worktree picker where one is
  available and a clean usage hint when nobody can answer.
- Build artifacts and credential-shaped files are now excluded from change reports, diffs and
  promotion (consistent with the shadow mirror).
- 45 more tests (148 total) covering the race arena, shadow repos, hooks and commands.
