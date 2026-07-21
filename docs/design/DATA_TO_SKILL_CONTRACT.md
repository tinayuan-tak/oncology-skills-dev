# Data-to-Skill Contract — Measurement Atoms, Pull-Routed to Gates

**Status:** Decided (principle) 2026-07-21; pressure-tested against 15 real/adversarial
cards the same day (see appendix). Makes the two-layer model of
`CARD_ARCHITECTURE_DECISION.md` *executable*: it fixes the card's **identity** to a
`(measurement_type × entity_grain)` tuple, gives a one-question rubric for the
new-card-vs-extend decision, and inverts the data→skill flow from push to pull so that
adding a dataset is a **local, one-sided act** that never touches a skill. The
pressure-test upgraded the model from a flat data→card→gate pipeline to a **DAG of
per-target-entity measurement-types with governed type/grain vocabularies, per-type
conflict policies, and static-capability-vs-runtime-selection on grain** — every
refinement forced by a real card, most naming machinery the framework already has.
Companion to `CARD_ARCHITECTURE_DECISION.md` (the two-layer principle),
`MODALITY_TAXONOMY.md` (the measured-vs-inferred / concordance discipline),
`FRAMEWORK_OVERVIEW.md` (the four layers), and the resolver work (gap #5 — the same
declarative-pull philosophy applied to verdicts).

Portable GFM (no Mermaid/HTML) per README format rules.

---

## What prompted this

Every time a new dataset + method is ingested, deciding *how it flows into the skills*
requires a chain of coupled decisions — which card, which rule, which verdict, which
gate, which skill — and several have no obvious answer. The recurring symptoms:

- **The new-card-vs-extend call has no stable answer.** Because a card is allowed to be
  a dataset AND a measurement AND a question-answer simultaneously, "is this a new card
  or an extension?" is really three questions at once.
- **Orphaned-but-useful data.** CSPA (Bausch-Fluck 2015 cell-surface proteome MS) was
  ingested and landed on S3, then wired to **no card** — because the model has no way to
  *register a measurement without also deciding its consumer*. When the consumer is
  ambiguous (CSPA plausibly serves presence, safety, and modality-fit), the wiring
  stalls and the data sits dead.
- **One dataset, many questions.** A single measurement legitimately serves several
  gates, but the push model forces picking one home or duplicating the card.

**Diagnosis.** The framework is organized *question-first* (skills/gates/verdicts are the
top-level units) but data arrives *dataset-first*. The current model resolves the
mismatch with a **push**: "I have data → where do I put it?" — a manual fan-out into the
skill graph, decided at ingestion time, in the hardest direction. The fix is to **pull**:
gates declare the measurement types they need; data registers what it provides; a
resolver matches them. Flow becomes a *consequence of matching*, not a hand-wiring
decision. This is the same inversion the verdict-resolver already made one layer up.

---

## The decision (five rules)

Rules 1–3 are the core; Rules 4–5 are the refinements the pressure-test forced (a flat
data→card→gate model could not represent ~5 of the framework's richest cards without
them). All five are traceable to a real card (appendix).

### Rule 1 — A card's identity is `(measurement_type × entity_grain)`. Nothing else.

A card is a **measurement atom**: it owns exactly one `measurement_type`, emitted at one
or more declared `entity_grain`s. It is **NOT** a dataset, and **NOT** a question.

- `measurement_type` = a *claim about the target* you would triangulate within (multiple
  sources corroborating) and contrast across (different claims as distinct axes). E.g.
  `crispr_lof_dependency`, `surface_confirmation`, `normal_tissue_breadth`,
  `tumor_vs_adjacent_rna_differential`.
- `entity_grain` = a value from a **governed grain vocabulary** — today `target |
  target_indication | target_subtype`, extensible to `target_lineage`, `cohort`,
  `single_cell` by the same one-sided registration (Rule 5). Do NOT hardcode the grain
  set; a new slicing dimension must be a vocabulary entry, never a schema change. Some
  grains carry a **partition dependency** (Rule 4) — `target_subtype`/`target_lineage`
  need a definition of which strata exist and which samples belong to each.

**Two identity discriminators (not one).** A claim is a *distinct* `measurement_type` if
EITHER:
  (a) it fails the concordance test — it is not interchangeable evidence for an existing
      claim (Rule 2); OR
  (b) it answers a *different gate question*, even from the same substrate (framing).
