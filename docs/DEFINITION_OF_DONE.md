# Definition of Done — claude-oncology-skills

A change is "done" when it satisfies the checks below. These encode the invariants the framework's
guards already enforce in CI; the list makes the contract explicit for authors and reviewers.

## Every change
- [ ] Runs in its **own worktree** off `main`; landed via `land-pr` (auto-merge on green).
- [ ] `.claude/branch-scope` declares exactly the paths touched (grab-bag prevention).
- [ ] Registry entry in `~/.claude/wip-registry.md` for non-trivial work (`depends_on` set).
- [ ] `pixi run pytest` green from a clean checkout (blocking suites: `_skills_common`,
      target-profile, `skills/tests/`). Live-S3 tests self-skip credential-less — never assert on availability.

## Verdict-bearing changes (resolvers, rule consumers, gate maps, card-field reads)
- [ ] **Contract conformance green** — the cross-skill guards must pass:
      resolver-verdict consumers (`test_resolver_verdict_consumers`), `CARDS ⊆ cards_used`
      (`test_cards_used_declares_consumed`), field-name reads ⊆ card `outputs.summary_fields`
      (`test_card_field_conformance`), and resolver **reachability**.
- [ ] **Golden snapshots updated INTENTIONALLY**, never blindly regenerated. A golden diff is a
      reviewed act — explain *what* changed in the output and why that output is now correct.
      **Do not argue the change by whether the verdict moved.** Verdict movement is not a metric and
      verdict inertness is not a proof obligation (owner directive 2026-09-29, SK#2091): "the spine is
      unchanged" is not a defence of a wrong number, and "the spine moved" is not an objection to a
      right one. Correctness is argued at the data/logic level, with mutation teeth.
- [ ] `--verdict-only` / lean read stays **byte-identical** to the full-read verdict (parity guard —
      this is a two-read AGREEMENT contract, not a non-movement claim about a diff; it stays).
- [ ] A new resolver verdict is **classified by every Python consumer** (add it to the relevant
      set/map, or waive with a documented reason — the guards fail otherwise).

## Cards & skills
- [ ] Every card the skill consumes is declared in `SKILL.md` `composition.cards_used`.
- [ ] Field reads use names that exist in the card's `outputs.summary_fields` (no silent-None drift).
- [ ] A card's honest no-data answer is one of the **four states** — `informative` /
      `data_unavailable` (applies_when false / no shard) / `measured_negative` (real negative) /
      `not_in_scope` (subgroup card without a subgroup_spec) — never conflated.
- [ ] Provenance wired: emitted cards resolve to a data source + manifest + method git-sha.
- [ ] `run_health.status == ok` on a known-good target (no false `degraded`).

## Cross-repo
- [ ] Card/rule/manifest references in `cards_used` / `rules_scope` exist in target-contracts /
      analysis-methods / data-catalog. Check the registry for active refactors before extending them.
