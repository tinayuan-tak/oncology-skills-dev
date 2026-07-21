# Gate model v2 — decision memo

**Status:** proposal for review (2026-07-21). No code. Written after a full card-by-card audit
of the A–H model + review of the predesigned module dashboard.

## The problem (one sentence)

The A–H gate letters conflate **two different axes** — *what is biologically true about the
target* (modality-independent) and *whether it's actionable given a modality* (strategy-dependent)
— and have no clean home for **biomarker/relational** evidence (feature × outcome). This forces
slashes (`Present (alteration) / Required (biomarker-stratified)`), parenthetical letter-overloads
(C carries 4 sub-skills; E carries 2), and leaves ~11 modality-conditional cards homeless.

Audit evidence: `gate_coverage.yaml` has 11 sub-skills on 8 letters; 1 gate_name spans two letters;
7 `derived_from` (relational) measurement_types the letters must re-fan across gates; 4 cross-gate
cards (`prism-crispr-concordance` self-declares "feeds BOTH C and E"); 4 first-class cross-gate
edges already hand-wired in `nomination_verdict_gate.yaml`.

## The model (proposed) — 2 axes + biomarkers as facets (NOT a new graph tier)

**Axis 1 — Biology gates (necessity; modality-independent).** Is this real biology?
`Present · Selective · Required · Mechanism · Altered`. Clean single homes. (A–D today, + "Altered"
split cleanly out of the A/genomic overload.)

**Axis 2 — Modality-fit assessments (sufficiency; per-lens).** Will it become a drug *in THIS
modality*? `Small-molecule · Surface-biologics (ADC/TCE) · Degrader · Safety · Differentiation`.
These are *fit scores conditional on a modality lens*, not gates you pass. This resolves the E-overload,
the 11 modality-conditional cards, and `surface_modality` (today a 2nd sub-skill jammed onto letter E).

**Biomarkers — surfaced as FACETS of the gate they relate, split by sub-type (no new tier):**
- **Corroboration** (CRISPR×RNAi, compound×dependency): agreement between two measures of the same
  thing → a **confidence annotation** on the outcome gate. Reuses the confidence mechanism already
  built for dependency-predictability (Gate-C Gap 1). No new machinery.
- **Stratification** (mutation×dependency, expression×dependency): a feature partitions the outcome
  → the **patient-selection** hypothesis (who responds). Surfaced as a labeled facet under the
  outcome gate (Required), carrying its own verdict (`biomarker_stratified_dependency`) + the
  veto-suppressor cross-feed already wired in `nomination_verdict_gate.yaml`.

Rejected: a full "biomarker = edge in a graph" tier. It's the most elegant model but over-engineered
for ~4 cards; the facet approach gives the same visibility + flexibility without a graph formalism.
Also rejected: a single catch-all "Biomarker gate" — it would merge corroboration (confidence) with
stratification (who-responds), which are genuinely different jobs.

## Mechanism (contract-layer, verdict-neutral)

Replace the slashed/parenthetical gate_names with an explicit schema in `gate_coverage.yaml`:
each sub-skill declares `axis: biology|modality_fit`, its home `gate`, and `reports_into: [...]`
(the gates its verdict modulates) + optional `role: corroboration|stratification`. The 4 cross-gate
edges already in `nomination_verdict_gate.yaml` become the general `reports_into` mechanism; the
ad-hoc slashes retire. Modality-fit sub-skills carry `modality_relevance` (5 cards already do) so the
active lens selects which fit-assessments are relevant.

## Dashboard implication (user chose: HYBRID)

Gate scorecard stays the **top-level lens/nav** (the A–H-ish roll-up); each gate section's *content*
is **module-organized** underneath (distribution + lineage + subtype + biomarker panels together —
as the predesigned dashboard already does with its dependency module). Biomarker facets render inside
their outcome gate's section. This is the presence-section work we've built, generalized.

## The 3–4 hardest decisions (need your call)

1. **"Altered" as a 5th biology gate?** Splitting genomic-alteration cleanly out of the A/C overload
   needs a home. Options: a new necessity gate "Altered", or fold alteration-frequency into Present +
   route the biomarker-stratified half to Required. (Lean: new "Altered" gate — it's a distinct
   biology question and kills the one slash.)
2. **Do biology gates keep letters (A–E) or move to names?** Letters are terse but the two-axis split
   makes "E = both SM and surface" incoherent. (Lean: keep letters for the 5 biology gates; name the
   modality-fit assessments, since they're lens-conditional, not sequential.)
3. **Is this verdict-neutral in v2?** I propose YES — taxonomy + presentation only; the resolver/
   nomination-gate logic is untouched this pass (the cross-feeds already exist). A later pass could
   make the modality lens actually select fit-assessments at runtime.
4. **Migration cost.** ~42 cards don't self-declare gates (binding is in skills' SKILL.md `phase`),
   and skill `phase` letters already diverge from `gate_coverage` letters. Re-aligning is real work;
   scope it as its own slice after the model is agreed.

## What this does NOT change
- No renumbering of the clean biology gates' identities beyond adding "Altered".
- No resolver/verdict logic (verdict-neutral).
- No new science — every relationship already exists as a `derived_from` type or a wired cross-feed.
