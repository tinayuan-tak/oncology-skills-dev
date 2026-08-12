<!-- See docs/DEFINITION_OF_DONE.md for the full contract. Delete rows that don't apply. -->

## What & why


## Definition of Done
- [ ] Own worktree off `v2-architecture`; scoped `.claude/branch-scope`; registry entry if non-trivial
- [ ] `pixi run pytest` green from a clean checkout (blocking suites)

**If verdict-bearing** (resolvers / rule consumers / gate maps / card-field reads):
- [ ] Contract-conformance guards pass (verdict-consumers, `CARDS ⊆ cards_used`, field-name, reachability)
- [ ] Golden snapshots updated **intentionally** (or untouched because the change is verdict-inert)
- [ ] `--verdict-only` parity holds; any new resolver verdict is handled by every consumer

**If touching cards / skills:**
- [ ] Consumed cards declared in `SKILL.md` `cards_used`; field reads exist in `outputs.summary_fields`
- [ ] No-data answers use the correct one of the four states (informative / data_unavailable / measured_negative / not_in_scope)
- [ ] Provenance wired; `run_health.status == ok` on a known-good target

## Notes for reviewers
<!-- golden diffs, cross-repo deps, parallel-session coordination -->
