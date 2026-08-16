# Per-dimension evidence representation + grounded-agent reasoning

**Status:** DRAFT for discussion (2026-08-15) · owner: ryan.abo
**Supersedes intent of:** the single categorical nomination call in `target-profile`
**Related:** `portfolio/takeda-onc.portfolio_spec.yaml` (Stage-4 `pareto_dimensions`),
`validators/validate_framework_discrimination.py`, `resolvers/*.resolver.yaml`,
`vocabularies/nomination_verdict_gate.yaml`

---

## 1. Problem

`target-profile` collapses ~10 sub-verdicts into ONE categorical call
(`nominate`/`hold`/`veto`) via an asymmetric gate (`veto` dominates `hold`; positive
signals only *floor* confidence, never mint a nomination). Three limits:

1. **The single call is too rigid** for the target × indication × subtype × modality
   space — a target can be strong biology / weak modality-fit / blind on biomarker, and
   "hold" throws that structure away.
2. **A calibrated global score is not defensible.** The known-target label set is small,
   and `advanced`/`active` labels are program-status, not target-quality (e.g. MARK2/3
   advanced but never beat YAP/TAZ efficacy). We cannot honestly fit/​calibrate a
   P(success) score. (See PR #367: the discrimination harness now segregates the 5
   drug-backed silent-FNs from 7 program-status ones.)
3. **The framework is blind on the deciding axis for 75% of known targets**
   (discrimination harness). A fully deterministic framework for *all* target types is a
   losing battle — surface-antigen density, internalization, avidity, cell-state windows,
   and SL context resist rule formalization.

**Goal:** capture all key evidence, distil it, and present it effectively **with certainty
attached** — per decision *dimension*, conditioned on the *objective* — rather than a
single collapsed verdict. Push scoring DOWN to the axis/dimension level; make any roll-up
optional and explicitly relative (evidence-strength, NOT probability of success).

---

## 2. Core model — three separable dimensions per axis

Every axis emits a triple. Critically, none of the three needs an outcome label:

| Property | Answers | Derived from | Lives in |
|---|---|---|---|
| **Strength** (signed) | How strong is the signal, and which direction? | within-axis effect size, n, and the `-supportive`/`-killer`/`-warning`/`-neutral` suffix on `fired_rule_ids` (sign) | evidence engine (deterministic) |
| **Certainty** | How much of the evidence do we actually have, and does it corroborate? | coverage (measured vs `insufficient`/`data_unavailable`/blind) + cross-comparator agreement → an explicit **unknown mass** (Dempster–Shafer flavour) | evidence engine (deterministic) |
| **Relevance** | Does this evidence bear on THIS objective / indication / modality? | objective-conditioned weights + in/out-of-scope rules | **explicit spec** (portfolio_spec-style), NEVER the evidence engine |

**Why relevance is separate and not folded into strength:** a maximally strong, certain
signal can carry zero decision-weight for the question asked (pan-essentiality is strong,
certain, and its relevance to "selective drug target" is *negative*; an off-lineage
dependency is strong but low-relevance for indication Y). In Bayesian terms relevance is a
question-conditioned likelihood ratio — it *multiplies* strength, not adds. Keeping it in
the explicit preference spec is what keeps the evidence honest and the objective auditable
(the portfolio_spec header already mandates this separation).

---

## 3. Dimensions — the 7 drug-discovery risk categories (AstraZeneca 5R)

**Taxonomy DECIDED** in `RISK_CATEGORY_DASHBOARD_SPINE.md` (2026-07-21): the dimensions are the
7 committee-facing risk categories, anchored to the **AstraZeneca 5R framework** (Cook et al.,
Nat Rev Drug Discov 2014) — a VIEW grouping the existing gates/sub-skills, not new science. Each
category carries TWO reads: a **conviction read** (deterministic axes — strength+certainty, §2)
AND a **risk read** (the risk lens, §5.2). They map onto the parked `pareto_dimensions` and roll
up member-gate statuses via `_gate_scorecard` (so a category rollup can never disagree with its
per-gate verdicts).

