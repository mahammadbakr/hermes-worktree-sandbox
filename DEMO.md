# Demo video package — `worktree-sandbox`

**Target: 75 seconds** (hard limit 90). One idea: *the agent works in a throwaway copy of your
project, and it proves which of two fixes is actually correct before touching your files.*

Post on X, tag `@NousResearch`, and put the link in the entry form.

---

## 1. What the viewer must remember

1. The agent edits and runs commands while `git status` on the real checkout stays clean.
2. Two plausible fixes are raced **in parallel**, verified by the project's own tests, and one **fails**.
3. One click promotes the winner; a backup is written; the diff is exactly what it should be.

---

## 2. Pre-flight (do this once)

> **A connected model is required for the agent beats** (0:14–0:32 and 0:32–0:58). Sign in with
> `hermes portal` (Nous Portal) or `hermes setup`, then confirm `hermes status` shows a provider.
> **The race itself needs no model, no network and no API key**, so the model-free variant in §3
> works with nothing connected.
>
> **Use a capable model for the recording.** Measured on a free tier model
> (`upstage/solar-mini4:free`): ~50 s per API call, and instead of acting it went off to
> `web_search` for documentation — unusable for a 75-second video. Pick a strong model with
> `hermes model` before you record, or use the model-free variant, which is instant and cannot
> flake on camera.

