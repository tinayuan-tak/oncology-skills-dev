---
name: cis-feature-coherence
description: |
  Focused question skill: "Does target X's OWN locus feature causally explain its OWN
  expression AND its OWN dependency — is this a coherent cis-driven addiction, or three
  axes that merely co-occur?" The coherence OWNER for the locus → expression → dependency
  chain. Distinguishes amplification-driven oncogene addiction (ERBB2/MYC/KRAS-amp:
  copy-number drives expression drives dependency) from a co-occurring passenger amplicon,
  from an expressed-but-inert target (the abundance-laundering guard), and from a
  trans-driven (copy-number-independent) dependency.

  Integrates ONE genuinely-new leg with TWO reused leg-cards (no new dependency
  measurement, no new *-stratified-dependency card):
    - leg-1 (NEW)  cis-feature-expression-coherence — does the target's own relative CN
                   predict its own expression across DepMap? (cis-dosage coupling)
    - leg-2 (reuse) expression-dependency-correlation — does expression track dependency?
    - leg-2 (reuse) amp-expr-stratified-dependency   — is the amplified∩overexpressed
                   subset more dependent? (the conjoint dependency lens)

  Emits a data-package with a self-contained cis_coherence_verdict resolved from the
  shared declarative cis_coherence resolver (a deterministic 2×2 cross-tab).

  Use for questions like "is ERBB2 an amplification-driven cis-driver in this indication?",
  "is MYC over-expression copy-number-driven or trans-regulated?", "is this target's
  dependency explained by its own lesion, or is it a passenger?"

  VERDICT-INERT at the composed target-profile layer: cis_coherence is a DEDICATED,
  self-contained axis (like combinatorial_dependency / resistance_emergence) — kept OUT
  of the shared nomination ladder, never a nomination gate. It feeds confidence +
  tension_analysis framing. Graduation to a gate (coherent → supportive; incoherent →
  contradiction) is a later, CALIBRATED stage.

metadata:
  version: 1.0.0
  owner: ryan.abo@takeda.com
  requires_preflight: false

composition:
  data_mode: derived_read
  phase: [A, C]                        # cross-axis coherence: leg-1 = expression (A), leg-2 = dependency (C)
  cards_used:
    - cis-feature-expression-coherence     # GoF leg-1: CN → own-expression cis-dosage (amplification)
    - cellline-methylation-expression-coherence  # LoF leg-1: promoter methylation → own LOW expression (silencing)
    - expression-dependency-correlation     # leg-2 (reuse): expression → dependency
    - amp-expr-stratified-dependency         # leg-2 (reuse): conjoint amp∩overexpr dependency
    - patient-cis-coherence                  # VERDICT-INERT patient (TCGA) corroboration facet (fires no rule)
  # DATA_TO_SKILL_CONTRACT Rule 3 — the measurement_type claims this skill PULLs.
  measurement_types_pulled:
    - cis_dosage_coupling
    - methylation_silencing_coupling
    - expression_dependency_correlation
    - amp_expr_stratified_dependency
    - patient_cis_coherence
  rules_scope:
    - cis-coherence
  # Verdict via the SHARED declarative resolver (resolvers/cis_coherence.resolver.yaml) on a
  # DEDICATED rules axis `cis_coherence` so its rules never cross-load with the shared
  # intracellular-intrinsic ladder. NOT wired into nomination_verdict_gate — cis_coherence is
  # verdict-INERT at composition (the existing nomination/dependency resolver golden snapshots stay
  # byte-stable). Composition into target-profile (as a verdict-inert facet + _synthesis_facet lift)
  # is a deliberate follow-on stage.
  synthesis:
    - rule_engine
  output_shape:
    - data_package
  steps_covered: [1, 2, 3, 4, 6]
  optional_lenses:
    - modality
  status: wired
---

# cis-feature-coherence — Locus → Expression → Dependency Coherence

## What this skill does

Given a target (+ optional indication):
  1. Loads THREE cards over DepMap 26Q1 (zero new ingest — CN + expression + Chronos co-resident):
     - `cis-feature-expression-coherence` (leg-1, NEW): `cis_dosage_class` — does the target's own
       relative copy-number predict its own log2TPM? (`cn_dosage_coupled_strong|moderate` /
       `cn_dosage_uncoupled` / `cn_invariant_panel` / `data_unavailable`). Method `depmap_cis_dosage`.
     - `expression-dependency-correlation` (leg-2, reuse): `correlation_class`.
     - `amp-expr-stratified-dependency` (leg-2, reuse): `amp_expr_stratification_class`.
  2. Fires the `cis-coherence` rule subset (axis `cis_coherence`) and resolves a self-contained
     `cis_coherence_verdict` via the shared `cis_coherence` resolver — a deterministic 2×2 cross-tab
     of leg-1 (cis-dosage coupling) × leg-2 (dependency coupling):

     |                 | leg-2 dependency-coupled       | leg-2 dependency-absent            |
     |-----------------|--------------------------------|------------------------------------|
     | leg-1 coupled   | `coherent_cis_driver`          | `expressed_cis_coupled_inert`      |
     | leg-1 uncoupled | `dependency_without_cis_dosage`| `cis_uncoupled_no_dependency`      |

     Any leg untestable/unmeasured → `insufficient_cis_coherence` (honest abstention).

## Verdict semantics

- `coherent_cis_driver` — the amplification-driven oncogene-addiction chain is intact (CN drives
  expression drives dependency). The strongest cis-nomination support.
- `expressed_cis_coupled_inert` — present and cis-driven, but NOT more required where more abundant.
  The **abundance-laundering guard**: a bare abundance steer would mis-read this as "expected
  non-dependency"; naming it is the point.
- `dependency_without_cis_dosage` — a real dependency whose expression is copy-number-INDEPENDENT
  (trans/lineage-regulated). Routes framing toward dependency_relational, not a CN-stratified strategy.
- `cis_uncoupled_no_dependency` — no coherent cis chain.
- `insufficient_cis_coherence` — a leg is untestable (e.g. near-diploid panel) or unmeasured.

## Boundaries

cis-dosage coupling is CORRELATIONAL, not a formal mediation test — a co-amplified neighbour or a
shared trans-regulator can mimic it (leg-1 caveat). Cell-line coherence is necessary but not
sufficient for a patient cis-driver claim; the patient epigenetic-silencing arm (promoter
methylation → expression) and the patient CN↔expression join are deferred (they need the
`tcga-sample-id-crosswalk-v1` substrate). This skill is VERDICT-INERT — it never blocks a nomination.

## How Claude invokes this skill

`/cis-feature-coherence --target ERBB2 [--indication BRCA]`. Reads the emitted `decision.json`;
`cis_coherence_verdict` + `driving_rule_id` are the audit spine; the headline carries each leg's class
+ the cis-dosage metrics (`cn_expr_spearman_r`, `delta_log2tpm_amplified_vs_neutral`).
