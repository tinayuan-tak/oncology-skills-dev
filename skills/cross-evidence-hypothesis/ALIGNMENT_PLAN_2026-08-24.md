# Cross-evidence-hypothesis ↔ spine facet-layer alignment plan (2026-08-24)

Design note driving the multi-phase alignment of the `cross-evidence-hypothesis`
integrator with the target-profile spine's recently-added verdict-inert facet
layer (PRs #714–#736). Companion to
`target-contracts/docs/design/CROSS_EVIDENCE_INTEGRATION_ROADMAP.md`,
`CERTAINTY_MODEL.md`, and `VERDICT_REPRESENTATION.md`.

## Root finding

Almost all recent enrichment (`certainty_by_axis`, `cross_gate_shared_evidence`,
`fragility` + `acquisition_backlog`, `competitor_crossref`, `heterogeneity`,
`claim_record_shadow`) landed in **`nomination.json`**, NOT in the
**`evidence_package.json`** the integrator consumes. `_write_evidence_package`
(`tp_evidence_package.py`) is not passed these, so they never reach the
integrator's input contract. The integrator is therefore *structurally blind* to
the new facet layer — the fix is two-sided: extend the evidence-package contract
first, then wire the integrator to consume it.

Health baseline: 68/68 skill tests pass; the `DIMENSION_CARDS` mirror is in sync
with the spine (`test_dimension_cards_matches_spine`); no read-field renames.
This is enrichment, not repair.

`safety_verdict_by_modality` is a special case: computed in the safety sub-skill
headline + consumed internally by `tp_gates.py` for the `exists_safe_modality`
gate suppression, baked into `hard_gates` at compose time under the target-profile
run's `--modality`. The integrator takes its own `--modality` but cannot re-derive
the per-modality safety call because neither the block nor the composed modality is
carried in the package.

## Design decision

Add ONE verdict-inert sub-block `synthesis.decision_facets` to
`evidence_package.json`, carrying the decision-facing facets. Keeps them separate
from the recommendation spine (`sub_verdicts` / `recommendation_gate`), preserves
the "these never move the verdict" invariant, and gives the integrator one stable
read surface. All keys default-empty so a run that didn't compute them stays
byte-stable.

## Phases

### Phase 1 — target-profile: extend the evidence-package contract (PREREQUISITE)
Repo: claude-oncology-skills. Files: `tp_evidence_package.py`, `run.py`.
1. Widen `_write_evidence_package` (`tp_evidence_package.py:303`) with kwargs
   `certainty_by_axis`, `cross_gate_shared_evidence`, `fragility`,
   `competitor_crossref`.
2. Thread them at the call site (`run.py:558`) — all four already in scope.
3. Add `synthesis_block["decision_facets"] = {certainty_by_axis, cross_gate_shared_evidence,
   fragility, competitor_crossref}` (`tp_evidence_package.py:386`), default-empty.
4. Modality×safety: stamp `safety_verdict_by_modality` into the `safety` entry of
   `sub_verdicts` (recompute via `modality_safety.safety_verdict_by_modality` on the
   safety fired rules, mirroring `tp_gates.py:395`); record the composed modality at
   `synthesis.decision_facets.composed_modality`.
5. Tests: extend `test_cross_gate_shared_evidence.py` + evidence-package emit test;
   regenerate target-profile evidence-package golden fixtures.

### Phase 2 — integrator: modality×safety seam (priority #1)
Files: `hypothesis_core.py`, `run.py`.
1. Read `synthesis.decision_facets.composed_modality`; on mismatch vs resolved `--modality`, flag
   `degraded_mode.modality_mismatch` + surface a tension (hard_gates were frozen
   under the composed modality).
2. `gate_ceiling`: when `safety_verdict_by_modality` present + `--modality` set, use
   `svbm[modality].action` (`hold|conditional|supportive|not_applicable|no_concern`)
   to refine the hold-grade safety cap — `supportive`/`no_concern` should not force
   the blanket `advanceable_flagged` cap the scalar `safety` currently imposes
   (`hypothesis_core.py:422`). Fail-closed when absent.
3. Extend `_MUTANT_SELECTIVE_SAFETY` conditioning to read per-modality
   `wt_engagement` where present.

### Phase 3 — integrator: per-axis certainty (priority #2)
1. Reader for `synthesis.decision_facets.certainty_by_axis`.
2. Rewrite `weakest_link_certainty` (`hypothesis_core.py:525`) to take the base
   per-axis level from `certainty_by_axis[short].certainty.level` for in-scope axes;
   fall back to binary `_dim_certainty` for non-opted-in axes. Reconcile the
   `moderate`↔`medium` vocabulary (prefer adopting the spine's `low|medium|high`).
3. Fold `unknown_mass` into `data_gaps` / `go_forth`.
4. Quick win (no emit-side dep): cross-check computed certainty vs the
   already-present `synthesis.confidence_tier`; record divergence in
   `uncertainty.cap_reasons`.

### Phase 4 — integrator: cross-gate correlation (priority #3)
1. When `decision_facets.cross_gate_shared_evidence` present, prefer it over the
   self-derived `substrate_independence` (`hypothesis_core.py:485`) for the
   independence discount; keep `evidence_substrate` derivation as fallback +
   reconciliation cross-check (log divergence).

### Phase 5 — integrator: panel facets (priority #4)
1. Surface `fragility.contested` + `fragility.acquisition_backlog` +
   `competitor_crossref` into `_panel_block` (`run.py:342`) for
   `therapeutic_window` / `population` / `go_forth` reasoning. Tokens already in the
   citation surface (no traceability widening). Keep compact under the salience gate.

## Cross-cutting
- Drift golden: refreeze KRAS-COADREAD + MARK2-PAAD via
  `freeze_drift_golden.py --all --replay-only` (offline); update trimmed fixtures to
  include `decision_facets` + `composed_modality`; add modality-mismatch +
  `supportive`-channel fixture cases.
- Full suite from home checkout under `pixi run`: `_skills_common/`,
  `target-profile/`, `cross-evidence-hypothesis/`, `skills/tests/`; run
  `scripts/preland.sh` before landing.
- Docs: update `reads_spine_fields` in SKILL.md (add `synthesis.claim_vectors`,
  `synthesis.decision_facets.*` incl. `composed_modality`); bump 0.2.0→0.3.0;
  note roadmap §10 contract-test as now-worth-building.

## Sequencing
1. Phase 1 lands first (worktree scope `skills/target-profile/`).
2. Phases 2–5 in a second worktree (scope `skills/cross-evidence-hypothesis/`) once
   Phase 1 is on `v2-architecture`. Phase 2 quick-win + Phase 3 fallback can proceed
   in parallel (no new-block dependency).

## Do NOT
- Wire `claim_record_shadow` — zero-consumer M2 render-equivalence substrate;
  premature until M2 lands real consumers.

## Risks
- Parallel churn on `tp_evidence_package.py` / `run.py` — land Phase 1 small + fast.
- Byte-stability — guard all new keys default-empty (evidence-package only writes
  under `--emit evidence-package` / `--ground`).
- Modality `action` enum mapping — confirm `conditional` vs `hold` handling with the
  safety-skill owner.
