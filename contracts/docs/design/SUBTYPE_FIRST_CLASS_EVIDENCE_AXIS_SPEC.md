# Design Spec — Subtype as a First-Class Evidence Axis for the Integrator

**Status:** Drafted 2026-08-16 from a grounded investigation of the current iDAS/subtype
integration. Details `CROSS_EVIDENCE_INTEGRATION_ROADMAP.md` §13 (multi-indication/subtype grain).
Companion to `IDAS_SUBTYPE_PIPELINE.md` (the substrate design) and
`PATHWAY_NODE_LEVERAGE_SPEC.md` (a sibling axis).

Portable GFM per the `README.md` format rules (no Mermaid/HTML).

---

## 1. The problem (current state, grounded)

The objective is target × indication × **subtype** reasoning. But subtype is built at the
data/method layers and **collapses to near-nothing by the time it reaches the cross-evidence
integrator**:

- **Cards are verdict-inert.** All four subtype cards (`subgroup-stratified-dependency`,
  `subgroup-stratified-mutation-frequency`, `tumor-rna-distribution-by-subtype`, dormant
  `subgroup-stratified-expression`) are DISPLAY-ONLY panoramas — their caveats state
  "emits no verdict signal" / "subtype is confidence/context … NOT a new veto".
- **target-profile subtype tier is opt-in + negative-selection only.** `--subtypes` gates it;
  `_subtype_verdict` (run.py:432) can only return `subtype_specific_non_dependence` → a *hold*;
  a positive/absent finding returns `None` and can never lift a nomination.
- **Per-stratum signal doesn't reach an agent-facing slot.** With `--subtypes`, the package carries
  a single scalar `sub_verdicts.subtype_fit` + raw `per_subgroup_metrics` buried in two card blobs;
  `input_context.subgroup_spec` is hardcoded `null` (run.py:4681); the subtype cross-axis
  convergence facet is dropped from the package (goes only to nomination.json).
- **The integrator never parses it.** `hypothesis_agent.py::assemble` flattens each card to its
  scalar `interpretation_call`, never reads `per_subgroup_metrics`/strata, and isn't told the scoped
  subtype. So `population.subtype_or_biomarker` is LLM free-text, unanchored — the agent can *name*
  a subtype but cannot reason "dependency is strong in MSS but absent in MSI-H."

