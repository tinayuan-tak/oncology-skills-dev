<!-- See docs/DEFINITION_OF_DONE.md for the full contract. Delete rows that don't apply. -->

## What & why


## Definition of Done
- [ ] Own worktree off `main`; scoped `.claude/branch-scope`; registry entry if non-trivial
- [ ] `pixi run pytest` green from a clean checkout (blocking suites)

**If verdict-bearing** (resolvers / rule consumers / gate maps / card-field reads):
- [ ] Contract-conformance guards pass (verdict-consumers, `CARDS ⊆ cards_used`, field-name, reachability)
- [ ] Golden snapshots updated **intentionally** — a golden diff is a reviewed act: say what changed and why it is correct. (Do NOT argue the PR by whether the verdict moved; verdict movement is not a metric and verdict inertness is not a proof obligation.)
- [ ] `--verdict-only` parity holds; any new resolver verdict is handled by every consumer

**If touching cards / skills:**
- [ ] Consumed cards declared in `SKILL.md` `cards_used`; field reads exist in `outputs.summary_fields`
- [ ] No-data answers use the correct one of the four states (informative / data_unavailable / measured_negative / not_in_scope)
- [ ] Provenance wired; `run_health.status == ok` on a known-good target

## Notes for reviewers
<!-- golden diffs, cross-repo deps, parallel-session coordination -->
