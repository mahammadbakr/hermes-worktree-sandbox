# Changelog

All notable changes to `hermes-worktree-sandbox` (`worktree-sandbox`) are documented in this file.

## [0.1.2] - 2026-11-11

### Fixed
- **`terminal.backend: worktree` was unusable on a real install.** Hermes substitutes a generic
  in-container default (`/root`) whenever a backend does not declare `default_cwd`, and the provider
  treated that value as the workspace, so *every* `terminal` / `write_file` call failed with
  `workspace is not a directory: /root`. A cwd that is not an existing directory (or is the `/root`
  default) now falls back to the session's own working directory, then the process cwd. Found only by
  running a real agent turn on a real install — a checkout-based test could not see it.
- **The seeded demo project is now a real Git repository** (best-effort `git init` + initial commit),
  so the demo's "your checkout is untouched" beat actually works: `git status` is clean before the
  agent runs and the agent's edits land in a worktree instead.

## [0.1.1] - 2026-11-11

### Fixed
- **`hermes sandbox`, not `hermes worktree`.** Core already owns `hermes worktree` (the session
  worktree auditor) exactly as it owns the `/worktree` slash command, so the plugin's CLI
  registration silently lost and the documented `hermes worktree demo` did not exist. Both surfaces
  now share one name: **`/sandbox`** and **`hermes sandbox`**. Found by installing on a real Hermes
  0.23.1 install rather than a checkout. The status output and `hermes doctor` hints no longer
  advertise `/worktree demo` either.

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
- **Built-in offline demo** (`/sandbox demo`, `hermes sandbox demo`): seeds a self-contained
  project and races a failing `quick-split` parser against a passing `careful` parser — no network,
  no model call, no API key.
- **Shadow-Git fallback**: a folder that is not a Git repository is mirrored into a private shadow
  repo (credentials, binaries and dependency dirs excluded) so isolation works with zero setup;
  promotion always writes back into the real folder.
- **Lifecycle hooks**: `on_session_start`, `post_tool_call` (throttled live diff stats + Desktop
  events), `pre_verify` (optional `verify_command` gate that keeps the agent working when
  verification fails), `on_session_finalize` (bounded prune).
- **`/sandbox` slash command** and **`hermes sandbox` CLI** sharing one verb dispatcher
  (`status|list|diff|promote|discard|prune|demo`), with an interactive worktree picker where one is
  available and a clean usage hint when nobody can answer.
- Build artifacts and credential-shaped files are now excluded from change reports, diffs and
  promotion (consistent with the shadow mirror).
- 45 more tests (148 total) covering the race arena, shadow repos, hooks and commands.

### Milestone 3 — Desktop UI and dashboard backend

- **`plugin/dashboard/`**: `manifest.json` + `plugin_api.py` mounting
  `/api/plugins/worktree-sandbox/` (`status`, `worktrees`, `worktrees/{id}`, `.../diff`,
  `.../promote`, `race`, `demo`, `races/{id}`, `events`, `config`). The module bootstraps the plugin
  core by path, because Hermes imports a plugin backend as a single file.
- **`plugin/desktop/plugin.js`**: docked **worktrees** pane (live stats, inline diff preview,
  per-worktree Promote / Force / Discard, "Run demo race"), a status-bar diff chip, ⌘K palette
  commands, and the interactive `::worktree-card` transcript directive fed by the recorded race.
  Namespace import plus feature detection, so older Desktop builds still load; every timer and
  listener is owned by `ctx`.
- **`plugin/skills/worktree-sandbox/SKILL.md`**: bundled skill teaching the worktree workflow, the
  race arena and the directive.

### Hardening pass (feature freeze)

Adversarial review of the codebase, with the fixes below and 41 new tests:

- **Tool input validation**: every handler now rejects wrong-typed arguments (`workspace`,
  `task_id`, `base`, `worktree_id`, `force`, `files`, `verify_command`, `timeout`,
  `promote_winner`, `keep_worktrees`) instead of silently coercing them.
- **Newline-safe change parsing**: `--numstat -z` / `--porcelain=v1 -z`, so filenames containing
  spaces, quotes, tabs, newlines or non-ASCII characters are read exactly (a misparsed path would
  have promoted the wrong file). Regression-tested.
- **Symlinks are never promoted** (they are reported under `skipped`) and are never read through.
- **Silent exclusions are now reported**: `promote` returns `filtered` (artifact/credential-shaped
  paths) and `unmatched` (requested paths that were not in the change set); `create` returns a
  `note` when the managed worktree lives inside the project's own working tree.
- **`pre_verify` verifies the right worktree**: it now selects the worktree from the turn's
  `changed_paths`, so a dirty worktree from another project can never be verified by mistake.
- **Race input validation** (candidate file content must be a string) and **bounded demo storage**
  (seeded demo projects are trimmed to the newest three).
- **No more log noise**: event emission is skipped in a process with no gateway, which previously
  made Hermes log a warning with a traceback in every plain `hermes chat` session.
- **Type safety**: `mypy` clean across the plugin; the ledger migration and the process-group
  attribute are now explicitly typed.
- **Catalog entry** added at `catalog-entry/worktree-sandbox.yaml`; the structural validator, the
  unsccannable-payload scanner and `hermes plugins validate` all pass.
- `scripts/clean_install.sh` reproduces the README install on a throwaway `HERMES_HOME` and asserts
  first success inside a 120-second budget (measured: ~5 s).
