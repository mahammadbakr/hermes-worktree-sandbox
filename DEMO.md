# 90-Second Demo Video Script (`DEMO.md`)

> **Target Duration:** 75 seconds (strictly under the 90-second limit)  
> **Post Target:** X (Twitter), tagging `@NousResearch`  
> **Setup Before Recording:**
> 1. Run `hermes worktree demo --reset` (or click **Seed Demo Arena** in the Hermes Desktop Worktree Sandbox pane) to initialize a clean sample repository with a slow parser implementation and unit test suite.
> 2. Open Hermes Desktop with the **Worktree Sandbox** right pane docked and visible alongside the chat transcript, and a small terminal showing `git status` in the main workspace.

---

## Second-by-Second Script

### 0:00 – 0:12 | The Problem & The Hook (12s)
- **Visual:** Split screen: Hermes Desktop on the left, terminal showing `git status` (`nothing to commit, working tree clean`) on the right. Highlight the `worktree: clean` chip in the Hermes Desktop status bar.
- **Voiceover:** *"When coding agents edit files or run shell commands, they mutate your working tree in place—and if you spawn parallel subagents, they overwrite each other's files. Meet **Worktree Sandbox**: a transactional Git-worktree terminal backend and speculative execution arena for Hermes Agent."*

### 0:12 – 0:30 | Transactional Isolation in Action (18s)
- **Visual:** Type in Hermes Desktop composer:  
  `Refactor parser.py to add strict header validation and run pytest.`
- **Action:** Hermes calls `write_file` and `terminal` (`pytest -q`).
- **What the viewer sees ("Wow" #1):**
  - The status bar chip live-updates to `🌿 wt-session (+28 / -6) · 4 passed`.
  - The right-hand **Worktree Sandbox** pane updates automatically via `broadcast_plugin_event`, showing the unified diff of `parser.py` inside the isolated worktree.
  - In the terminal on the right, run `git status` on the main checkout: **it is still 100% clean and untouched!**
- **Voiceover:** *"Because Worktree Sandbox implements Hermes's `TerminalEnvironmentProvider` with `uses_host_filesystem = False`, every file edit and shell command runs inside an isolated Git worktree with secrets stripped—leaving our main checkout completely untouched."*

### 0:30 – 0:58 | Speculative Multi-Branch Arena (`/worktree race`) (28s)
- **Visual:** Type `/worktree demo` (or click **"Run Speculative Race"** in the Desktop pane / ask Hermes to call `worktree_race` with two candidate optimizations: **Candidate A: Precompiled Regex** vs **Candidate B: Single-Pass State Machine**).
- **What the viewer sees ("Wow" #2):**
  - Two isolated Git worktrees spin up in parallel (`wt-race-regex` and `wt-race-statemachine`).
  - Both run the verification test suite and benchmark in parallel.
  - Inside the chat transcript, an inline `::worktree-card{race_id="..."}` React component renders live, showing:
    - **Candidate A (`regex`):** `✅ 12/12 tests passed · 18.4 ms · +14/-9 lines · Score: 91.2`
    - **Candidate B (`statemachine`):** `🏆 WINNER · ✅ 12/12 tests passed · 6.1 ms (3x faster) · +22/-9 lines · Score: 98.4`
- **Voiceover:** *"Even better: instead of guessing one approach, we can race competing solutions in parallel worktrees. Worktree Sandbox runs our verification suite against each branch, scores them on test pass rate, speed, and diff size, and renders an interactive comparison card right inside the Hermes transcript."*

### 0:58 – 1:15 | One-Click Promotion & Clean Rollback (17s)
- **Visual:**
  - Click **"Promote Winner"** on Candidate B in the Desktop pane (or inline card).
  - Toast notification appears: `Promoted wt-race-statemachine to workspace (1 file updated, backup saved)`.
  - Run `git status` and `git diff` in the main terminal: the winning changes are now cleanly applied to the main repo!
- **Voiceover:** *"With one click—or `/worktree promote` from Telegram, CLI, or Desktop—the winning diff is conflict-checked, backed up, and applied to our main workspace. Zero Docker overhead, works offline on macOS and Linux. Install `worktree-sandbox` from the Hermes Marketplace today."*
