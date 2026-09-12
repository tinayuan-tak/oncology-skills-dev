# cross-evidence-hypothesis — finalized data product

The **I/O contract**: data reasoned IN, the bespoke package emitted OUT, what is locked. This is an
**auxiliary (non-fan-out) skill**, and a **BESPOKE** one: an LLM cross-skill SYNTHESIS integrator that
sits ABOVE target-profile and emits a gated therapeutic *hypothesis* — **not** the fan-out
`skill_decision` envelope. Logic + history live in SKILL.md / run.py; this file is the data-product spec.

| | |
|---|---|
| **Skill** | `cross-evidence-hypothesis` |
| **Skill code version** | 0.6.0 |
| **Contract version** | 1.0.0 (emitted-output schema; versioned independently — see §4) |
| **Role** | **integrator / gated synthesis** — the LLM PROPOSES a verdict; a DETERMINISTIC, FAIL-CLOSED, GATE-COMPLETE ceiling CLAMPS it (`computed = min(proposed_by_agent, gate_ceiling)` over `VERDICT_RANK`). It ENRICHES; it never OVERRIDES the spine |
| **Verdict field** | `verdict` — an **OBJECT** (`{proposed_by_agent, computed, gate_ceiling, was_clamped, promotion_capped, verdict_after_gate, gate_reason, active_vetoes, …}`), each rung ∈ `VERDICT_RANK`. TWO demotion mechanisms, reported apart: `was_clamped` = the spine's ceiling; `promotion_capped` = this hypothesis's own citation/coherence hygiene |
| **Output shape** | **bespoke `hypothesis.json`** — a single file (NOT the standard `write_package` `decision.json` tree; NO `run_health`). Carries a **top-level `skill_report`** (v0.6.0, UNIFIED_OUTPUT_CONTRACT, `role: descriptive`) but deliberately NOT `headline.skill_report` — `data_product_contract.is_full_decision` keys off that path and this is not a single-gate decision |
| **Emitted schema** | `target-contracts/schemas/skills/cross-evidence-hypothesis.emit.schema.json` — **HAND-AUTHORED** bespoke contract (the `.emit.` suffix, NOT the generated `.decision.` envelope schema; no pin, no cross-file `$ref`) |
| **Conformance target** | the **FRESH deterministic emit** — the real `run.py` over the frozen KRAS-COADREAD evidence package, driven by the canned two-call `llm_replay.json` via `run.replay_synthesize` (`llm_mode="offline_replay"`), exactly as `tests/test_drift_guard.py` does. No Bedrock / no S3; no stale hand-frozen decision fixture |

---

## 1. Inputs — reasoned-over evidence (composed artifacts, not cards)

This is a **META / non-evidence-composing** skill (`data_mode: catalog_read`): it composes NO cards and
fires NO interpretation rules. It reasons over ALREADY-composed, orthogonal grounded evidence — the
emitting skills (target-profile + fan-out) own the cards/rules.