> **Command name:** this plugin registers **`hermes sandbox`** and **`/sandbox`**. (`hermes worktree`
> and `/worktree` belong to Hermes core — they manage *session* worktrees, not this plugin's.)


```bash
# 1. A checkout to record against
cd <your clone of hermes-worktree-sandbox>

# 2. Seed the recording workspace (creates a demo project whose parser fails 4 of 7 tests
#    and races two candidate fixes, keeping both worktrees so the Desktop pane has content)
HERMES_AGENT_REPO=/path/to/hermes-agent PYTHON=/path/to/hermes/venv/bin/python \
  bash scripts/demo_seed.sh --reset

# It prints:
#   DEMO_PROJECT=/Users/you/.hermes/plugin-data/worktree-sandbox/demo/<stamp>
#   DEMO_RACE=race-...  WINNER=careful
#     careful      PASS    95 ms  wt-race-...-1-careful-cbc130
#     trim-only    FAIL   113 ms  wt-race-...-0-trim-only-cbc130
```

Then in Hermes:

```bash
hermes plugins install mahammadbakr/hermes-worktree-sandbox#plugin --enable   # or the catalog name
hermes config set terminal.backend worktree
# open the seeded project as the workspace
hermes desktop            # or: hermes chat   (both work; Desktop shows the pane)
```

In Desktop: right-click the workspace → dock the **worktrees** pane on the right
(it may already be there), and open a terminal panel in `DEMO_PROJECT`.

**Reset between takes:**

```bash
bash scripts/demo_seed.sh --reset         # wipes seeded projects, re-seeds one
/sandbox prune 0                          # remove leftover worktrees
```

---

## 3. Second-by-second script

### 0:00 – 0:06 · Hook
- **Shot:** Desktop window, **worktrees** pane visible on the right, terminal showing
  `cd "$DEMO_PROJECT" && git status --short` → **empty**.
- **Caption (big, top):** `Your agent edits. Your checkout doesn't.`
- **Voice:** "This is a coding agent that cannot touch your real files until you say so."

### 0:06 – 0:14 · The problem
- **Shot:** terminal — `python -m unittest -q test_parser` → `FAILED (failures=4)`.
- **Caption:** `4 failing tests. Two plausible fixes. Which one is right?`
- **Voice:** "The parser is broken. I could guess — or I could measure."

### 0:14 – 0:32 · Isolation, live
- **Shot:** Desktop composer. Type:
  > `Fix parser.py so all the tests pass. Keep my checkout untouched and tell me what's pending.`
- **Shot:** the agent edits `parser.py`; the pane’s `+added/-deleted` numbers tick up (driven by the
  `post_tool_call` hook, not polling); `python -m unittest -q` runs **inside the worktree** and passes.
- **Shot:** terminal — `git status --short` again: **still empty**.
- **Caption:** `terminal + every file tool + all tests ran in an isolated Git worktree`
- **Voice:** "Every command and every edit went into an isolated Git worktree — the real checkout is
  untouched, so I can review this, keep it, or throw it away."

### 0:32 – 0:58 · The arena (the payoff)
- **Shot:** composer. Type:
  > `Race two fixes for the parser: one that only trims whitespace, and one that also normalises key
  > case. Use the project's own tests to verify. Don't apply anything yet.`
- **Shot:** two worktrees appear in the pane in parallel; the leaderboard prints in the chat:
  ```
  1. careful      PASS    95 ms  +12/-7 in 1 file(s)  score 1188.15
  2. trim-only    FAIL   113 ms  +11/-7 in 1 file(s)  score 186.80
  ```
- **Shot:** zoom on `trim-only FAIL` — the *wrong* fix, caught before it ever reached the repo.
- **Caption:** `Same tests, same moment. The arena caught the wrong fix.`
- **Voice:** "Both fixes ran at once, each in its own worktree, verified by the project's own test
  suite. The obvious tidy-up fails — and it never touched my project."

> **Deterministic fallback (if the live model is slow — same visuals, instant):**
> type `/sandbox demo` instead. It seeds its own project and prints the same kind of leaderboard
> with zero model latency, no network and no API key.

### 0:58 – 1:10 · Promote the winner
- **Shot:** click **Promote** on the `careful` worktree in the pane → toast:
  `Promoted wt-…-careful: 1 file(s) into your checkout.`
- **Shot:** terminal — `git diff --stat` → one file changed; `ls` → nothing else appeared.
- **Caption:** `Promoted 1 file · backup written · nothing else changed`
- **Voice:** "One click promotes the winner — conflict-checked, and backed up first. The loser is
  discarded; my history is untouched."

### 1:10 – 1:15 · Call to action
- **Shot:** the pane with the remaining worktree, then the repo URL on screen.
- **Caption:** `hermes plugins install worktree-sandbox`
- **Voice:** "Worktree Sandbox — install it from the Hermes plugin catalog. No Docker, no API keys,
  works offline on macOS and Linux."

---

## 4. On-screen captions (muted viewing)

Show these as large text overlays, one per beat:

| Time | Caption |
|---|---|
| 0:00 | `Your agent edits. Your checkout doesn't.` |
| 0:08 | `4 failing tests` |
| 0:16 | `Commands + edits + tests → isolated Git worktree` |
| 0:24 | `git status: still clean` |
| 0:34 | `Race two fixes, in parallel` |
| 0:44 | `Verified by the project's own tests` |
| 0:50 | `the obvious fix FAILS` |
| 1:00 | `Promote the winner → 1 file, backup written` |
| 1:12 | `hermes plugins install worktree-sandbox` |

---

## 5. Shot list

| # | Shot | Source | Notes |
|---|---|---|---|
| 1 | Clean checkout + pane idle | Desktop + terminal | Establish the panel layout |
| 2 | `python -m unittest -q` failing | terminal | Crop tight on `FAILED (failures=4)` |
| 3 | Prompt typed + agent edit | Desktop composer | Type it live; do not paste — reads better |
| 4 | Pane numbers changing | Desktop pane | The only "live" moment; hold ~2 s |
| 5 | `git status --short` empty | terminal | The core claim — hold 2 s |
| 6 | Race prompt → leaderboard | Desktop | Zoom the leaderboard |
| 7 | Pane with 2 parallel worktrees | Desktop pane | Shows the parallel worktrees |
| 8 | Promote click + toast | Desktop pane | Show the backup path in the toast if visible |
| 9 | `git diff --stat` | terminal | Proves exactly one file changed |
| 10 | URL + install line | static card | 3 s closing |

---

## 6. Recording checklist

- [ ] Display at 1920×1080 (or 2560×1440), scale so terminal text is ≥ 16 px on screen
- [ ] One window: Desktop with the **worktrees** pane docked right and a terminal panel below
- [ ] Font size in the terminal and composer bumped (⌘+ twice)
- [ ] Do Not Disturb on; Slack/mail/notifications off; quit menu-bar clutter
- [ ] Close unrelated browser tabs and any second monitor
- [ ] `DEMO_PROJECT` open as the workspace; `/sandbox prune 0` so the pane starts empty
- [ ] Theme: dark (the pane chip and captions read better); hide the session list if it is noisy
- [ ] Run one **throwaway take** end-to-end before the real one
- [ ] Record at 60 fps; keep the raw file for a re-cut
- [ ] Check audio: the voiceover must be legible over the keystrokes
- [ ] Final export ≤ 90 s, ≤ 512 MB, H.264 + AAC, 1080p
- [ ] Watch it **muted** once — the captions alone must tell the story
- [ ] Watch it **at 0.25×** to check no secret, path or token is on screen
- [ ] Backup take recorded with the `/sandbox demo` fallback

---

## 7. Post-production

- Trim dead air between beats (typically 8–12 s) rather than speeding anything up — the pane updates
  and the race are the interesting motion.
- Add a subtle zoom on: the `FAILED (failures=4)` line, the `trim-only FAIL` row, and the promote toast.
- Keep the terminal font large enough that a phone viewer can read `git status` output.
- Do **not** add music louder than the voice; the keystrokes carry the pace.
- End card: plugin name, `hermes plugins install worktree-sandbox`, `@NousResearch`.

---

## 8. If something breaks mid-recording

| Symptom | Recovery |
|---|---|
| Pane is empty | The gateway restarted: `hermes plugins enable worktree-sandbox`, then reload the Desktop window |
| Pane says "backend is not reachable" | The plugin is not enabled, or `plugins.isolation: host` — see README → Troubleshooting |
| Pane is stale | Click **Refresh** in the pane header, or `⌘K → Reload desktop plugins` |
| Worktrees piled up from earlier takes | `/sandbox prune 0` then re-run `scripts/demo_seed.sh --reset` |
| The model is slow / refuses | Switch to the `/sandbox demo` fallback take (fully offline, identical UI) |
| Promote refuses with a conflict | That is the feature working: click **Force** (a backup is still written) or re-seed |
