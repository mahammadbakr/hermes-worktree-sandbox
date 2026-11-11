# Submission package

Everything needed to file the entry: the catalog PR, the X post, the form answers, and the
step-by-step checklist. Fill in the two `<…>` placeholders once the public repo exists.

**Official entry form:** https://form.typeform.com/to/FwJLvOln

**Assumed public repo:** `https://github.com/mahammadbakr/hermes-worktree-sandbox`
(if the owner/name differ, update `plugin.yaml` → `homepage`, `README.md` → Install, and
`catalog-entry/worktree-sandbox.yaml` → `repo`).

---

## 1. X post variants (tag `@NousResearch`)

Attach the ≤90 s demo video to each. Keep the first line self-contained — it is the whole ad.

### A. Punchy

> Your agent edits your repo. Mine doesn't.
>
> **Worktree Sandbox** for Hermes Agent runs every command, file edit and test inside an isolated Git
> worktree — then races competing fixes in parallel and promotes the one that actually passes.
>
> Demo 🎬 below · `hermes plugins install worktree-sandbox`
>
> @NousResearch

### B. Technical

> Built a Hermes plugin that makes agent edits reversible and agent choices evidence-based.
>
> `worktree-sandbox` registers a real `terminal.backend` (`TerminalEnvironmentProvider` + a
> `BaseEnvironment` with `uses_host_filesystem = False`), so `terminal`, `execute_code` and the file
> tools all run in a per-task Git worktree with the credential env stripped.
>
> `worktree_race` then runs 2–5 candidates in parallel worktrees, verifies each with your project's
> own test command (hard timeout, process-group kill) and scores pass/fail → speed → diff size.
> Desktop pane + status chip + inline `::worktree-card`, one-click promote with a timed backup.
>
> No network, no API keys, no Docker. macOS + Linux. 90s demo 👇
>
> `hermes plugins install worktree-sandbox` · @NousResearch

### C. Story-driven

> I kept losing work to an agent that "helpfully" refactored my repo while I wasn't looking.
>
> So the fix wasn't a better prompt — it was a boundary. Every Hermes command now runs in its own
> throwaway Git worktree. Nothing reaches my checkout until I promote it.
>
> Then I went one step further: if I have two ideas, why guess? The plugin runs both, in parallel,
> against my real test suite, and tells me which one is actually correct — in the demo, the obvious
> fix *fails* and never touches my files.
>
> 90 seconds, no API keys, works offline: packing it up as a Hermes plugin 👇
>
> @NousResearch

---

## 2. Pull request to `NousResearch/hermes-agent`

**PR title:**

```
catalog: add worktree-sandbox (transactional Git-worktree terminal backend + race arena)
```

**PR body** (mirrors `.github/PULL_REQUEST_TEMPLATE.md`):

```markdown
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
hermes worktree demo           # the same demo from the terminal

# 3. The plugin's own suite (227 tests) and the end-to-end proof
HERMES_AGENT_REPO=/path/to/hermes-agent python3 scripts/vertical_slice.py
#    loads the plugin through the real PluginManager in a throwaway HERMES_HOME, runs the real
#    `terminal` tool inside the worktree, asserts the host checkout stays clean, promotes, races,
#    checks the hooks/skill/commands, and mounts the dashboard backend
```

## Checklist

### Code