| input (flag) | artifact | required |
|---|---|---|
| `--evidence-package` | a target-profile `evidence_package.json` — the indication-conditioned sub-verdict panel + cards + `synthesis` (recommendation_gate.hard_gates, sub_verdicts, claim_vectors, decision_facets) + `subtype_resolved` | **REQUIRED** |
| `--target-dossier` | a target-intrinsic `decision.json` (indication-INDEPENDENT target biology) | optional |
| `--risk` | a 6-dimension literature-risk `decision.json` (the retrieved-PMID surface for retrieve-don't-recall) | optional |
| `--substrate AXIS=PATH …` | per-subskill GROUNDED SUBSTRATE blocks (`ground_axis` output); enrich the panel + make PMIDs citable + surface engine↔literature discordance — **escalate-only** (never lowers the ceiling) | optional |
| `--modality` | controlled enum (small_molecule / degrader / molecular_glue / rna_therapeutic / adc / bite_tce / antibody / modality_agnostic); else inferred from `--objective`; scopes which sub-verdict axes are in play | optional |

The **spine fields read** are pinned in SKILL.md `composition.reads_spine_fields` (a rename is visible in
review). A missing dossier / risk read degrades certainty (capped `low`) and is FLAGGED — it never
silently inflates certainty or raises the ceiling.

---

## 2. Coverage & capability ceilings (contractual)

- **The integrator ENRICHES; it never OVERRIDES** (roadmap invariant §1). The LLM proposes a verdict but
  a deterministic, fail-closed, gate-complete ceiling (`hypothesis_core.gate_ceiling`, consuming
  `synthesis.recommendation_gate.hard_gates`) CLAMPS it: `computed = min(proposed_by_agent, gate_ceiling)`
  over `VERDICT_RANK`. The emitted verdict is NEVER more permissive than the spine; a clamp is SURFACED
  as `verdict.gate_clamp_tension`. A package with no parseable `synthesis` → `declined`; a `hard_gates`
  block absent (older package) → fail-closed rec-gate + sub-verdict kill scan (never fail-open).
- **The pre-clamp proposed verdict + all clause prose are an LLM sample and are NOT reproducible** (the
  manifest is an as-of-date archival read). Only the DETERMINISTIC SPINE — the ceiling + clamp,
  clause-traceability score, the promotion cap, computed certainty + cap ceiling + the per-axis histogram,
  the per-view independence counts, data gaps + not-scored
  axes, substrate-discount + tagging coverage, intra-package coherence, the prose-free `skill_report`
  fields, and the two provenance PINS (`prompt_template_hash` + `model_id`) — is run-to-run stable, and it
  is exactly this spine that `tests/test_drift_guard.py` freezes for KRAS-COADREAD + MARK2-PAAD. Both
  frozen cases predate #1310, so the golden pins the roles-UNKNOWN / untagged FALLBACK path; the
  role-aware and independence-capped paths are covered by unit tests
  (`tests/test_skill_report_and_teeth.py`) until a third case is frozen from a fresh package.
- **Defensibility is an ENFORCED contract WITH TEETH**: retrieve-don't-recall PMIDs (an ASSERTED PMID —
  explicitly cued, or a bare identifier list — must be an exact member of the risk/substrate retrieved set,
  no substring escape; digits inside prose are data, not a PMID claim, and still have to resolve as part of
  the residual), clause-traceability (untraceable citation → `promotable: false` + verdict capped
  `advanceable_flagged`), absence-discipline (an absent/insufficient line supports nothing, matched at the
  same word-boundary grain traceability credits), independence-before-certainty, and always-on intra-package
  COHERENCE (a positive-thesis clause may not rest on a signal another present signal contradicts unless the
  tension is surfaced).
- **Independence-before-certainty counts TAGGED substrates only** and is GRADED (1 unit → `low`,
  2 → `moderate`, ≥3 → uncapped). An untagged card is missing provenance, not proven independence:
  counting it as its own unit made the control inert (121–125 "independent" units on real packages). Where
  substrate tagging covers a MINORITY of cards, the substrate view ABSTAINS from the unit cap
  (`tagging_sparse: true`) and only a declared-blindness `moderate` cap applies — a pipeline metadata gap
  is not charged to the target. The spine's decision-gate-group view (`cross_gate_shared_evidence`) still
  caps in that case; the binding view is the LOWER of the views that are AUTHORITATIVE and is named in
  `independence_unit_kind`. `independence_view_authoritative: false` means NO view could speak (sparse
  tagging AND no `cross_gate_shared_evidence` facet), not merely that the substrate view abstained — with
  the gate facet present it reads `true` while naming `decision-gate-group`.
  **In production the substrate view therefore never participates at all.** `tagging_sparse` is `true` on
  20/20 panel targets by construction, so the substrate view is excluded from the candidate set on every
  real package and `independence_unit_kind` is `decision-gate-group` on 20/20;
  `n_independent_substrate_units` is computed, emitted, and never consumed by a cap. Two consequences worth
  stating plainly: (a) the effective independence control is the gate-group view alone, and (b) because
  `n_distinct_substrates` cannot exceed the TWO entries in the `evidence_substrates` vocabulary, the
  substrate view reads exactly `2` on all 20 targets and could never reach the `>= 3` uncapped rung even
  with perfect tagging. The remedy is therefore MORE DISTINCT SUBSTRATES in
  target-contracts `vocabularies/measurement_types.yaml`, not wider tagging of the two that exist — the
  same root cause as the `tagging_sparse` floor below, and out of scope for this skill. **Each reported quantity answers exactly one
  question**: `independence_view_authoritative` (could the read speak) is separate from
  `independence_cap_binding` (did it lower anything), because an authoritative view finding ≥3 units caps
  nothing; and each unit count is named by view (`n_independent_substrate_units` vs
  `effective_independent_units`) rather than one of them claiming the unqualified name.
