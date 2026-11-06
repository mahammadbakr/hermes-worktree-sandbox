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

### 0:30 – 0:58 | Speculative Multi-Branch Arena (`/sandbox race`) (28s)
- **Visual:** Type `/sandbox demo` (or click **"Run Speculative Race"** in the Desktop pane / ask Hermes to call `worktree_race` with two candidate optimizations: **Candidate A: Precompiled Regex** vs **Candidate B: Single-Pass State Machine**).
- **What the viewer sees ("Wow" #2):**
  - Two isolated Git worktrees spin up in parallel (`wt-...-quick-split` and `wt-...-careful`).
  - Both run the project's own test suite, in parallel, inside their own worktree.
  - The leaderboard prints in chat:
    - **Candidate A (`quick-split`):** `FAIL · 4 tests failed · score 186.6`
    - **Candidate B (`careful`):** `🏆 WINNER · PASS · 12 tests, 0 failures · score 1190.35`
- **Voiceover:** *"Instead of guessing one approach, we race competing solutions in parallel worktrees. Worktree Sandbox runs the project's own test suite against each candidate, scores them on pass/fail, speed and diff size, and promotes the winner — the arena found the implementation that actually works."*

### 0:58 – 1:15 | One-Click Promotion & Clean Rollback (17s)
- **Visual:**
  - Click **"Promote Winner"** on Candidate B in the Desktop pane (or `/sandbox promote <id>`).
  - Toast notification appears: `Promoted wt-...-careful: 1 applied, 0 deleted. backup: ...`
  - Run `git status` and `git diff` in the main terminal: the winning changes are now cleanly applied to the main repo!
- **Voiceover:** *"With one click—or `/sandbox promote` from Telegram, CLI, or Desktop—the winning diff is conflict-checked, backed up, and applied to our main workspace. Zero Docker overhead, works offline on macOS and Linux. Install `worktree-sandbox` from the Hermes Marketplace today."*