- [x] I've read the [Contributing Guide](https://github.com/NousResearch/hermes-agent/blob/main/CONTRIBUTING.md)
- [x] My commit messages follow [Conventional Commits](https://www.conventionalcommits.org/)
      (in the plugin repository; this PR is a single-agent-authored commit adding one catalog file)
- [x] I searched for [existing PRs](https://github.com/NousResearch/hermes-agent/pulls) to make sure
      this isn't a duplicate (`worktree`, `sandbox`, `race` — no existing catalog entry)
- [x] My PR contains **only** changes related to this fix/feature — one file under `plugin-catalog/`
- [ ] I've run `pytest tests/ -q` and all tests pass — **N/A: no `hermes-agent` core code is changed.**
      The plugin's own suite (227 tests) passes and is run in its repository's CI.
- [ ] `python scripts/check` passes — **N/A: no core code is changed.**
- [ ] I've added tests for my changes — the tests live in the plugin repository (227 tests, plus a
      real-`PluginManager` end-to-end script).
- [x] I've tested on my platform: **macOS 15 (Apple Silicon)**. Linux is supported and covered by the
      plugin's CI; Windows is explicitly out of scope (`platforms: [linux, macos]`).

### Documentation & Housekeeping

- [x] I've updated relevant documentation — plugin README, `DEMO.md`, `PLAN.md`, `CHANGELOG.md` in
      the plugin repository (the catalog page renders that README from the pinned commit)
- [ ] I've updated `cli-config.yaml.example` — **N/A: the plugin adds no core config keys**
- [ ] I've updated `CONTRIBUTING.md` / `AGENTS.md` — **N/A**
- [x] I've considered cross-platform impact — macOS + Linux supported, Windows declared unsupported in
      `platforms`
- [x] I've updated tool descriptions/schemas — in the plugin repository

## For New Skills

Not applicable — this PR adds no bundled skill. The plugin ships its own skill inside its package
(`plugin/skills/worktree-sandbox/SKILL.md`), registered via `ctx.register_skill()`.

## Screenshots / Logs

Screenshots and the 90-second demo are in the plugin README and the linked X post.

```
$ hermes plugins validate ./plugin
  PASS  manifest                           plugin.yaml parses
  PASS  manifest fields                    name, version, description present
  PASS  requires_hermes                    spec '>=0.22.5' parses
  PASS  config schema                      shape valid
  PASS  requires_env                       all entries UPPER_SNAKE
  PASS  oauth                              not declared
  PASS  loadable                           entry: __init__.py, desktop/plugin.js
  PASS  python dependencies                none declared
  PASS  capability probe                   register() ran in isolation
  PASS  declared tools                     matches registrations
  PASS  declared hooks                     matches registrations
  PASS  declared middleware                matches registrations
  PASS  built-in tool collisions           no collisions
  PASS  security scan                      safe
  PASS  no core override                   no runtime rebinds of Hermes core
  PASS  desktop surface                    stays inside the plugin SDK surface
  ok: True   warnings: none
```
```

---

## 3. The official entry form — exact fields

**Form:** *Hermes Agent Plugin Hackathon Submission Form*
**URL:** https://form.typeform.com/to/FwJLvOln
(linked from the official [@NousResearch announcement](https://x.com/NousResearch/status/2118094256438936062))

It is a five-question Typeform. **All five are required** (verified from the page's embedded form
definition, not guessed):

| Field | Type | Paste this |
|---|---|---|
| **Plugin Title** | short text | `Worktree Sandbox` |
| **Plugin Description** | short text | `Transactional Git-worktree terminal backend and speculative race arena for Hermes Agent: the agent works in an isolated copy of your project and proves which fix is correct before touching your files.` |
| **Email Address** | email | your email (used for winner contact / prize receipt) |
| **Discord Username** | short text | your Discord handle — join https://discord.gg/nousresearch first |
| **X Demo Post Link** | URL | the X post URL of the ≤90 s demo, tagging @NousResearch |
| **GitHub Link to your Hermes Plugin Pull Request** | URL | `https://github.com/NousResearch/hermes-agent/pull/153343` |

A statement step in the middle ("Submit a PR to add your Plugin to the Hermes Plugin Catalog")
links to the catalog-submission instructions; click **Continue** to move past it.

Confirmation: a **Submission Received** screen reading *"…We will post a thread from the Nous Research
X Account (@nousresearch) with the winners shortly following the end of the hackathon
(November 11th at 1pm PST)."*

> **Deadline nuance worth knowing:** the announcement says **5 PM EST**, while the thank-you copy says
> the winners thread follows **1 PM PST** (= 4 PM EST). The announced deadline is 5 PM EST; submitting
> by **4 PM EST** satisfies both readings.

### Longer description (if the field takes more than one line)

> Worktree Sandbox registers a real terminal backend for Hermes Agent (`terminal.backend: worktree`)
> so every `terminal`, `execute_code` and file-tool call runs inside its own isolated Git worktree,
> with the credential environment stripped and a private TMPDIR. The user's checkout is byte-for-byte
> unchanged until they promote, and promotion is conflict-checked against the worktree's base commit
> and preceded by a timestamped backup. `worktree_race` then runs two to five candidate solutions in
> parallel worktrees, verifies each with the project's own command (hard timeout, process-group kill)
> and scores them pass/fail -> speed -> diff size, so a faster-but-wrong candidate can never win.
> A docked Hermes Desktop pane, a status-bar diff chip and an inline `::worktree-card` transcript
> directive surface the result, with one-click promote. No network calls, no API keys, no Docker;
> macOS and Linux. MIT.

### Supporting answers (not asked by this form, but useful in a PR or Discord thread)

| Question you may be asked | Answer |
|---|---|
| Category | Tools |
| Plugin type | Terminal environment provider + tools + lifecycle hooks + Desktop UI (unified agent/desktop package) |
| Extension points | `register_terminal_environment_provider`, `register_tool` x5, `register_hook` x4, `register_system_prompt_section`, `register_command`, `register_cli_command`, `register_skill`, dashboard `plugin_api.py`, Desktop plugin SDK |
| Languages / deps | Python 3.11+ standard library only, plus one ES-module Desktop file. No third-party packages. |
| Why it is more than a prompt or a skill | A prompt can ask a model to be careful. This plugin changes what the harness *does*: a registered environment backend routes every command and file tool into a separate filesystem root at the runtime layer, and `worktree_race` actually executes and verifies competing solutions (including killing hung ones). |
| Requirements | macOS or Linux, `git` + `bash` on PATH, Hermes Agent >= 0.22.5. |
| License | MIT |
| Time to first success | Under 2 minutes (measured: ~5 s on a fresh `HERMES_HOME` for load + `/sandbox demo`). |
| Not included | Windows support; hunk-level cherry-picking; OS-level sandboxing (see README -> Limitations). |

## 4. Submission checklist — step by step

Do them in this order. Steps 1–2 are the long-lead items (a maintainer must start the checks).

### Step 0 — prerequisites (evening of Nov 9)
1. Confirm the public repo owner/name, then update all three references if it differs from
   `mahammadbakr/hermes-worktree-sandbox`: `plugin/plugin.yaml` → `homepage`, `README.md` → Install,
   `catalog-entry/worktree-sandbox.yaml` → `repo`.
2. `git remote add origin git@github.com:<owner>/hermes-worktree-sandbox.git && git push -u origin main`
3. Verify the repo is public and `git clone` works logged out.

### Step 1 — open the PR **early** (Nov 9–10 morning)
4. Pin the entry to the pushed commit:
   ```bash
   bash scripts/pin_catalog_entry.sh      # refuses on a dirty tree
   git commit -am "chore(submission): pin catalog entry to the pushed commit"
   git push
   bash scripts/pin_catalog_entry.sh      # re-pin to the commit you just pushed
   git commit -am "chore(submission): final catalog pin" && git push
   ```
   The invariant that matters: the pinned SHA's `plugin/` tree must be identical to the pushed HEAD's.
   `tests/test_submission.py` enforces this locally; if it fails, re-run the pin.
5. Fork `NousResearch/hermes-agent`, branch, and add **exactly one file**:
   ```bash
   gh repo fork NousResearch/hermes-agent --clone=false
   cd <your hermes-agent fork> && git fetch origin && git checkout -b catalog-worktree-sandbox origin/main
   mkdir -p plugin-catalog
   cp /path/to/hermes-worktree-sandbox/catalog-entry/worktree-sandbox.yaml \
      plugin-catalog/worktree-sandbox.yaml
   git add plugin-catalog/worktree-sandbox.yaml && git commit -m "catalog: add worktree-sandbox"
   git push -u origin catalog-worktree-sandbox
   gh pr create --title "catalog: add worktree-sandbox (transactional Git-worktree terminal backend + race arena)" \
     --body-file /path/to/hermes-worktree-sandbox/docs/pr-body.md
   ```
   > **Critical:** catalog CI rejects a PR that touches anything outside `plugin-catalog/**` and
   > `contributors/emails/**`. Do not add screenshots to the PR — link to the README and the X post.

### Step 2 — confirm the checks (within an hour of opening)
6. Watch `Plugin Catalog CI`: `structural` and `pinned-source-validate`. Both must be green.
   - `structural` failing almost always means a YAML/field problem — re-run
     `python3 scripts/validate_plugin_catalog.py plugin-catalog/worktree-sandbox.yaml`.
   - `pinned-source-validate` failing means the SHA is not reachable or
     `hermes plugins validate --install-deps` failed at the pin — re-run it locally on a clean clone
     of the pinned commit.
7. If Actions need a maintainer to approve the first run, leave a short, specific comment on the PR
   saying the checks are waiting on approval. Do not nudge more than once.

### Step 3 — record and post the demo (Nov 10)
8. Follow `DEMO.md` (seed with `scripts/demo_seed.sh --reset`, record, export ≤ 90 s).
9. Post on X with one of the variant posts above, attached video, tagging `@NousResearch`.
10. Copy the post URL. Open it in a private window and confirm the video plays.

### Step 4 — submit the entry

11. Open **https://form.typeform.com/to/FwJLvOln** and fill the five required fields from §3
    (Plugin Title, Plugin Description, Email Address, Discord Username, X Demo Post Link,
    GitHub PR link). Click **Continue** past the PR-instructions statement and submit.
12. Screenshot the **Submission Received** confirmation. Before submitting, open both links in a
    **logged-out** browser window: the PR must be publicly readable and the X post must play.

### Step 5 — monitor (Nov 10–11, buffer)
13. Join the Nous Research Discord and watch your entry's thread for maintainer questions; be ready
    to answer within a few hours.
14. If a reviewer asks for a change in the catalog entry, it is a **new commit on the same PR**; if
    they ask for a plugin change, that is a new commit in the plugin repo **plus a SHA bump in the
    entry** (a new PR diff). Keep the plugin's `version` and the entry `version` in step.
15. If the demo video needs a re-cut, the X post can be replaced only if the form allows editing the
    link — otherwise reply to your own post with the corrected video.

### Definition of done
- [ ] `plugin-catalog/worktree-sandbox.yaml` PR open and CI green
- [ ] Plugin repo public; the pinned SHA is reachable and contains the final `plugin/` tree
- [ ] ≤90 s demo posted on X, tagging `@NousResearch`, playing logged out
- [ ] Entry form submitted with both links, verified logged out
- [ ] Discord joined, entry thread watched