| Category | 5R pillar | Member axes / sub-skills | Gate semantics |
|---|---|---|---|
| **Biological** | Right Target | dependency, genomic_alteration, mechanism (+ presence) | independent |
| **Biomarker** | Right Patient | mutation×dependency, expr×dependency, CRISPR×RNAi, predictability, SL, subtype | independent (own category — DECIDED, peer of Right Target) |
| **Druggability** | Right Target (tractability) | tractability_sm, surface_modality | **scoped gate** — forecloses a *modality*, not the target |
| **Safety** | Right Safety | safety, selectivity | **scoped gate** — forecloses a *full-KO modality*; mechanism-conditioned |
| **Translational** | Right Tissue | translational-readiness (model-availability; PD/TE via risk lens) | independent (partial/blind) |
| **Clinical** | (practical 6th bucket) | clinical precedent (risk lens; license-walled) | risk-lens only |
| **Commercial** | Right Commercial Potential | differentiation (co-mutation) + competitive/IP (unlicensed) | independent (Differentiation folded here — DECIDED) |

**Independent vs scoped-gate is the load-bearing distinction:**
- Most categories are **independent** — reported side-by-side, none vetoes another. The
  output is a *profile*, not a scalar.
- Safety and Druggability (representation-feasibility) are **scoped gates** — they gate
  *within their scope* (safety concern ⇒ "full-KO modality unfavourable", not "not a target"),
  which fixes the positive/veto asymmetry: the veto stays inside its dimension.
- **Relevance decides which categories are even shown**: an SM objective puts the
  surface arm of Druggability out-of-scope; an ADC objective inverts it.
- **Data-driven surfacing** (spine decision 4): a category is shown IFF ≥1 member sub-skill
  fired this run — no not-wired placeholder rows; absence is itself the honest signal, noted
  in a compact "categories not yet evidenced: …" footnote.

---

## 4. Output shape — a per-dimension panel, not a scalar

Primary artifact = an objective-conditioned panel. Example, real KRAS/COADREAD extraction,
objective = small-molecule drug target:

```
KRAS / COADREAD   (objective: small-molecule drug target)
  Biological conviction   STRONG      certainty: HIGH   [lineage_selective + biomarker_stratified + well_characterized]
  Biomarker / selection   STRONG      certainty: HIGH   [G12C mutation-selective dependency]
  Modality fit (SM)       FAVORABLE   certainty: MED    [tractability well_covered] · surface: out-of-scope (intracellular)
  Safety headroom         CAVEATED    certainty: MED    [WT-constraint, downgraded for mutant-selective]
  Differentiation         NEUTRAL     certainty: LOW    [both co-mutation patterns present]
```

- No forced single nomination. A biologist reads N independent, scoped calls each with its
  own certainty.
- **Optional** relevance-weighted roll-up for triage: `Σ relevance(axis|objective) × sign ×
  strength`, certainty carried alongside (not merged in). Aggregate like the **Open Targets
  association score** (harmonic-sum, rewards independent lines) — and label it *evidence
  strength (relative)*, explicitly NOT P(success). Precedents to mirror: Open Targets
  association score, GRADE (certainty tiers), ACMG/ClinGen (combine evidence of different
  strengths by explicit rules, not arithmetic).

---

## 5. The agent layer — grounded reasoning over distilled summaries

The deterministic framework will never formalize every target type (75% blind). An agent
covers the long tail — but grounded, not free.

**Grounding contract:**
- The agent reasons over the **distilled card outputs** that already exist in the
  evidence-package (`cards[].summary` / `interpretation_call` / `caveats`) + the
  deterministic sub-verdicts + literature — NOT raw source data. (LLMs are unreliable at
  statistics over large tables; the methods layer computes; the agent reasons.)