Discriminator (b) is why `tumor_vs_normal_differential` (pulled by Selectivity — efficacy
window) and `normal_tissue_breadth` (pulled by Safety — off-tumor floor) are two types
despite sharing tumor-vs-normal biology. Identity is therefore **bottom-up from data AND
partly top-down from the question** — not purely a property of the substrate.

`CARD_ARCHITECTURE_DECISION.md` already declared "cards are measurement atoms (Layer 1)
vs question-gates (Layer 2)." That was stated as a *classification* ("cards are one of
two kinds"), which is why it didn't fully bind. Here it is an **identity rule**: a card
*is* a Layer-1 measurement atom, full stop. Layer-2 gates are separate objects (thin
views), never cards. Once identity is `(type × grain)`, the granularity question becomes
deterministic (Rule 2) and gates never touch data (Rule 3).

### Rule 2 — The concordance test decides new-card-vs-extend.

When a new dataset + method arrives, ask exactly one question:

> **"Would I want to show this data as *agreeing/disagreeing* with a claim an existing
> card already makes (interchangeable evidence, computed as concordance, never averaged
> away) — or as a *separate line of evidence* shown alongside it?"**

```
New dataset + method
      |
      v
Does it corroborate an EXISTING measurement_type?
(interchangeable evidence for the SAME claim)
      |
      +-- YES ------------------> EXTEND that card: register a new PROVIDER (source+method).
      |                            No new card. No skill/gate/rule touched.
      |                            e.g. a 2nd surfaceome-MS dataset joins CSPA under
      |                            `surface_confirmation`.
      |
      +-- SAME type, NEW grain --> EXTEND that card: add the entity_grain it emits.
      |                            e.g. target-grain dependency now also emits
      |                            target_subtype-grain.
      |
      +-- NO (a NEW claim; you'd  -> NEW card. Register its measurement_type in the
          show it ALONGSIDE, not     vocabulary (per the governance rules below).
          instead of, existing)      e.g. CSPA `surface_confirmation` != topology
                                     `has_transmembrane` != `surface_density` -> 3 cards.
```