The pipeline design (`IDAS_SUBTYPE_PIPELINE.md`) is largely aspirational; live today are the
substrate (8 indications' strata specs, 3 assigner methods, per-sample assignment parquets) and the
four descriptive cards.

## 2. The central thesis (resolves the philosophy tension)

The framework deliberately made subtype **context, not a gate** (the cards say so). That is CORRECT
and should be preserved. The two-layer architecture gives subtype a natural home:

> **The deterministic spine keeps subtype verdict-inert (context, negative-selection hold only).
> The CROSS-EVIDENCE INTEGRATOR is where subtype-resolved REASONING belongs.** "Promote subtype to a
> first-class axis" therefore means: make the per-stratum SIGNALS machine-readable and
> agent-consumable — NOT make them hard-gate verdicts.

This aligns exactly with the integrator's design (it *enriches*; it never *overrides*). Subtype
becomes a first-class **evidence/context** axis the integrator triangulates over, without changing
the spine's deliberate verdict-inert treatment or the monotone-safety clamp.

## 3. Philosophy decision to confirm (D1)

- **Option A — subtype as first-class integrator EVIDENCE (recommended).** Spine unchanged
  (subtype stays verdict-inert; negative-selection hold preserved). Work = surface per-stratum
  signals into a machine-readable package block + have the integrator consume them + reason at
  subtype resolution. Lower risk; no philosophy break; delivers the objective's subtype reasoning.
- **Option B — subtype becomes verdict-BEARING in the spine.** Implement the designed
  `subtype_fit_*` channels as resolver rules that can hold/condition. Larger; changes the
  "subtype = context" design; asymmetry must still hold (a subtype finding may HOLD a subtype, never
  MINT a nomination from ignorance). Defer unless A proves insufficient.

Recommendation: **do A now, keep B as a documented follow-on.** The rest of this spec assumes A.

## 4. Target end-state

A target-profile run (with subtype strata available for the indication) emits a first-class
`subtype_resolved` block the integrator consumes, so the hypothesis's `population`, `causal_rationale`,
and `therapeutic_window` clauses can carry **subtype-resolved, cited** reasoning
("dependency is strong in MSS (n=NN, Chronos −0.6) but absent in MSI-H"), traceable to per-stratum
records — while the deterministic nomination still rests on the aggregate + the existing
negative-selection hold.

## 5. Workstream components (build order)

1. **Package: first-class `subtype_resolved` block** (skills `target-profile/run.py`
   `_write_evidence_package`). Fix `input_context.subgroup_spec` (stop hardcoding `null`; record the
   requested/available strata). Emit, per requested stratum: the per-stratum verdict/effect-size
   from `per_subgroup_metrics` (dependency + mutation-frequency today), `evidence_state`,
   `subgroup_n` / floor-met, and the dropped subtype convergence facet (`_subtype_facet`). Additive,
   schema-versioned; default runs without strata emit an empty/absent block (byte-stable).
2. **Package schema** (target-contracts `schemas/evidence_package.schema.json`) — add the optional
   `subtype_resolved` object (requested_strata + per-stratum records + convergence facet).
3. **Integrator consumption** (`hypothesis_agent.py`): parse `subtype_resolved`; add per-stratum
   tokens to the citation surface (so subtype claims are traceable, not free-text); extend the prompt
   so `population`/`causal_rationale`/`therapeutic_window` can express subtype-resolved reasoning; the
   agent header must state the scoped subtype (from `subgroup_spec`, now populated). SOFT: subtype
   never raises certainty beyond what the per-stratum n supports; absent strata → no weight.
4. **Availability (opt-in → discoverable):** make the run auto-attach strata when the indication has
   an iDAS spec (or clearly document that batch runs feeding the integrator must pass `--subtypes`),
   so the integrator actually sees subtype signal in practice.
5. **(Follow-on, Option B) verdict-bearing `subtype_fit_*` channels** — only if A proves insufficient;
   own spec, must preserve the never-lift asymmetry + monotone-safety.
6. **(Follow-on) subtype-stratified siblings for more axes** — today only dependency + mutation-freq
   are stratified; expression is dormant. Additional stratified siblings (genomic, safety-window)
   would deepen subtype-resolved reasoning; each is its own card + assigner-backed method.

## 6. Invariants
- Spine unchanged under Option A: subtype cards stay verdict-inert; the negative-selection
  `subtype_specific_non_dependence → hold` is preserved; no positive subtype signal enters the hard gate.
- Subtype is SOFT integrator context: never raises certainty beyond per-stratum n; never overrides a
  gate; a stratum below its n-floor carries no weight (absence-discipline at stratum grain).
- Every subtype claim in the hypothesis must be traceable to a per-stratum record in the
  `subtype_resolved` block (clause-traceability extends to stratum tokens).
- Package remains byte-stable for default (no-strata) runs.

## 7. Collisions + coordination
No active wip-registry entry owns this integration surface. Coordinate with: the two open
analysis-methods assigner PRs (`subgroup_assigner_directly_tagged` burndown; `subgroup_assigner_maf_filter`
WT-denominator fix — reader-robustness only) before editing `subgroup-stratified-*` cards; and the
target-contracts validator-hardening entry (touches `subgroup-stratified-expression` blocked-status +
a `tumor-rna-distribution-by-subtype` back-ref). The `subtype_resolved` package block, schema field,
and agent consumption are on otherwise-unowned paths. Worktree-per-workstream per CLAUDE.md.

## 8. Acceptance criteria + effort/risk
- A `--subtypes` run emits a machine-readable `subtype_resolved` block (populated `subgroup_spec` +
  per-stratum records + convergence facet); default runs stay byte-stable.
- The integrator produces subtype-resolved population/causal reasoning that passes clause-traceability
  against per-stratum tokens (demonstrated on an MSI-H/MSS COADREAD or NAPY-strata SCLC case).
- Spine nomination/verdict byte-identical to pre-change (Option A changes nothing in the gate).
- **Effort:** Medium (package block + schema + agent consumption); the substrate + cards already exist.
- **Risk:** Low–Medium — additive + spine-invariant under Option A; main risk is the agent
  over-claiming subtype reasoning beyond per-stratum n (mitigated by the traceability + n-floor invariants).

**Proposed branches:** skills `feat/subtype-resolved-evidence-block` (scope
`skills/target-profile/`, `skills/_skills_common/` if needed); target-contracts
`feat/evidence-package-subtype-resolved-schema` (scope `schemas/`, `tests/`); integrator changes ride
the hypothesis-agent productionization (WS4).