- **Cite-or-abstain:** every agent claim references a computed card value or a specific
  citation. No support ⇒ `insufficient`, never a fabricated number.
- The **deterministic sub-verdicts remain the invariant audit spine**; agent judgments are
  tagged (`_source: llm_synthesized`, model id, prompt/input hash) and versioned.
- The agent supplies exactly the two things rules can't: **relevance** reasoning
  (objective-conditioning) and **blind-axis** judgment (surface / SL / cell-state), by
  reading cards + literature.

**Guardrails (non-negotiable):**
1. Reproducibility envelope — pinned model, temp 0, hash of the full evidence input;
   deterministic spine byte-stable.
2. Adversarial verification — a second pass that tries to REFUTE each dimension call before
   it is trusted.
3. Evaluation on known targets — the agent is tested, not believed (see §7 pilot).

### 5.1 The agent-layer contract (scenario-derived)

Eight worked scenarios (FOLR1, STEAP1, ADAR1, KRAS, PARP1, XPO1, CLDN18.2×LRRC15,
HIF2A) yield seven load-bearing rules:

1. **Deploy by coverage state** — agents run on blind / un-formalized axes only, never
   the validated lane (KRAS gets no judgment agent).
2. **Un-formalized ≠ unmeasured** — agents fix un-formalized axes (surface judgment, SL
   context); a missing *measurement* (co-localization, density) must be wired first, or
   the agent confabulates a relation (CLDN18.2×LRRC15 avidity failure).
3. **Typed disagreement arbitration** — an agent may soften a deterministic veto toward
   *conditional, with cited stratified evidence* (PARP1 → dependent-in-HRD+), but may NOT
   override a measured negative on literature alone.
4. **Adversarial refuter** on every agent-derived call (confabulation guard) AND on every
   confident positive (dangerous-FP red-team: STEAP1 over-veto, ADAR1 over-advance).
5. **Outcome-blinded, reasoning-scored evals** — testing on known approved targets measures
   *recall of the answer* unless the outcome is blinded and the reasoning chain + citations
   are scored (XPO1 leakage); include declined negative controls.
6. **License-blocked axes are out-of-agent-scope** pending legal (HIF2A/Cortellis) — no
   accidental license-laundering path.
7. **Capped certainty** on agent-derived cells unless they cite hard card values.

### 5.2 Risk lens — revived v1 6-dimension assessment

See `RISK_ASSESSMENT_INTEGRATION.md` (decided 2026-07-17). The deprecated
`workflow-target-evaluation-onc` produced a literature-sourced 6-dimension risk assessment
(Biological, Druggability, Translational, Clinical, Safety, Commercial). That record placed
it in the **synthesis-context layer, never the deterministic gate**, behind five
preconditions. The agent layer is the structured home that decision pointed to — reviving it
as a **risk lens** honors the decision AND resolves its blockers (temp-1.0 → reproducibility
envelope; unpinned corpus → PMID + mindate/maxdate pin; null-as-MEDIUM → already fixed
`not_assessed`; data-vs-judgment conflation → separate lens, capped certainty).

**Two lenses in the panel.** Conviction/certainty answers "how strong is the case"; the risk
lens answers "what could kill it." They are NEVER netted into one number. The 6 risk
dimensions ARE the **risk-read of the 5R categories** (§3): Biological, Druggability, Safety,
Translational, Clinical, Commercial. So conviction and risk are two reads *within the same
5R taxonomy* (`RISK_CATEGORY_DASHBOARD_SPINE.md`), not two separate dimension lists.

**Overlap dictates wiring:**

