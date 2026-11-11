---
name: worktree-sandbox
description: Work inside an isolated Git worktree, review or promote the diff, and race competing solutions with a verification command. Use when the terminal backend is `worktree`, when the user wants their checkout left untouched, or when there are several plausible approaches to the same change.
---

# Working with isolated worktrees

Your `terminal`, `execute_code`, `read_file`, `write_file`, `patch` and `search_files` calls may be
running inside an **isolated Git worktree**, not the user's checkout. When that is the case:

- The user's project files are **unchanged** until someone promotes the worktree.
- Say so in your final answer: "these changes are pending in worktree `X`" rather than
  "I changed your files".
- A background command left running inside the worktree dies with the worktree.

## Check state before claiming success

1. `worktree_status` — lists worktrees with `+added/-deleted` line stats. Call it before you claim a
   change is done.
2. `worktree_diff` — the unified diff the user would get from promoting.

## Promoting or discarding

- `worktree_promote` applies a worktree's changes into the real checkout. It **refuses** files the
  user edited since the worktree was created; re-run with `force: true` only after telling the user
  which files conflict. A timestamped backup is always written first.
- Ask before promoting when the user did not explicitly ask for it — promotion is the one
  irreversible-feeling step. `/sandbox promote <id>` does the same thing from a chat.
- `worktree_create` with a stable `task_id` reuses the same worktree, so a follow-up turn continues
  on the same changes.

## Racing several approaches (the interesting part)

When more than one implementation is plausible, do not guess — race them:

```
worktree_race(
  candidates=[
    {"label": "a", "files": {"src/parser.py": "<implementation A>"}},
    {"label": "b", "files": {"src/parser.py": "<implementation B>"}},
  ],
  verify_command="pytest -q",   # or the project's own test/lint/benchmark command
  promote_winner=false,         # set true only when the user agreed to apply the winner
)
```

Each candidate runs in its own isolated worktree, in parallel. The result is scored on
**pass/fail first**, then speed, then diff size — so a faster-but-wrong candidate never wins.
Report the leaderboard to the user, then promote only the candidate they pick.

Prefer the project's *own* verification (its test suite, type checker or benchmark) over a command
you invent.

## The `::worktree-card` directive

Hermes Desktop renders `::worktree-card{race_id="..."}` as an inline, interactive race card when the
plugin is enabled. Emit it on its own line, as an entire paragraph, right after a race:

```
::worktree-card{race_id="race-1a2b3c4d5e"}
```

Use the `race_id` from the `worktree_race` result. Other surfaces (CLI, TUI, messaging) show the
plain text instead, so always include the human-readable leaderboard too.

## Demo

`/sandbox demo` (or `hermes sandbox demo`) runs a self-contained offline race — no network, no API
key — seeding a small project and racing a failing candidate against a passing one. Useful for
explaining the feature to the user.
