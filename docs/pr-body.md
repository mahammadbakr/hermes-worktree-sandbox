## What does this PR do?

Adds one catalog entry, `plugin-catalog/worktree-sandbox.yaml`, listing a community plugin that
registers a new terminal backend for Hermes Agent (`terminal.backend: worktree`) plus a speculative
execution arena.

The plugin gives every task its own isolated Git worktree. `terminal`, `execute_code` and the
`read_file` / `write_file` / `patch` / `search_files` file tools all run inside it (the environment
sets `uses_host_filesystem = False`), with the inherited credential environment stripped and a
private `TMPDIR`. The user's checkout is byte-for-byte unchanged until they promote, and a promotion
is conflict-checked against the worktree's base commit and preceded by a timestamped backup.

On top of that, `worktree_race` runs two to five candidate solutions in parallel worktrees, verifies
each with the project's own command (hard timeout, process-group kill) and scores them
pass/fail → speed → diff size, so a faster-but-wrong candidate can never win. A docked Hermes Desktop
pane, a status-bar diff chip and an inline `::worktree-card` transcript directive surface the result,
with one-click promote.

**Hermes surfaces used** (all public, no core patching):

- `ctx.register_terminal_environment_provider()` — `agent.terminal_env_provider.TerminalEnvironmentProvider`
  plus a `tools.environments.base.BaseEnvironment` subclass
- `ctx.register_tool()` × 5 — `worktree_create`, `worktree_status`, `worktree_diff`,
  `worktree_promote`, `worktree_race`
- `ctx.register_hook()` × 4 — `on_session_start`, `post_tool_call`, `pre_verify`, `on_session_finalize`
- `ctx.register_system_prompt_section()` — tells the model where its commands actually run
- `ctx.register_command("sandbox")` + `ctx.register_cli_command("worktree")`
- `ctx.register_skill()` — a bundled workflow skill
- `ctx.get_config()` / manifest `config_schema` — five settings, rendered in Desktop → Settings → Plugins
- Dashboard backend `dashboard/plugin_api.py` (`/api/plugins/worktree-sandbox/…`) and the Desktop
  plugin SDK (`desktop/plugin.js`: pane, status bar, palette commands, transcript directive)
- `hermes_cli.plugin_events.broadcast_plugin_event()` for the live pane updates

**Disclosure (rule 13).** No network calls, no telemetry, no model calls of its own, no credentials
and no API keys. It shells out to the local `git` binary (argv, scrubbed env, 30 s timeout) and to
the verification command the user configured; writes managed worktrees, promotion backups, shadow
repositories (only when the folder is not a Git repository) and a SQLite ledger under
`$HERMES_HOME/plugin-data/worktree-sandbox/`; and exposes a read/write FastAPI router in the gateway.
It does not read `.env`, `auth.json`, keychains or browser profiles — the only setting it reads is its
own `verify_command` via `ctx.get_config`. Working-tree isolation is not an OS sandbox: a command can
still read other absolute paths on the host; the README says so and points at `bubblewrap` /
`singularity` for kernel-level confinement.

## Related Issue

No issue; a catalog listing does not require one. Happy to open one if you would prefer to track it.

## Type of Change

- [ ] 🐛 Bug fix (non-breaking change that fixes an issue)
- [x] ✨ New feature (non-breaking change that adds functionality)
- [ ] 🔒 Security fix
- [ ] 📝 Documentation update
- [ ] ✅ Tests
- [ ] ♻️ Refactor
- [ ] 🎯 New skill (bundled or hub)

## Changes Made

- `plugin-catalog/worktree-sandbox.yaml` — the only file in this PR.

## How to Test

The catalog CI job (`Plugin Catalog CI` → `pinned-source-validate`) clones the pinned commit and runs
`hermes plugins validate --install-deps` on it; I ran the same checks locally before opening this PR.

```bash
# 1. What catalog CI runs, against the pinned commit
hermes plugins validate ./plugin --install-deps
#    16/16 checks pass, 0 warnings

# 2. Install and try it (macOS or Linux, git + bash on PATH)
hermes plugins install mahammadbakr/hermes-worktree-sandbox#plugin --enable
hermes config set terminal.backend worktree
hermes chat
#    then in the session:
#      /sandbox demo            -> offline race, no network and no API key
#      /sandbox status          -> worktrees with +added/-deleted stats
#      /sandbox promote <id>    -> apply with a backup
hermes sandbox demo            # the same demo from the terminal

# 3. The plugin's own suite (227 tests) and the end-to-end proof
HERMES_AGENT_REPO=/path/to/hermes-agent python3 scripts/vertical_slice.py
#    loads the plugin through the real PluginManager in a throwaway HERMES_HOME, runs the real
#    `terminal` tool inside the worktree, asserts the host checkout stays clean, promotes, races,
#    checks the hooks/skill/commands, and mounts the dashboard backend