| Dimension | vs deterministic axes | Integration |
|---|---|---|
| Biological | overlaps dependency + genomic | ANCHOR to sub-verdict; agent adds literature color / flags contradiction |
| Druggability | overlaps tractability + modality-fit | ANCHOR |
| Safety | overlaps safety axis (gnomAD/human-genetics) | ANCHOR — also fixes the stale `safety→insufficient_evidence` hardcode (record §6b) |
| Translational | partial (target-model-availability card now exists) | Hybrid: deterministic model-coverage + agent PD/TE biomarkers |
| Clinical | orthogonal (no primary-data source) | Pure agent, context-tier |
| Commercial | orthogonal (Cortellis/IQVIA unlicensed) | Pure agent, context-tier, permanently out of gate |

Rule: **overlapping dimensions are grounded by the deterministic axis (consume, don't
re-derive); orthogonal ones are pure agent context.** The risk agent reads the
evidence-package sub-verdicts as priors — cite-or-abstain applied to computed evidence, not
just literature.

**The one verdict-affecting ramp.** Per the record §5, the only defensible gate-affecting
candidate is a `clinical_validation` **NO-GO** (a well-powered mechanistic de-validation in
the exact indication = a legitimate cross-target veto). This is also the *missing negative*
that catches the dangerous-false-positives (ADAR1, RBM39 — invisible IO/context clinical
decline). Ramp: **context lens now → clinical-de-validation hold/veto later**, behind the
five preconditions (#3 null≠MEDIUM done; #1 corpus-pin, #2 capture-sampled-output-as-pinned-
artifact, #5 staleness-TTL are tractable; #4 commercial/translational stay out).

---

## 6. Where each piece lives

- **(strength, certainty)** per axis → emitted by each sub-skill / resolver (deterministic).
- **Relevance** (objective × modality × indication → axis weights + scope) → explicit spec,
  extending `takeda-onc.portfolio_spec.yaml`.
- **Panel assembly** → `target-profile` (or a dedicated sub-skill), objective-conditioned.
- **Agent reasoning** → an upgrade of the Tier-3 synthesis: per-dimension + cite-or-abstain,
  over card summaries.
- **Risk lens** (§5.2) → a dedicated literature-risk subskill agent, context-tier, anchoring
  its overlapping dimensions to the deterministic sub-verdicts.

---

## 7. Validation

- **Reframe the discrimination harness question** from "does the final gate predict
  clinical outcome" (label-bound, weak) to "does higher **conviction + certainty**
  *concentrate* the known approved drugs" — a weaker, honest claim the data supports.
- **Agent pilot at its strongest point:** run the agent on the `honest_blind` **approved
  biologics antigens** (FOLR1, DLL3, TROP2, CD19) — where the deterministic framework
  abstains (0/10 nominable) — with the surface cards + literature, cite-or-abstain, scored
  against known-approved ground truth. Recovery of a defensible surface-antigen call =
  proof the agent layer earns its place. Confabulation = boundary learned cheaply on 4
  targets.

---

## 8. The cross-dimensional reasoning agent (spec)

The only component that sees ALL dimensions. Its job is the **interactions**, not
re-judging individual reads (those are deterministic or subskill-agent output).

### 8.1 Inputs
- The assembled per-dimension **panel**: for each dimension `{verdict, strength(signed),
  certainty, relevance(for-objective), provenance ∈ [deterministic | subskill_agent |
  risk_agent], citations}`.
- **Objective context**: `{modality, indication, therapeutic_hypothesis}`.
- **Deterministic hard-gate results** (safety-KILL, feasibility) — as BOUNDS, not advice.
- **Relevance spec** (objective × dimension weights + in/out-of-scope) from `portfolio_spec`.

### 8.2 The typed inter-dimension relation set (the auditable core)
Reasoning is expressed as cited edges of exactly four types, not free narrative:
- `conditions(A→B)` — A's state changes B's interpretation (genomic mutant-selective
  → safety WT-constraint moot).
- `tensions_with(A,B)` — pull opposite decision directions (biology vs commercial crowding).
- `corroborates(A,B)` — concordant AND independent (corroboration from a shared source does
  NOT count — non-independence guard).
- `contradicts(A,B)` — incompatible claims about the same thing → requires arbitration.
Each edge: `{type, from, to, rationale, citations, certainty_cap}`.

### 8.3 Authority & bounds (a *bounded* scoped-decider)
- Emits `overall_read ∈ {advanceable, advanceable_with_caveat, conditional_on_biomarker,
  advanceable_flagged:<out-of-gate-risk>, needs_data:<what>, declined:<why>}` **per
  objective** — derived from dimensions + edges.
- **`advanceable_flagged`** (from the ADAR1 stress test): advanceable by the gates, BUT an
  unresolved HIGH risk sits in a dimension the agent has no authority to gate on (an
  out-of-gate risk dimension, or a real deterministic positive the risk lens cannot
  override on low-certainty literature). The suspect is **visibly quarantined and routed to
  human adjudication** — never silently advanced — with `value_of_information` naming the
  deciding missing evidence. This is the honest terminal state when the system provably
  cannot decide (e.g. ADAR1: real ISG-high dependency, IO-context clinical decline that no
  risk-gate path can auto-veto).
- **Hard-gate bound:** never more permissive than the deterministic gates allow.
- **Typed disagreement arbitration** (§5.1.3): may soften a deterministic veto →
  `conditional` *with cited stratified evidence*; may NOT override a measured negative on
  literature alone; the **risk lens may only DOWNGRADE a positive via the
  `clinical_validation` NO-GO path** (behind the 5 preconditions) — otherwise risk
  contradictions are surfaced as caveats/tensions, never silent overrides.
- **Overall certainty = weakest-link** over relevant dimensions, computed deterministically
  (not narrated by the agent).

### 8.4 Output schema
`{overall_read, dimension_panel (pass-through), edges[], principal_tensions[] (ranked),
overall_certainty + limiting_dimension, value_of_information (the single missing evidence
that would most change the read), provenance {model_pin, input_hash, per-edge citations,
_source: llm_synthesized}}`.

### 8.5 Guardrails
Expose-don't-bury (refuter checks for a buried `contradicts`); structured intake (must
address every in-scope dimension); certainty computed not narrated; relevance from spec
(deviations justified + cited); adversarial refuter verifies **each edge** and the overall
read; reproducibility envelope.