- **`tagging_sparse` says WHOSE gap it is.** On the 2026-09-12 20-target panel it was `true` on every
  target, which makes it undiscriminating on its own: `evidence_substrate` is declared on MEASUREMENT_TYPES
  (target-contracts `vocabularies/measurement_types.yaml`), and that vocab currently has TWO substrates
  carried by 16 of 140 types, reaching ~16% of cards — so the 0.5 coverage floor is unreachable by
  construction and no per-run care can move it. The remedy is therefore not a lower floor (which would
  fabricate confidence in a lens that genuinely sees 14% of the package) but an ATTRIBUTION, computed from
  the package alone: `substrate_vocabulary_limited: true` means the emitter stamped every card it could and
  the vocabulary names no substrate for this evidence (a contracts gap), while
  `n_untagged_no_measurement_type` is the separate per-card registry back-ref debt — and that one DOES
  discriminate across targets (5 on EGFR/NSCLC to 42 on RBM39/AML on the same panel). All three fields are
  disclosure: no unit count, cap or verdict reads them.
  Read honestly, `substrate_vocabulary_limited` was ALSO `true` on 20/20 panel targets, so it does not
  discriminate on this panel either — but it is reachable-but-unexercised, not unreachable-by-construction,
  and the difference is the whole point. The 0.5 floor could not be cleared by ANY target while the vocab
  covers ~14% of cards; this flag flips `false` for a target whose untagged remainder is dominated by
  missing registry back-refs rather than vocabulary gaps (RBM39/AML is the closest approach at 77 vs 42),
  and `tests/test_skill_report_and_teeth.py` pins that `false` branch rather than leaving it to a future
  panel. The quantity to READ per target is `n_untagged_no_measurement_type`; the boolean is an
  attribution label on a fact about the CONTRACTS, and it will stay constant until
  `measurement_types.yaml` grows substrates.
- **`limiting_dimension` names a GATING axis; `binding_axis` is the one that set the level.** These are
  deliberately different questions and they can give different answers, so the artifact states both. The
  headline is the conjunctive minimum over EVERY scored in-scope axis, while the limiting attribution is
  restricted to `role=gating` (a descriptive lens that gates nothing must not be rendered as the thing
  limiting the decision). On the 2026-09-12 panel ERBB2/BRCA therefore emitted `overall_certainty: low`
  beside `limiting_dimension: mechanism` — and mechanism was `moderate`; the axis that actually bound was
  the non-gating `subtype_fit`. A reviewer acting on the named axis there would fund mechanism work and
  the certainty would not move. `limiting_dimension_is_binding: false` says to read `binding_axis`
  instead. Only 1 of 20 targets showed the symptom, but that is LUCK: `binding_axis` is non-gating on
  5 of 20 (3 inert, 1 descriptive, 1 role-unknown) and a gating axis merely TIED at the minimum on the
  other four — `n_binding_axes > 1` is what hides it. `binding_axis_role: null` is a THIRD role state,
  distinct from a declared `descriptive`/`inert`: the axis is absent from `synthesis.skill_reports`
  altogether, as `subtype_fit` is on 12 of 20 targets, so it is not in `not_scored_axes` and is silently
  eligible for the headline minimum. That is a #1310 PRODUCER gap, not fixable in this integrator. All
  six fields are disclosure — the headline level, the limiting name and the histograms are unchanged.
- **Every cap the certainty math CONSIDERED is listed, and the level they permit is stated**
  (`cap_reasons` + `cap_ceiling`), so `base_certainty / cap_ceiling / overall_certainty /
  certainty_capped` read as one coherent statement — on a `low` base the listed caps bind nothing and a
  reader can see the base is what bound. The spine `confidence_tier` cross-check is NOT a cap and lives
  in its own field (`spine_tier_divergence`): it observes two reads disagreeing and lowers nothing.
