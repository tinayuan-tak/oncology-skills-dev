---
name: compose-dashboard
description: |
  Iter-1 skill that consumes a dashboard_spec (target-contracts/dashboards/*.dashboard_spec.yaml)
  and an invocation context (target, indication, subgroup_spec, data_mode, release_pin) and
  produces a complete evidence_package.json (+ run_plan.yaml, dashboard.md, INDEX.md) in the
  data-products repo; the validation_summary is embedded in evidence_package.governance (there is
  no separate lockfile.yaml or validation_report.json — those were removed as phantom, see
  tests/test_envelope_integrity.py). The central iter-1 orchestration deliverable.

  Use this skill when: a contributor or downstream consumer asks to "evaluate target X in indication Y"
  via the v2 framework. It will (1) resolve manifests per data_mode, (2) build the context object,
  (3) for each card in the dashboard_spec: evaluate applies_when, invoke the method CLI, validate output,
  emit card entry, (4) run synthesis prompts, (5) compute validation_summary, (6) write the evidence
  package envelope.

  This skill is the iter-1 acceptance gate: criteria 1-3, 7 of B1's "Iter-1 done" all depend on its
  correct operation. See plan B1 § compose-dashboard behavioral spec for the runtime contract.

compute_mode: cross_product_synthesis
delegates_to:
  - methods/dge_deseq2/cli.py
  - methods/target_id_resolver
  - methods/depmap_chronos/cli.py            # iter-1 STUB; implementation pending
  - methods/gdc_somatic_hotspot/cli.py       # iter-1 STUB; implementation pending
  - methods/tempus_rwd_aggregator/cli.py     # iter-1 STUB; implementation pending
consumes_contracts:
  - target-contracts/schemas/card.schema.json
  - target-contracts/schemas/dashboard_spec.schema.json
  - target-contracts/schemas/evidence_package.schema.json
  - target-contracts/vocabularies/data_mode.enum.yaml
  - target-contracts/vocabularies/validation_state.enum.yaml
consumes_validators:
  - target-contracts/validators/validate_cards.py     # pre-invocation lint
produces_cached_artifact: true
cache_key: [dashboard_id, target, indication, subgroup_spec, data_mode, release_pin]
fan_out_strategy: sequential                          # iter-1 ships sequential; iter-2 may parallelize cards
status: operational                                   # all three phases (compose → execute → synthesize) ship; some phase-2 method CLIs are still iter-1 stubs (see delegates_to)
---

# compose-dashboard

**Status: all three phases implemented.** Per the plan's three-layer model
(see § Dashboard, Interpretation, Inference Layers), this skill runs in three phases, chained
end-to-end by `scripts/compose_dashboard.py`:

- **Phase 1 — compose**: resolve dashboard_spec + modality modules + subgroup_catalog
  into a deterministic `run_plan.yaml`. NO method execution; NO synthesis. Implemented in
  `scripts/compose_phase1.py` + `scripts/_resolution.py` + `scripts/_composition.py` + `scripts/_validation.py`.
  Run plan validates against `target-contracts/schemas/run_plan.schema.json`.
- **Phase 2 — execute**: take a run_plan.yaml, invoke each card's method CLI (some methods are
  still iter-1 stubs — see `delegates_to`), apply interpretation_hints, emit per-card outputs
  validating against per-method output schemas. Implemented in `scripts/_execution.py`.
- **Phase 3 — synthesize**: read per-card outputs, resolve each resolved-axis gate via the SHARED
  declarative resolver (`_skills_common.resolve_verdict_for_gate` over `target-contracts/resolvers/<gate>.resolver.yaml`),
  and emit the `evidence_package.synthesis` block with `primary_gate_verdict` + `additional_gate_verdicts`
  as the verdict spine. The per-modality `modality_fit_assessment` (fit_level, built from
  `modality_module.synthesis_emphasis` via `_build_signal_matrix`) is retained as an **optional lens**, NOT
  the verdict. Implemented in `scripts/_synthesis.py`.

  > **Phase-D convergence (2026-08-12, #375→#377):** this skill previously *reimplemented* the verdict
  > as the per-modality `fit_level` scorer (a SECOND composition engine that never called the resolver).
  > That reconstruction was deleted — compose-dashboard now shares the ONE resolver engine every standalone
  > skill and target-profile already use, so a new evidence facet can no longer drift between two engines.
  > `fit_level` survives only as a presentation lens. See `tests/test_engine_equivalence.py` for the pinned
  > cross-engine correspondence.

Each phase's output is independently validatable against a schema. The three phases are pipelined
deterministically: same inputs → byte-identical outputs at every phase.

## Iter-1 acceptance reference

The 7 "Iter-1 done" criteria in B1 reference this skill explicitly:

1. **Schemas validate** — relies on `validate_cards.py` pre-invocation lint.
2. **Cards emit clean** — this skill iterates cards and gates emission on validation_state.
3. **Dashboard composes** — this skill is what composes.
4. **Renders to markdown** — delegates to render-evidence-package skill.
5. **Concurrence recorded** — out of scope for this skill; verify_concurrence.py is separate.
6. **Card-invariance check passes** — this skill must produce byte-identical deterministic-field
   output on re-invocation against the same inputs (the `cache_key` tuple above).
7. **Negative-control refuses correctly** — this skill must emit clean evidence packages for
   (TG, COADREAD) with cards 1/4/5 excluded by applies_when and cards 2/3 as "not informative".

## Runtime behavior (per B1 § compose-dashboard behavioral spec)

Six subsections:
1. Manifest resolution algorithm — by data_mode
2. applies_when evaluator — CEL-compatible subset
3. Context object — built once per composition
4. Card execution model — sequential in iter-1
5. Validation timing — twice per card (pre + post)
6. Method output contracts — methods write to staging, this skill curates to data-products
7. Error semantics — structured failure, never silent

## Worked sequences

See plan B1 § compose-dashboard behavioral spec § Worked sequences for the two iter-1 acceptance
sequences: (KRAS, COADREAD) positive and (TG, COADREAD) negative-control.

## Dependencies that must be in place before this skill is implemented

- ✅ target-contracts/schemas/{card,dashboard_spec,evidence_package}.schema.json
- ✅ target-contracts/vocabularies/{data_mode,validation_state,concurrence_state}.enum.yaml
- ✅ target-contracts/validators/validate_cards.py
- ✅ target-contracts/cards/*.card.yaml (5 iter-1 cards)
- ✅ target-contracts/dashboards/target-in-indication.dashboard_spec.yaml
- ✅ methods/dge_deseq2/cli.py (R4 — carved out, CLI live)
- ✅ methods/target_id_resolver/ (R3 — carved out)
- ⬜ methods/depmap_chronos/cli.py (iter-1 NEW method; stub)
- ⬜ methods/gdc_somatic_hotspot/cli.py (iter-1 NEW method; stub)
- ⬜ methods/tempus_rwd_aggregator/cli.py (iter-1 NEW method; stub)
- ⬜ data-catalog/subgroup-catalogs/COADREAD/2026-Q2.yaml (R5 — authored)
- ⬜ canonical-decisions records for each input manifest

When the ⬜ items land, this skill's implementation is unblocked.