### 8.6 Relationship to existing code
The principled upgrade of `target-profile`'s `tension_analysis` + `_deciding_axis` +
`_gate_scorecard`: same intent, but structured (typed edges), grounded (cite-or-abstain),
bounded (hard gates), and coverage-honest (weakest-link certainty).

---

## 9. Open questions for the team

1. ~~**Dimension taxonomy** — is "biomarker / patient-selection" a first-class dimension?~~
   **DECIDED** (`RISK_CATEGORY_DASHBOARD_SPINE.md`, 2026-07-21): the taxonomy is the 7 5R risk
   categories; Biomarker is its own top-level category (Right Patient), Differentiation folds
   under Commercial. See §3.
2. **How much does the agent DECIDE vs PRESENT?** Does it emit per-dimension verdicts, or
   only distil + surface tensions while dimensions stay rule-derived?
3. **Label re-grade** — the 7 `advanced`/`active` silent-FNs need expert grading
   (efficacy-differentiated vs program-status) before any conviction↔outcome validation.
4. **Roll-up exposure** — do we surface the optional evidence-strength scalar at all, given
   the risk it gets read as P(success)?
5. **Risk-lens verdict ramp** — do we invest in the five §5 preconditions of
   RISK_ASSESSMENT_INTEGRATION.md to let a `clinical_validation` NO-GO become a gate-affecting
   veto (the dangerous-FP guard), or keep the whole risk lens context-only?
6. **Cross-dimensional reasoning agent** — its scope and arbitration authority (see the
   companion discussion): does it only surface tensions, or also emit a scoped overall read?
