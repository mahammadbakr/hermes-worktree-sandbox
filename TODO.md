# TODO — `hermes-worktree-sandbox`

## Milestone 0–3 — DONE
- [x] Research, plan, repo scaffold (`RESEARCH.md`, `PLAN.md`, `DEMO.md`, README, LICENSE, CI)
- [x] **M1 vertical slice**: worktree terminal backend, manager, ledger, 4 tools (+ proof in real Hermes)
- [x] **M2 race arena**: `worktree_race`, shadow-Git fallback, 4 hooks, `/sandbox` + `hermes worktree` CLI
- [x] **M3 Desktop**: docked pane, status chip, palette commands, `::worktree-card` directive, dashboard API, bundled skill

## Hardening pass (feature freeze) — DONE
- [x] Adversarial review of usefulness / reliability / polish / creativity; weaknesses logged in README → Limitations
- [x] Failure-mode probes: missing config, wrong-typed inputs, awkward filenames, symlinks, very large
      and very numerous changes, concurrency, repeated load, ledger upgrade, git unavailable
- [x] Fix P0/P1: input validation, `-z` path parsing, symlink refusal, reported exclusions,
      `pre_verify` worktree selection, race input validation, bounded demo storage, no log noise
- [x] `ruff` clean, `mypy` clean, `pytest` 216 passed, `hermes plugins validate` 16/16 checks with 0 warnings
- [x] Catalog entry (`catalog-entry/worktree-sandbox.yaml`) + structural validator + payload scanner pass
- [x] Clean-install test (`scripts/clean_install.sh`): first success in ~5 s on a throwaway HERMES_HOME

## Submission (owner actions)
- [ ] **Create the public GitHub repo** `mahammadbakr/hermes-worktree-sandbox` (the name is assumed in
      `plugin.yaml` `homepage`, the catalog `repo`, and the README install line — change all three if
      the owner/name differs)
- [ ] `git push -u origin main` from the repo root
- [ ] Re-pin `sha` in `catalog-entry/worktree-sandbox.yaml` to the pushed 40-char commit
- [ ] Copy the entry to `plugin-catalog/worktree-sandbox.yaml` in a fork of `NousResearch/hermes-agent`,
      open the PR with the template in `docs/SUBMISSION.md`, and keep the PR to catalog files only
- [ ] Record the 90-second video from `DEMO.md`, post on X tagging @NousResearch, verify both links
      while logged out, submit through the entry form
- [ ] Join the Nous Research Discord and watch the entry's thread for maintainer questions

## Post-submission
- [ ] Address catalog review feedback; SHA bumps are their own PR
- [ ] Optional stretch: hunk-level cherry-pick UI in the Desktop pane