- **Axis ROLES are read, not assumed** (`synthesis.skill_reports`, #1310). A `role=descriptive`/`inert`
  axis with no call is GATELESS BY DESIGN — excluded from `data_gaps`, from the supporting-line count, and
  from the limiting-axis attribution (restricted to `role=gating`). `overall_certainty` stays the
  conjunctive weakest link; because that minimum is `low` on essentially every real package, the
  DISTRIBUTION is emitted alongside it (`certainty_by_axis`, `n_axes_by_level`, gating-only slice). A
  package with no `skill_reports` reports roles as UNKNOWN (`axis_roles_present: false`, gating slice
  `null` — NOT a zeroed histogram, which would assert every axis is decorative) and falls back to the
  pre-#1310 behaviour.
- **Modality is a controlled enum**, not `objective.startswith()`; an out-of-scope axis (e.g.
  surface-modality for a small molecule) is surfaced as `modality_excluded`, never a data gap and never a
  degradation. Scope is by axis OWNERSHIP, not name shape: a multi-lens card is in scope when ANY owning
  dimension is. `immune_context` is IN scope for all three antibody-derived channels (adc / antibody /
  bite_tce).

---

## 3. Emitted output

`hypothesis.json` (a single file under `--out`; bespoke, NOT a `write_package` tree). Top-level keys:
`skill · skill_version · target · indication · objective · modality · hypothesis · edges ·
evidence_paths · verdict · defensibility · uncertainty · evidence_independence · subtype_resolved ·
degraded_mode · grounded_substrate · quality · provenance · panel_conviction · skill_report`.

`skill_report` (v0.6.0) is the UNIFIED_OUTPUT_CONTRACT view built by
`_skills_common.skill_report.build_skill_report`, so the framework's TERMINAL synthesis is readable by the
same report/rollup/dashboard layer as every emitting skill. `role: descriptive` / `polarity: not_scored`
(this integrator sits ABOVE the nomination and must never feed back into gate math); `call` is the FINAL
clamped verdict, built AFTER the promotion cap; `provenance.cards_used` / `fired_rule_ids` are empty BY
CONSTRUCTION (`data_mode: catalog_read`). Four claim atoms — `gate_agreement`, `clause_traceability`,
`intra_package_coherence`, `evidence_independence` — are the integrator's readings of its OWN hypothesis,
not biology-card signals (a `_disclaimer` says so in the artifact); non-atom scalars (`certainty`,
`n_axes_by_level`, `n_gating_axes_by_level`, `n_data_gaps`, `n_not_scored_axes`, `limiting_gating_axis`,
`promotable`, `modality`) are carried losslessly for a rollup reading a coordinate off the report.

Contractual (locked — see §4): the top-level identity (`skill` const, `skill_version`, `target`,
`provenance` with `generated_at`); the gated **`verdict` OBJECT** (`proposed_by_agent` / `computed` /
`gate_ceiling` each ∈ `VERDICT_RANK`); `modality.resolved` ∈ MODALITY_SCOPE; the six-part
`hypothesis` (`hypothesis.evidence_grade.overall` ∈ {strong, moderate, weak, insufficient};
`hypothesis.therapeutic_hypothesis.modality` ∈ MODALITY_SCOPE); and typed `edges[].type` ∈
{conditions, tensions_with, corroborates, contradicts}. All LLM-authored clause prose (statements,
rationales, citations text) is schema-**open** (`additionalProperties: true`) — inherently fluid and
prompt-hash nondeterministic.

---

## 4. Contract & versioning (what is locked)

Pinned by the **hand-authored, self-contained** `cross-evidence-hypothesis.emit.schema.json` (the `.emit.`
suffix flags a bespoke aux-skill emit — NOT the generated fan-out `.decision.` envelope; no pin, no
cross-file/network `$ref`). It `required`s `[skill, skill_version, target, verdict, hypothesis,
provenance]`, locks `skill` = `const` + the `verdict`-object / edge-type / modality / evidence-grade
enum vocabularies + `provenance.generated_at` presence, and is `additionalProperties: true` throughout
so the LLM prose stays open. Append-only within contract major version.

CI: fresh-replay conformance (`tests/test_data_product_schema.py`, CI-fail-not-skip — the real run.py
over the frozen golden llm-replay, no Bedrock) + schema-well-formedness; the offline golden-set drift-CI
(`tests/test_drift_guard.py`, freezing the deterministic spine + the two provenance PINS); the
cross-skill coverage ratchet (`skills/tests/test_data_product_lock_coverage.py`); and the
target-contracts schema meta-test. Change policy: a new verdict token → add to the `VERDICT_RANK` enum
in the hand-authored schema (coordinate with `hypothesis_core.VERDICT_RANK`; minor); a top-level identity
key rename → major; a new open LLM/clause field → no schema change.

## 5. Known gaps & notes (non-blocking)

- **Schema is HAND-AUTHORED, not generated** (unlike the 14 fan-out `.decision.` schemas): it deliberately
  does NOT track every open sub-field of `defensibility` / `uncertainty` / `evidence_independence` /
  `degraded_mode` / `grounded_substrate` / `quality` / `panel_conviction` — those stay
  `additionalProperties`-open by design. It pins identity + the closed enum vocabularies + provenance
  presence; deeper field-fidelity is intentionally deferred (the drift-guard, not the schema, is the
  spine-stability check).
- **`quality.adversarial_survival` is `null`** in the emit unless the OPT-IN Bedrock skeptic post-check
  (`scripts/adversarial_survival.py`) is run; the always-on offline `coherence_violations` guard is its
  deterministic sibling. The conformance target (offline replay) exercises the null-slot path.
- **The pre-clamp proposed verdict + clause prose are non-reproducible** (LLM sample); the drift-CI
  freezes only the deterministic spine + the two provenance PINS, and regenerates the golden on a
  reviewed, deliberate prompt/schema/resolver change (`scripts/freeze_drift_golden.py`).
- **`composition.output_shape: data_package`** in SKILL.md is the framework enum; the concrete emit is
  the single bespoke `hypothesis.json` (no `decision.json` / cards tree).