The concordance test is the whole discriminator, and it is the same principle
`MODALITY_TAXONOMY.md` already holds ("surface concordance/disagreement, never average
it away"): same-type data **triangulates** (extend); different-type data is a **distinct
axis** (new card). Two cards being "about the surface" does not make them one card —
CSPA (measured surface residency) and topology (predicted TM domain) are *complementary*,
not interchangeable, so they are separate atoms.

### Rule 3 — Gates PULL measurement_types; data PUSHES providers. The two decisions are decoupled.

- A **provider** (dataset + method) registers `(measurement_type, entity_grain,
  evidence_tier, value_vocabulary)`. This is a *local* decision about the data — "what
  does it measure?" — never a global one about skills.
- A **gate** (Layer-2 question-view) declares the `measurement_type`s it pulls. This is a
  *local* decision about the question — "what would answer it?" — never about specific
  datasets.
- A **resolver** matches providers to gate needs. Adding a dataset never opens a skill;
  adding a question never opens a dataset.

An unclaimed-but-registered measurement is a **first-class, visible state** (discoverable
capability), not a dead end. The CSPA-orphan situation becomes structurally impossible:
CSPA would register as a `surface_confirmation` provider and be visible to any gate that
pulls that type, whether or not one does today. The mirror state — a registered type that
no gate pulls yet (e.g. `dependency_predictability` today) — is equally legitimate and
queryable, not a silent dead-end.

### Rule 4 — The registry is a DAG. Edges are `data→type` (push) and `type→type` (derived).

A measurement_type has providers of two kinds:

- **`dataset` providers** — a source+method that measures the claim directly (CSPA →
  `surface_confirmation`).
- **`derived_from` providers** — the claim is *computed by comparing other
  measurement_types*, and the comparison itself is the scientific object. The edge is
  always **type→type**, regardless of whether the inputs come from one dataset or several.

Derived types are how the framework's richest cards are represented: `crispr_rnai_
concordance` is `derived_from: [crispr_lof_dependency, rnai_lof_dependency]`;
`mutation_stratified_dependency` is `derived_from: [mutation_status, crispr_dependency]`
(both co-resident in DepMap, but still a type→type edge, not a single-atom read);
`adc_tce_modality_fit` is `derived_from: [topology, surfaceome_family, structure]`. This
generalizes `CARD_ARCHITECTURE_DECISION.md`'s "Layer 1b derived-comparison cards": a
derived card is still a measurement atom, but its providers are types, not datasets.

**A grain a card *can* emit ≠ a grain that *fires*.** Providing a grain is necessary but
not sufficient: admissibility (the n>=30 floor, evidence-tier) is enforced **downstream,
per-instance, at the rule layer** — exactly as the `subgroup_n_floor_met: true`
`in_record` predicate already does for underpowered strata. "CSPA provides
`surface_confirmation` at target grain" does NOT mean it always fires; an inadmissible
instance simply fails the match.

**Subtype/lineage grain carries a PARTITION dependency the coarser grains do not.**
`target` and `target_indication` grains need only their substrate provider. But a
`target_subtype` (or `target_lineage`) emission needs a *second* input: the **partition**
— which strata exist and which samples belong to each. In this framework that partition
is a first-class artifact pair: the **subgroup-catalog** (stratum *definitions*, e.g.
COADREAD → MSI/MSS, CMS1-4) and the **subgroup-assignment product** (sample→stratum
membership, e.g. `depmap-subgroup-assignments-coadread-v1`, `tcga-maf-...`,
`genie-bpc-...`). So a subtype-grain emission is a DAG node with edges
`derived_from: [the_claim_substrate, subgroup_assignment]` — modeled exactly like any
other type→type/derived edge, with the assignment product as a required input and its pin
part of the composite cache key. The rule layer already declares this linkage via
`subgroup_metadata_declared` (`subtype_defining_data`, `subgroup_n_source`,
`min_n_required`). **Consequence to enforce:** a subtype-grain card must be wired to BOTH
its substrate AND the assignment product — wiring only the substrate produces the
sample-id-join-mismatch silent failure (a stratum looks empty because membership was
never joined, not because the biology is absent). The n-floor admissibility above is the
downstream guard; the partition dependency is the upstream one.

### Rule 5 — Grain is capability (static, on the card) vs selection (runtime, from the query).

`entity_grains` on a card declares the **ceiling** — the grains its substrate can
support (a per-sample reader can emit `target_subtype`; an aggregate reader cannot). The
**query** selects a grain *within* that ceiling. A query requesting a grain above the
ceiling gets an honest `data_unavailable` *for that grain* — it must **NEVER** silently
fall back to a coarser grain (mislabeling whole-cohort data as per-subtype is a known
silent-failure mode). This is the same insight as the evidence-tensor cell: all
supportable strata are computable; scope-narrowing is *display-foreground selection*, not
a compute mode.

**Multi-provider conflict is resolved explicitly, never silently.** When two providers of
one type disagree (CSPA `confirmed` vs SURFY `not_surface`), the type declares a
`multi_provider_policy`:
  - `tier_dominant` — higher `evidence_tier` wins (`measured` CSPA beats `inferred`
    SURFY). The simple default.
  - `surface_discordance` — emit the disagreement as a sub-signal
    (`provider_agreement: concordant | discordant`) and let the rule decide — the exact
    pattern `crispr_rnai_concordance` already uses one layer up.
Averaging or arbitrary pick-one is **forbidden** (the anti-pattern the whole framework
rejects). A type with multiple providers MUST declare a policy.

**Provider identity includes the release pin.** A provider is `(source, method,
release_pin)`. A dataset re-release (DepMap 26q1 → 26q2) is the *same* provider at a new
pin → new immutable instances (old retained per retention policy), never a new type or a
new provider. This composes with the content-pin spine gap.

---

## The missing middle: a governed `measurement_type` vocabulary

One new artifact, versioned in `target-contracts/vocabularies/` alongside the others
(sibling of `nomination_verdict_gate.yaml`). Each entry declares the claim, its grains,
its value vocabulary, the modalities it is *relevant to* (routing metadata only), and its
providers with a mandatory evidence tier.

```yaml
# vocabularies/measurement_types.yaml  (illustrative entries)

# --- a dataset-provided type with two disagreeing providers ---
surface_confirmation:
  claim: "Is the target protein detected on the extracellular cell surface?"
  entity_grains: [target]            # capability ceiling; extend iff a tumor-surface assay lands
  value_vocabulary: [confirmed_high, confirmed, predicted_only, not_surface, data_unavailable]
  modality_relevance: [adc, bite_tce, antibody]   # ROUTING metadata; NOT modality-specific values
  multi_provider_policy: tier_dominant            # measured CSPA beats inferred SURFY (Rule 5)
  providers:
    - {kind: dataset, source: cspa-bausch-fluck-2015, method: cspa_surface_confirmation, evidence_tier: measured}
    - {kind: dataset, source: surfaceome-family,      method: surfy_prediction,          evidence_tier: inferred}

# --- a DERIVED type: the comparison IS the claim (Rule 4, type->type edge) ---
crispr_rnai_concordance:
  claim: "Do orthogonal LOF assays agree that the target is required?"
  entity_grains: [target]
  value_vocabulary: [strongly_concordant_dependent, concordant, discordant, strongly_concordant_non_dependent, data_unavailable]
  providers:
    - {kind: derived_from, inputs: [crispr_lof_dependency, rnai_lof_dependency], method: concordance}
```

Two governance rules keep the vocabulary honest and prevent sprawl:

1. **The concordance test defines type identity.** Two providers share a
   `measurement_type` iff they are corroborating evidence for the same claim. That test
   is also the answer to "is this really a new type, or the same one?"
2. **`evidence_tier` is mandatory per provider** — `measured | inferred | estimated`.
   This lets one card hold CSPA (`measured` surface residency) *and* SURFY
   (`inferred`/predicted) without pretending they are equal. It is the machine-checkable
   home for the presence-vs-inference distinction, and it must travel to the verdict
   layer (an `inferred`-only atom must never fire a `measured`-strength killer — the
   measured-vs-null discipline, applied to provenance).

---

## Why this is fit-for-purpose across our modalities

Measurement atoms stay **modality-agnostic**; `modality_relevance` is routing metadata;
the modality *lens* is applied by **rules** (the resolver signals), never baked into the
card. One substrate serves intracellular and surface modalities at once:

| Biological axis   | measurement_type (atom)          | SM / degrader reads as        | ADC / TCE reads as              |
|-------------------|----------------------------------|-------------------------------|---------------------------------|
| Presence          | `tumor_protein_abundance`        | protein present to act on     | necessary, not sufficient       |
| Surface presence  | `surface_confirmation`           | **not_applicable**            | **gating: is it reachable**     |
| Surface abundance | `surface_density`                | not_applicable                | ADC payload / TCE-viability     |
| Requirement       | `crispr_lof_dependency`          | efficacy basis (can veto)     | informative-only (antigen kill) |
| Safety            | `normal_tissue_breadth`          | full-KO tolerance             | on-target-off-tumor tox         |

The *same* `surface_confirmation` atom is `not_applicable` for a small molecule and
`gating` for a TCE — and that difference lives in the **rule** (the modality lens already
built), not in a duplicated card. Adding a future modality (e.g. radioligand) is writing
new *rules* over existing atoms — not re-ingesting or re-carding data. The substrate is
bought once; modalities are cheap views on top.

---

## The add-a-dataset workflow, after this change

The N-part decision collapses to a local, one-sided act:

1. **Ingest** the dataset (data-catalog — unchanged).
2. **Answer one question:** "what claim does this measure, at what grain, at what
   evidence tier?" -> register it as a **provider** of a `measurement_type` (existing per
   the concordance test, or new-per-the-rubric). Add a new `measurement_type` entry only
   if the concordance test says NEW.
3. **Stop.** No skill is opened. If a gate already pulls that type, it lights up. If not,
   the atom is registered, visible, and claimable later with zero rewiring.

Adding a new *question* is the symmetric one-sided act: a gate declares the
`measurement_type`s it pulls. Ingestion and consumption are finally **decoupled** — the
"complete fit" the push model was missing.

---

## How it flows — data → evidence → gates → profile

The five layers, with the measurement-type registry as the pivot. Everything below the
registry is **push** (data announces what it measures); everything above is **pull**
(gates request what they need); they meet at the registry and never wire directly.

```
 +-- PUSH side (data announces) ---------------------------------------------------+
 |  LAYER 0: DATASETS          LAYER 1: MEASUREMENT-TYPE REGISTRY (a DAG)           |
 |  (providers, + pin)         (per-target-entity CLAIMS; governed vocab)          |
 |  DepMap 26q1  --provides--> crispr_lof_dependency --+                           |
 |  DepMap RNAi  --provides--> rnai_lof_dependency ----+--derived--> crispr_rnai_  |
 |  CSPA MS      --provides--> surface_confirmation --+ |            concordance    |
 |  SURFY (pred) --provides--> surface_confirmation --+ (2 providers, conflict pol.)|
 |  HPA IHC      --provides--> normal_tissue_breadth                               |
 |  CPTAC prot   --provides--> tumor_protein_abundance                             |
 |  GDC somatic  --provides--> hotspot_frequency, snv_recurrence  (1 dataset->many)|
 +---------------------------------------+-----------------------------------------+
                                         |  RESOLVER MATCHES (type -> gate)
 +-- PULL side (questions request) ------+-----------------------------------------+
 |  LAYER 2: GATE VIEWS        LAYER 3: RESOLVER        LAYER 4: PROFILE            |
 |  (declare types needed)     (fired rules->verdict)   (compose + LLM)            |
 |  Presence  <-pulls- tumor_protein_abundance ------> presence_v.  --+            |
 |  Selective <-pulls- tumor_vs_normal_differential -> selectivity_v.  |           |
 |  Required  <-pulls- crispr/rnai/concord/paralog/ --> dependency_v.  +-> nomination
 |                     chem-genetic                                    |   gate +   |
 |  Mechanism <-pulls- signaling_network ------------> mechanism_v.    |   risk     |
 |  Genomic   <-pulls- hotspot/snv/cn/stratified-dep-> genomic_v.      |   matrix   |
 |  Surface   <-pulls- surface_confirmation/density/ -> surface_v.     |   + LLM    |
 |                     topology/normal_tissue                          |   synth    |
 |  Safety    <-pulls- normal_tissue_breadth/gnomad --> safety_v. -----+            |
 +---------------------------------------------------------------------------------+
```

The conceptual shift: **cards stop being the top-level unit — measurement-types do.** A
card *is* a measurement-type view over its providers; a gate attaches from above by
pulling type names, never dataset names. That is why adding data is one-sided.

### The five flow-patterns (different elements flow differently)

Not every profile element flows the same way. The contract makes these differences
explicit rather than special-casing them:

1. **Simple atom → one gate.** `CPTAC → tumor_protein_abundance → Presence`. One claim,
   one puller, direct — the vanilla path.
2. **One atom → many gates (decoupling win).** `DepMap PRISM →
   chemical_genetic_concordance` is pulled by BOTH Required (reads it as
   confirmed-dependent) and Tractability (reads it as compound-exists). Same atom, two
   gate-views, two rule-lenses, zero duplication — the pattern the push model could not
   express without forking the card.
3. **Many atoms → one derived claim → gate.** `crispr + rnai --derived-->
   crispr_rnai_concordance`, alongside `paralog_buffering` and
   `chemical_genetic_concordance`, all feed Required; the resolver's precedence ladder
   picks the verdict. Dependency is the richest element: 5 atoms + 1 derived comparison.
4. **Two providers disagree on one atom.** `CSPA (measured) + SURFY (inferred) →
   surface_confirmation`, resolved by the type's `multi_provider_policy` — tier-dominant
   or surface-the-discordance, never silently averaged.
5. **Same biology, two gates, opposite framing.** Tumor-vs-normal RNA splits into
   `tumor_vs_normal_differential` (Selectivity — efficacy window) and
   `normal_tissue_breadth` (Safety — off-tumor floor). Identity shaped top-down by the
   question (Rule 1 discriminator (b)).

### Modality is the orthogonal second axis — applied by rules, not cards

The SAME atoms feed intracellular and surface modalities; what differs is how the rule
reads each atom per modality channel:

```
  crispr_lof_dependency:  SM/degrader -> efficacy basis (can veto)  | ADC/TCE -> informative only
  surface_confirmation:   SM/degrader -> not_applicable             | ADC/TCE -> GATING
  normal_tissue_breadth:  SM/degrader -> full-KO tolerance          | ADC/TCE -> off-tumor tox floor
```

A modality lens does not change *which data flows* — it changes *how each gate's rule
interprets the same atoms*. A new modality later = new rules over existing atoms, not new
data.

### The target-profile is the assembled matrix

A profile query selects a slice of per-target-entity measurement-types at a chosen grain;
each gate pulls its slice and resolves a verdict; the verdict set, read through a modality
lens, IS the (gates × modality) matrix the LLM narrates and the nomination gate scores.
The matrix is not a separate thing to build — it is the natural projection of this
architecture. For KRAS-COADREAD all five flow-patterns run in parallel and converge:

```
 DATA         -> MEASUREMENT-TYPES (atoms + derived)  -> GATE VERDICTS          -> PROFILE
 DepMap/CPTAC    tumor_protein_abundance                 presence: moderate    +
 TCGA DGE        tumor_vs_normal_differential            selectivity: discordant|
 DepMap x5       crispr/rnai/concord/paralog/chem-gen    dependency: lineage_sel+-> nomination
 GDC/DepMap      hotspot + snv + cn + stratified-dep     genomic: biomarker_str |   gate
 SIGNOR          signaling_network                       mechanism: well_charac |   (dep=+,
 CSPA/SURFY/HPA  surface_confirmation + normal_breadth   surface: neither_viable|    safety=hold)
 gnomAD          gnomad_constraint                       safety: highly_constr -+       v
                                                                                  risk + gate x modality
                                                                                  matrix + LLM -> "hold, high"
```

---

## Worked example — CSPA through the new model (the case that surfaced this)

1. **Register providers.** CSPA registers as a `surface_confirmation` provider,
   `evidence_tier: measured`, grain `target`. SURFY/topology already provide the same
   type at `evidence_tier: inferred`.
2. **Concordance test.** Does CSPA corroborate an existing claim? It corroborates
   `surface_confirmation` (same claim as SURFY, higher evidence tier) -> **EXTEND** that
   card with a new provider. It does **NOT** collapse into topology (`has_transmembrane`)
   or `surface_density` — those are complementary claims (different axes), so they remain
   separate atoms. Net: **0 new cards for the residency claim; 1 provider added.**
3. **Gate pull.** The surface-presence gate (and the biologics-safety and modality-fit
   gates, if they pull `surface_confirmation`) light up automatically — no skill edit.
4. **Rule / modality lens.** `surface_confirmation == confirmed_high` fires
   `supportive` on adc/bite_tce/antibody channels and `not_applicable` on
   small_molecule/degrader. CSPA's `measured` tier lets it clear the admissibility floor
   that SURFY's `inferred` tier cannot — so a measured surface confirmation can carry a
   verdict a prediction alone could not.

This resolves the orphan: CSPA stops being "ingested but homeless" and becomes "a
measured provider of an existing claim" — a one-line registration.

---

## Honest cost / tradeoffs

- **You author + govern a `measurement_type` vocabulary.** The concordance test makes
  this tractable, but it is real curation (when are two datasets the "same claim"?).
- **Provider discipline.** Datasets must honestly declare `(type, grain, evidence_tier)`.
  A mis-declared tier is the new failure mode to validate against.
- **Straddle-card migration.** The ~8 cards that currently do both jobs must each be
  split into their measurement atom(s) + a thin gate view.

What it buys: the per-dataset decision collapses from N (which card/rule/verdict/gate/
skill) to **one** ("what does this measure?"); one dataset can serve many gates with no
duplication; orphaned-useful-data becomes impossible; and the substrate is modality-
extensible by rules alone.

---

## Migration approach (do NOT big-bang)

1. **Freeze the identity rule now** (Rule 1) — a card is `(measurement_type ×
   entity_grain)`. Applies to all **new** cards immediately, so the problem stops growing.
2. **Stand up `vocabularies/measurement_types.yaml`** seeded from the *existing* cards'
   claims (each current atom-like card already implies one type). Add a validator that
   every card declares its `measurement_type` + every provider its `evidence_tier`.
3. **Migrate the surface family first** — it is where the pain is live and where CSPA is
   waiting. Register CSPA as a `surface_confirmation` provider; split the straddle cards
   in that family into atoms + gate views.
4. **Migrate remaining straddle cards opportunistically**, one family per branch (per the
   repo's one-workstream-per-branch discipline).
5. **Gate views pull types, not products.** Where a card's `required_inputs` names a
   specific `product_id`, add the `measurement_type` it satisfies; the resolver matches on
   type, falling back to product_id during migration.

---

## Non-goals / guardrails

- Do NOT let a `measurement_type` carry modality-specific *values*. Modality enters via
  rules (`modality_relevance` is routing metadata only). A modality-specific value baked
  into an atom re-couples the layers this doc separates.
- Do NOT create a `measurement_type` per dataset. Types are *claims*; datasets are
  *providers*. Multiple providers per type is the norm, not the exception.
- Do NOT let an `inferred`/`estimated` provider fire a `measured`-strength killer. Tier
  gates admissibility, exactly as the n>=30 floor does for measured negatives.
- Do NOT re-litigate atomize-vs-fuse per card — the concordance test (Rule 2) is the
  standing answer.
- **Population-relative claims are NOT measurement_types.** Measurement_types are
  per-target-entity (a claim about *one* target). Rankings, cross-cohort convergence
  (e.g. pan-tumor CDH17/GJB3 convergers), and cross-target mutual-exclusivity are
  operations over a *population of targets/indications* — a different product class (the
  panorama / cohort-scan), correctly kept out of the per-target skills. Do not try to
  stuff a ranking into a single per-target cell; it is category-incoherent. This is why
  `surfaceome-cohort-ranking` was dropped from the per-target fan-out.

---

## Appendix — pressure-test (15 cases, 2026-07-21)

The model was stress-tested against real and adversarial cards before adoption. Nothing
broke it; 8 refinements surfaced (5 structural, 3 dynamic), each folded into the rules
above. "Held" = the rules as written give the right answer; "Refine" = forced a rule
addition/qualification.

| # | Case | Result → where folded |
|---|---|---|
| 1 | `crispr-rnai-dependency-concordance` (card reads cards, not data) | **Refine** → Rule 4 (typed edges / DAG) |
| 2 | `genomic-alteration-profile` multi-class combiner | Held → prescribes gate-view + resolver, not code combiner |
| 3 | `mutation-hotspot-frequency` vs `mutation-type-counts` | Held → concordance test beats "both about mutations" trap |
| 4 | `prism-crispr-concordance` (1 provider → Required + Tractability) | Held → cleanest decoupling win (flow-pattern 2) |
| 5 | `dependency-predictability` (card with no consumer) | Held → orphan-with-no-puller is a first-class visible state |
| 6 | `normal-tissue-liability` vs `tumor-vs-normal-selectivity` (same biology, opposite framing) | **Refine** → Rule 1 discriminator (b), framing-by-consumer |
| 7 | `mutation-stratified-dependency` (cross-claim within one dataset) | Held → derived edge is type→type, agnostic to dataset count |
| 8 | 3 dependency slices (subtype / lineage / genotype) | Held *only with* Rules 4+1(b): slice-of-claim (grain) vs contrast-is-claim (derived) |
| 9 | `dependency-lineage-selectivity` at `target_lineage` grain | **Refine** → Rule 1: grain is a governed, extensible vocabulary |
| 10 | hypothetical future tumor scRNA atlas | Held → registers as provider; dormant `sc_rna` slot lights up, zero skill edits |
| 11 | CSPA vs SURFY disagree on `surface_confirmation` | **Refine** → Rule 5: `multi_provider_policy`; never silently average |
| 12 | `tumor-vs-normal-selectivity` grain changes at runtime by query scope | **Refine** → Rule 5: emittable-grain (capability) vs requested-grain (query) |
| 13 | subtype grain present but n=4 (below floor) | Held → admissibility enforced per-instance at rule layer (Rule 4) |
| 14 | cross-cohort convergence / rankings | **Boundary** → non-goal: population-relative claims are a different product class |
| 15 | DepMap 26q1 → 26q2 re-release | Held → provider identity includes pin (Rule 5); new instances, not new types |

**Meta-finding.** The first draft treated the model as purely bottom-up (data defines
types → types define grains → gates consume). The hard cases show it is
*bidirectionally constrained*: the question shapes type identity (framing, case 6);
comparisons create types from types (DAG, cases 1/7/8); slicing dimensions are open-ended
(grain vocab, case 9); and there is a hard boundary against population-relative claims
(case 14). The architecture survives — as a **constrained DAG with governed vocabularies,
per-type conflict policies, and per-instance admissibility** — and most of the added
machinery (concordance, n-floor, content-pin, panorama-separation) already exists in the
framework and is merely *named and unified* here.
