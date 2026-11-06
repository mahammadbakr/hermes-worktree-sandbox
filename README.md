# Worktree Sandbox (`worktree-sandbox`)

**Transactional Git-worktree terminal backend and speculative execution arena for [Hermes Agent](https://github.com/NousResearch/hermes-agent).**

`worktree-sandbox` gives Hermes Agent zero-overhead transactional filesystem isolation on macOS and Linux without Docker or VMs. By implementing Hermes's `TerminalEnvironmentProvider` (`terminal.backend: worktree`) with `uses_host_filesystem = False`, every shell command (`terminal`, `execute_code`) and file operation (`read_file`, `write_file`, `patch`, `search_files`) executes inside an isolated Git worktree while your main checkout stays 100% untouched. Even better, its **Speculative Arena** (`worktree_race`) lets Hermes race multiple competing code solutions in parallel worktrees, score them with your real test suite, and promote the winning diff with one click in Hermes Desktop or via `/worktree promote`.

![Worktree Sandbox Hero BannerPlaceholder](docs/assets/banner-placeholder.svg)

---

## Why This Could Never Be Just a Prompt or Skill

1. **Runtime Environment Interception (`TerminalEnvironmentProvider`):** A prompt or skill cannot stop `write_file`, `patch`, or `execute_code` from mutating your working tree in place. By registering a `BaseEnvironment` with `uses_host_filesystem = False`, Hermes routes all file and terminal tool calls through the isolated worktree at the Python runtime level.
2. **Subprocess Secret Stripping & Private `$TMPDIR`:** Automatically strips provider API keys, GitHub tokens, and SSH/GPG agent sockets from spawned commands while giving each worktree its own private scratch directory.
3. **Parallel Multi-Worktree Racing (`worktree_race`):** Spins up N concurrent Git worktrees, applies candidate patches or commands in parallel, runs a verification/benchmark suite with process-group timeout enforcement, and computes a deterministic composite score (test pass status, execution latency, and diff footprint).
4. **Live Desktop UI (`@hermes/plugin-sdk`):** Pushes real-time diff events (`broadcast_plugin_event`) to a docked Hermes Desktop inspector pane, a live status-bar diff chip, and inline `::worktree-card` transcript components.

---

## Install

From the Nous plugin catalog (recommended — pinned, reviewed commit):

```bash
hermes plugins install worktree-sandbox --enable
```

Directly from this repository (the plugin lives in the `plugin/` subdirectory):

```bash
hermes plugins install <owner>/hermes-worktree-sandbox#plugin --enable
```

To use `worktree` as your default transactional terminal backend:

```bash
hermes config set terminal.backend worktree
```

*(Optional)* Even when `terminal.backend` is left on `local`, the 5 `worktree_*` tools, `/worktree` slash command, `hermes worktree` CLI, and Desktop Arena pane remain fully available!

---

## Quickstart (Under 2 Minutes)

### 1. Run the Instant Built-In Demo Race
From any Hermes chat (CLI, TUI, Desktop, or Telegram/Discord):
```text
/worktree demo
```
Or from your terminal:
```bash
hermes worktree demo
```
This creates a self-contained sandbox repository, races two competing parser implementations (**Candidate A: Regex** vs **Candidate B: State Machine**) in isolated Git worktrees, runs automated verification benchmarks, and prints the scored leaderboard and inline `::worktree-card` directive.

### 2. Inspect, Diff & Promote Changes
```text
/worktree status
/worktree diff <worktree_id>
/worktree promote <worktree_id>
```

---

## Tools Reference

| Tool | Description |
|---|---|
| `worktree_create` | Create or reuse an isolated Git worktree for a task or experiment (auto-falls back to a shadow Git repo if the workspace is not a Git repository). |
| `worktree_status` | List active worktrees, modified/added/deleted files, line diff stats (`+added/-deleted`), and verification status. |
| `worktree_diff` | Return the unified git diff and per-file change summary for a worktree against its base commit. |
| `worktree_promote` | Conflict-check, back up touched host files, and apply a worktree's changes back into the main workspace. |
| `worktree_race` | Run 2–5 candidate approaches in parallel isolated worktrees, execute a verification/benchmark command in each, score them, and optionally promote the winner. |

---

## Configuration Reference (`config_schema`)

Configure in Hermes Desktop under **Settings → Plugins → Worktree Sandbox** or in `~/.hermes/config.yaml`:

```yaml
plugins:
  entries:
    worktree-sandbox:
      settings:
        auto_isolate: true       # Auto-create a worktree per task when terminal.backend is worktree
        keep_on_exit: true       # Keep worktrees with unpromoted changes after session ends
        verify_command: ""       # Default test command for pre_verify and worktree_race (e.g. "pytest -q")
        max_worktrees: 20        # Auto-prune oldest clean worktrees beyond this limit
```

---

## Security & Disclosure (Catalog Rule 13)

- **Zero Network Calls & Zero External Dependencies:** Runs 100% locally using `git` on `PATH` and the Python standard library. Makes no outbound HTTP requests, collects no telemetry, and makes no hidden LLM calls.
- **Local Storage:** Stores managed worktrees, `.bak` promotion backups, shadow repositories (for non-Git folders), and the WAL-mode SQLite ledger (`data.db`) exclusively inside `$HERMES_HOME/plugin-data/worktree-sandbox/`.
- **Credential Protection:** Never reads `.env`, `auth.json`, or SSH keys. Strips sensitive environment variables (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `OPENROUTER_API_KEY`, `GH_TOKEN`, `GITHUB_TOKEN`, `SSH_AUTH_SOCK`, `GPG_AGENT_INFO`) from commands run inside worktrees, and excludes credential-shaped filenames (`.env*`, `*.pem`, `*.key`) from shadow snapshots and diffs.
- **Approvals Respected:** `WorktreeSandboxProvider` keeps `is_container = False` (`skip_container_guards = False`), so Hermes's dangerous-command human approval gate stays active.

---

## Troubleshooting & Limitations

- **`git not found on PATH`:** Install Git (`xcode-select --install` on macOS or `apt install git` on Linux). Run `hermes doctor` to verify `worktree` backend health.
- **Promoting into a dirty checkout:** If a file in your main workspace was modified *after* the worktree branched, `worktree_promote` refuses to overwrite it by default and lists the conflicting file(s). Pass `force: true` (or `--force` in CLI/slash) to overwrite; a timestamped backup is always saved under `$HERMES_HOME/plugin-data/worktree-sandbox/backups/` first.
- **Platform Support:** Supports `macos` and `linux` (requires `bash` and `git`).

---

## License

[MIT](LICENSE)
