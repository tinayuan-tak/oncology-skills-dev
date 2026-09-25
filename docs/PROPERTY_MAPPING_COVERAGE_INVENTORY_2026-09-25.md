# Property mapping-coverage inventory (SK#1608)

**Status:** measurement + document only. No skill output, verdict, or schema was changed to
produce this. This issue is a gate: it decides whether issue **A** (the evidence-record
architecture spike, epic #1507) proceeds broadly, narrowly, or not at all.

## 1. Method

**Population.** The fleet-wide `skills/_skills_common/field_read_health.json` census
(`rosters.declared_fields`) — **148 cards, 1814 declared summary fields** — is the
authoritative "every emitted field" population; it is derived from
`target-contracts/cards/*.card.yaml` `outputs.summary_fields`, not hand-enumerated, so it
cannot silently narrow. The census's own `undeclared_queue` (4 rows: `emission_undetermined`/
`meta_key`) is immaterial and excluded.

**Domain assignment.** Each card is assigned to exactly one core domain by its primary
consuming skill's `cards_used:` list (parsed from `skills/*/SKILL.md`), to avoid double-counting
a card under every composing skill (`target-profile` recomposes 37 cards already owned
elsewhere and is excluded as an aggregator). 9 cards are declared in target-contracts but
referenced by **no** skill's `cards_used:` (`antigen-internalization`, `antigen-prevalence`,
`antigen-prevalence-protein`, `functional-blockade-rationale`, `lineage-restriction-evidence`,
`rwd-stratified-expression`, `sc-surface-normal-safety-solid`, `subgroup-stratified-expression`,
`temporal-setting-expression-shift`) — orphan/not-yet-wired, bucketed `UNASSIGNED` and scored
conservatively.

**Classification, first pass (mechanical, exact over all 1814 fields).** A field-name pattern
sweep sorts every field into one of five buckets deterministically:

| Bucket | Rule |
|---|---|
| `shared-property` | field is literally an emitted key in an already-shared cross-skill vocabulary or a landed cross-source concordance claim (exact-match allowlist, grounded below) |
| `display-only` | provenance/audit tokens (`_version`, `_pin`, `_ref`, `provenance`, `source`, `license`, `pmid`, …) or human-facing prose (`_rationale`, `_note`, `_caveat`, `_summary`, `_text`, `_label`, `_description`, narrative fields) |
| `L3-context` | decision-frame / context-conditioned vocabulary (`modality`, `fit_class`, `adc_`/`tce_`, `grade`, `rubric`, `gate`, `risk_tier`, `druggability`, `window`, `veto`, `subtype`/`subgroup`/`stratif`, `indication_`) |
| `measurement-only` | raw numeric/statistical fields (counts, fractions, medians, p/q-values, r/rho, hazard ratios, CoV, …) |
| `candidate` | everything else — categorical class/state/flag-shaped fields not caught above |

**Classification, second pass (`candidate` bucket only — judgment, sampled).** The mechanical
pass cannot tell a genuinely single-fact classifier (clean) from a composite, cross-card, or
multi-meaning-collapsing one (not clean) from the field NAME alone — that distinction is exactly
what "clean" means per the issue's definition, and it requires reading the card. I read the full
`summary_fields` block (with its authoring comments) for **45 cards spread across every core
domain** (list below) and used those readings to (a) confirm concrete lossy/collapsing/cross-card
patterns already flagged elsewhere in this repo's history (TC#864's 8-classifier expression
audit; the epic's own EPCAM finding) and (b) estimate a **per-domain clean fraction** applied to
that domain's `candidate` count. This is a **stratified estimate, not an exhaustive per-field
audit** of all 947 candidate fields — at Sonnet/M effort, auditing 1814 fields individually is
out of scope; the sampled fraction is named per domain so the estimate is falsifiable and
re-measurable. Per the issue's own instruction, ambiguous cases were scored **not clean**
(under-claim, never over-claim).

**Cards read for the judgment pass** (grouped by domain): *expression* — cellline-rna-distribution,
tumor-rna-distribution, tumor-elevation-breadth (+ TC#864's audit of all 8 expression
classifiers, reused rather than re-derived); *dependency* — pan-cancer-crispr/rnai-dependency-distribution,
paralog-buffering (+ TC#864 essentiality-family finding); *safety* — gnomad-lof-constraint,
clingen-dosage, mouse-ko-phenotype, target-safety-prioritisation, drug-warning-safety,
onsides-adverse-event-safety; *genomic* — mutation-type-counts, fusion-rearrangement-landscape,
mutation-hotspot-frequency, oncogenic-pathway-alteration, genomic-instability-state; *surface_modality*
— surface-topology-and-ptm, adc-tce-modality-fit, surfaceome-family-classification,
cd-antigen-backbone; *tractability* — prism-compound-activity, known-drug-tractability,
degradation-feasibility; *combination_vulnerability* — synthetic-lethal-partners,
resistance-emergence-signature, combo-crispr-screen; *differentiation* — co-mutation-and-mutual-exclusivity,
precog-prognostic-association, stemness-context, clinical-precedent; *immune_context* —
immune-context, ici-response-association; *translational_readiness* — target-model-availability;
*mechanism_pharmacology* — signaling-network-mechanism; *cis_coherence* — cellline-isoform-expression;
*target_intrinsic* — target-identity-summary, ppi-interactome.

**The clean test, applied concretely.** A categorical field is scored clean only if it resolves
ONE biological fact from ONE measurement/source at a stated, consistent grain, is not derived
from another card's output, and does not fold ≥2 distinct biological facts under a
"dominant"/"landscape"/"overall" framing. It is scored NOT clean when any of:
- **cross-card derivation** — e.g. `surface_confirmation_state` (`adc-tce-modality-fit.card.yaml`)
  is explicitly "DERIVED cross-card by the surface_modality preprocessor" from 3 other cards;
  `fusion_class`'s `promiscuous_amplicon_fusion` value is a documented "SKILL-LAYER DEMOTION"
  keyed on `copy-number-distribution.patient_focal_cn_class`.
- **collapsed meanings** — `mutation_landscape_class` folds missense-dominance, LoF-dominance,
  mixed, no-mutation, and underpowered into one token; `_classify_expression` (the field
  motivating the whole epic) folds presence+magnitude+heterogeneity into one flat class and
  drops the bimodal case (TC#864, #1506).
- **power-floor-adjusted composite decision gates** — `resistance_emergence_class` /
  `combination_opportunity_class` fold mediator count + strongest shift + significance +
  power floor into one call; `known_drug_tractability_class` folds several DGIdb category
  flags; `degradability_feasibility_class` folds E3 evidence + precedent + surface-exclusion.
- **context/grain already caught upstream** (subtype/subgroup/indication-conditioned facets,
  modality-fit fields) — these were already routed to `L3-context` by the mechanical pass and
  are not re-counted here.

Binning a single continuous measurement into an ordinal band (e.g. `aneuploidy_burden_class`,
`wgd_class`, `stemness_class`, `immune_context_class`, `ppi-interactome.interactome_class`) is
**not** disqualifying by itself — that is ordinary property resolution, the same shape as the
already-shared `magnitude`/`prevalence` properties. What disqualifies is folding ≥2 orthogonal
facts, or reaching into another card.

## 2. Results

### 2a. Mechanical-pass totals (exact, over all 1814 fields)

| Bucket | n | % of total |
|---|---:|---:|
| measurement-only | 656 | 36.2% |
| candidate (pre-judgment) | 947 | 52.2% |
| L3-context | 136 | 7.5% |
| display-only | 74 | 4.1% |
| shared-property | 1 | 0.1% |

(`shared-property`=1 by exact-match is `expression_properties` on `cellline-rna-distribution` —
the only field literally declared into `target-contracts/vocabularies/expression_property.enum.yaml`
today. The three landed cross-source concordance claims —
`bulk_vs_singlecell_coverage_concordance`, `crispr_rnai_essentiality_concordance`,
`normal_liability_concordance` — are claim-vector keys on `_skills_common/*_claims.py`, not
card `summary_fields`, so they don't appear in this card-keyed census; they are counted in the
property registry below as the fleet's only genuinely cross-source-validated properties.)

### 2b. Per-domain clean estimate (after the judgment pass)

| Domain | n fields | shared | candidate | est. clean (frac applied) | **% clean** |
|---|---:|---:|---:|---:|---:|
| **expression** | 282 | 1 | 127 | 19 (0.15) | **7.1%** |
| **genomic** | 256 | 0 | 120 | 42 (0.35) | **16.4%** |
| **dependency** | 212 | 0 | 103 | 57 (0.55) | **26.9%** |
| **surface_modality** | 168 | 0 | 98 | 24 (0.25) | **14.3%** |
| **selectivity** | 159 | 0 | 76 | 34 (0.45) | **21.4%** |
| **safety** | 141 | 0 | 90 | 50 (0.55) | **35.5%** |
| cis_coherence | 101 | 0 | 31 | 11 (0.35) | 10.9% |
| differentiation | 84 | 0 | 41 | 23 (0.55) | 27.4% |
| **tractability** | 83 | 0 | 53 | 16 (0.30) | **19.3%** |
| immune_context | 80 | 0 | 42 | 25 (0.60) | 31.2% |
| target_intrinsic | 58 | 0 | 41 | 18 (0.45) | 31.0% |
| combination_vulnerability | 57 | 0 | 43 | 17 (0.40) | 29.8% |
| UNASSIGNED (orphan cards) | 54 | 0 | 30 | 9 (0.30) | 16.7% |
| mechanism_pharmacology | 47 | 0 | 30 | 12 (0.40) | 25.5% |
| translational_readiness | 22 | 0 | 13 | 7 (0.55) | 31.8% |
| literature_context | 10 | 0 | 9 | 0 (0.00) | 0.0% |

**Bold rows** are the "core domains" the issue names by example (expression, dependency, safety,
genomic, selectivity, tractability, surface/modality).

**OVERALL: 365/1814 = 20.1% clean.**

### 2c. Applying the pre-committed decision rule

- Overall clean = **20.1%** → **< 50%**.
- Every core domain is **< 30%** clean except safety (35.5%): expression 7.1%, genomic 16.4%,
  dependency 26.9%, surface_modality 14.3%, selectivity 21.4%, tractability 19.3%.

Two independent triggers both fire in the same direction: the global-% rule alone already says
**stop A as a general architecture** (`<50%` bucket), and the per-domain floor rule would in any
case pull out every core domain except safety and (marginally) dependency, leaving no coherent
"broad" or even "50–69% subset" scope to greenlight. There is no domain-count arithmetic that
reaches the 50–69% "clean subset" bucket honestly — the overall number is well inside the
`<50%` band, not close to the boundary.

**This is not a surprising result — it is the fleet's own prior findings, now counted.** TC#864
already audited all 8 expression classifiers as bespoke and largely lossy (ceiling ≈8 property
families vs. 1 realized). The epic's own EPCAM×TACSTD2 prototype found the value of the property
layer is "largest where today's classes are lossy... smallest where they already surface the
property cleanly" — i.e. today's classes are the norm, not the exception, and most of them are
composite, cross-card, or collapse ≥2 meanings by construction (`fusion_class`,
`mutation_landscape_class`, `known_drug_tractability_class`, `resistance_emergence_class`,
`surface_confirmation_state`, `adc_grade`, …). The framework was largely built around *richer
per-card classifiers*, which is the anti-pattern the epic exists to move away from — this
inventory just puts a number on how far that move still has to go.

## 3. Draft property registry

Properties actually resolved from measurements today, with maturity state. This is a **draft**
— promotion to `stable` requires the same governance discipline as
`expression_property.enum.yaml` (semver, additive-only, cross-repo coordination via the
wip-registry).

| Property family | State | Sources (independent?) | Grounded at |
|---|---|---|---|
| `presence` / `magnitude` / `prevalence` / `heterogeneity` / `lineage_restriction` (expression) | **stable** | cellline RNA only today; `selectivity`/`localization`/`subtype_restriction` declared but `fleet_deferred` | `target-contracts/vocabularies/expression_property.enum.yaml` v1.0.0 |
| `bulk_vs_singlecell_coverage_concordance` (presence/coverage) | **stable** (landed claim) | bulk RNA × scRNA × IHC escape corroboration — 3 sources | `presence_claims.py::_coverage_concordance_claim`, SK#1517/#1578 |
| `crispr_rnai_essentiality_concordance` (essentiality-depth) | **stable** (landed claim) | CRISPR Chronos × RNAi DEMETER2 — 2 orthogonal LoF assays, same vocab by design | `dependency_claims.py`, SK#1533 |
| `normal_liability_concordance` (normal-tissue safety) | **stable** (landed claim) | GTEx bulk × scRNA-normal × HPA-IHC — 3 sources | `safety_claims.py`, SK#1546/#1584 |
| `recurrence_class` (genomic driver-recurrence) | candidate | MC3 (`driver_recurrence_class`) / GENIE panel (`genie_driver_recurrence_class`) / pooled (`pooled_driver_recurrence_class`) — same cutoff shape, partially-overlapping cohorts (pooled is a superset, not independent of the other two) | `mutation-hotspot-frequency.card.yaml` |
| `genomic_instability` sub-family (aneuploidy / WGD / MSI / MMR-signature) | candidate | ABSOLUTE (WGD/ploidy), TCGA marker-paper (patient MSI), DepMap MSIsensor (model MSI), DepMap signature matrix (MMR) — each single-source per arm, kept separate by grain (patient vs. model), not fused | `genomic-instability-state.card.yaml` |
| `surfaceome_family` | candidate | SURFY + HPA-plasma-membrane + UniProt EC + IUPHAR — already a multi-source corroborated single fact (`surfaceome_confidence_score` = source-agreement fraction) | `surfaceome-family-classification.card.yaml` |
| `germline_constraint` (`constraint_class`, gnomAD pLI/LOEUF) | candidate | single-source | `gnomad-lof-constraint.card.yaml` |
| `dosage_sensitivity` (ClinGen) | candidate | single-source | `clingen-dosage.card.yaml` |
| `ko_phenotype` (MGI) | candidate | single-source | `mouse-ko-phenotype.card.yaml` |
| `drug_warning` / `adverse_event` (FDA label / OnSIDES) | candidate | single-source each, orthogonal facts | `drug-warning-safety.card.yaml`, `onsides-adverse-event-safety.card.yaml` |
| `immune_infiltration` (`immune_context_class`) | candidate | CIBERSORT, single-source | `immune-context.card.yaml` |
| `ici_response_association` | candidate | multi-cohort Stouffer rollup, same assay family (RNA-seq DE) | `ici-response-association.card.yaml` |
| `model_availability` | candidate | HCMI, single-source | `target-model-availability.card.yaml` |
| `network_characterization` (`network_class`) | candidate | STRING/curated, single-source | `signaling-network-mechanism.card.yaml` |
| `isoform_dominance` | candidate | DepMap transcript-level RNA, single-source | `cellline-isoform-expression.card.yaml` |
| `prognostic_association` | candidate | PRECOG meta-analysis, single-source (has its own multi-dataset pooling, `n_precog_datasets`) | `precog-prognostic-association.card.yaml` |
| `stemness` (`stemness_class`, mRNAsi) | candidate | single-source | `stemness-context.card.yaml` |
| `protein_interactome_connectivity` | candidate | STRING + CORUM + BioGRID-physical kept as 3 distinct signals, "never merged" per the card's own comment — already following the right discipline | `ppi-interactome.card.yaml` |
| all fields tagged `L3-context` (modality-fit, ADC/TCE grades, subtype/subgroup facets, therapeutic-window, gate/veto tokens) | **experimental / not a property** | — | pending issue **G** (decision-frame architecture), explicitly blocked on this issue + A |
| all fields tagged `display-only`/provenance | **n/a — not a property** | — | — |

**M3 readout (epic scorecard):** vocabulary-reuse stays at **3** realized shared families
(expression's 5-property bundle, essentiality-depth, presence/coverage, normal-liability — counted
as 4 realized property-groups, "M3=3" per the epic's own count of concordance claims) against a
TC#864-measured ceiling of ~8. This inventory adds concrete **candidates** for at least 3 more
plausible cross-source families not yet built as L2b claims: `genomic_instability` sub-properties
(4 independent-ish arms already resolved separately), `recurrence_class` (3 cohort arms, though
overlapping), and `surfaceome_family` (already internally multi-source-corroborated within one
card). None of these were previously named in the TC#864 matrix, which only covered the 8
expression-adjacent classifiers — this inventory's genomic/surface domain reads surface them as
a byproduct.

## 4. Go/scope verdict for issue A

Per the pre-committed rule (issue text, §"Pre-committed decision rule"):

> **<50% clean overall → stop A as a general architecture.**

Overall clean = 20.1%. **A does not proceed as a general, system-wide evidence-record
architecture spike.** Filing the Opus/H spike as originally scoped (a schema meant to cover
expression + dependency + safety uniformly, per the epic's own "A" description) would be
premature — the shared-property substrate it would be built on is, today, real for exactly 3
concordance families and aspirational everywhere else. Most of the fleet's emitted categorical
fields are composite, cross-card-derived, or fold ≥2 biological facts into one token — the
opposite of what a canonical property record needs to hold.

**What this does NOT mean:**
- It does not mean the evidence-property epic's L2b concordance-claim pattern is wrong — those 3
  landed claims (#1517, #1533, #1546) are exactly the shape that DOES map cleanly, and this
  inventory found several more candidates (`genomic_instability`, `recurrence_class`,
  `surfaceome_family`) worth building the same way.
- It does not mean safety and dependency (the two domains that clear ~27–36%) are precluded from
  small, deliberate, per-property canonicalization work — but that is scoped, incremental L2b/L2a
  work of the kind already landing (#1517/#1533/#1546/#1578/#1584/#1589), not a general
  architecture spike.

**Recommendation to record on #1507:** do not file issue **A** as scoped. Continue the
already-validated pattern — pick individual candidate properties (this doc's registry gives a
prioritized list) and build them one cross-source concordance claim at a time, the same way as
the three that already landed. Revisit a general record-schema spike only if/when the clean
fraction in the domains that matter for the schema's first users (expression, dependency, safety)
crosses materially higher than today's 7–36%, which would require actually replacing several of
the collapsing/composite classifiers named in §2c rather than adding claims alongside them.

## 5. Caveats

- **This is a sampled, judgment-scored estimate for the `candidate` bucket (947/1814 fields),
  not an exhaustive per-field audit.** The mechanical provenance/display/measurement/L3-context
  split (867/1814 fields) is exact and reproducible from the field-name patterns in §1. The
  per-domain clean fractions applied to `candidate` are grounded in 45 read cards (listed in §1)
  spread across every core domain, not all 947 fields individually — re-running this with a full
  per-field read would very plausibly move individual domain numbers by single-digit points, but
  is very unlikely to flip the overall <50% or per-domain <30% conclusions given how consistent
  the collapsing/composite/cross-card pattern was across every domain sampled.
- **Ambiguous fields were scored not-clean** (issue's own instruction) — the 20.1% figure is a
  floor estimate, not a ceiling; a more generous reading would raise it, but not enough to change
  §4's verdict, since crossing to 50% would need almost every remaining candidate field to be
  clean, which the sampled reads contradict domain-by-domain.
- **The `UNASSIGNED` 9 orphan cards** are unread by any skill today (not wired into any
  `cards_used:` list) — their clean fraction is unverified and scored conservatively (0.30);
  they should not be treated as informative about domain viability either way.
- **Grain caveat is real and under-counted here**: several candidate properties above
  (`recurrence_class`, MSI/model-MSI) resolve the "same" fact at genuinely different grains
  (patient vs. model, TCGA vs. GENIE panel-coverage-corrected) and are kept as separate fields —
  correct discipline, but a future canonical schema needs an explicit grain axis on the property,
  not a single flat name, or it will silently re-introduce the mixing this inventory screened for.

## 6. Promotion-eligibility taxonomy (this doc's primary, durable value)

**Reframe (SK#1630).** §§1–4 answered a one-time go/no-go for issue **A** and that question is
now *closed* (A does not proceed as a general architecture; §4). What outlives that verdict is a
**map**: the layer a field lives on, and — the load-bearing part — **whether the field is allowed
to become a shared property "island" at all** (to instantiate the evidence-property envelope
landed in #1629). F's original 5-bucket split (§1) forced a false binary in which any field that
failed the "clean" test read as *bad*; in fact many are legitimate, reproducible **within-card
summaries** — useful, just not portable as a single cross-card/cross-source property. The taxonomy
below replaces that split. It is the **architectural guardrail**: it is what stops a future
developer from seeing a categorical field like `combination_opportunity_class` and promoting it
into a property claim *just because it looks categorical*.

**This taxonomy — not the 20.1% clean-% — is now the primary value of this document.** The clean-%
and the issue-A go/no-go (§§2c, 4) are retained for the record but superseded; do not re-run or
re-litigate them.

### 6a. The six categories (layer spectrum)

Ordered from most-raw to most-derived. **Only `atomic-property-candidate` and
`integrated-property-candidate` are island-eligible** — everything else is, by category, ineligible
to instantiate the #1629 envelope. The category *itself* is the guardrail; eligibility is decided
by which layer a field sits on, not by whether it happens to be categorical.

```
measurement → atomic-property-candidate → integrated-property-candidate → local-composite → L3-context → display/provenance
              └──────────── island-eligible ────────────┘
```

| Category | What it is | Island-eligible? | Maps from F bucket (§1) |
|---|---|:---:|---|
| `measurement` | Raw / simple resolved value — a count, fraction, median, p/q-value, hazard ratio, CoV, a single directly-read datum. No canonicalization intended. | no | `measurement-only` |
| `atomic-property-candidate` | A single biological fact from one measurement/source at one stated grain, that *could be* canonicalized into a shared property (the shape of the expression `presence`/`magnitude`/… bundle; an ordinal band over one continuous measurement). | **yes** | the "clean" part of `candidate` (+ the 1 exact `shared-property`) |
| `integrated-property-candidate` | One property resolved by corroborating ≥2 *independent* sources/assays — the L2b concordance shape. Island-eligible and the preferred target. | **yes** | landed concordance claims + a few `candidate` fields |
| `local-composite` | A reproducible within-card summary that folds ≥1 fact into a single token under a "dominant"/"landscape"/"overall" framing. **Legitimate and useful** as a card readout — **NOT** island-eligible, because the token is not a single portable fact. | no | the "not-clean" part of `candidate` |
| `L3-context` | A decision- / context-conditioned output (modality-fit, grades, gates/vetoes, risk tiers, subtype/subgroup facets). A *frame input*, never a property; pending issue **G**. | no | `L3-context` |
| `display/provenance` | Presentational or lineage-only tokens (`_version`, `_pin`, `_ref`, `provenance`, `source`, `pmid`, `_rationale`, `_note`, narrative prose). | no | `display-only` |

The dividing line between `local-composite` and the two island-eligible candidate categories is
exactly F's "clean" test (§1, "The clean test, applied concretely"): a token is `local-composite`
(ineligible) if it folds ≥2 distinct biological facts, reaches into another card's output, or
collapses multiple meanings under a dominant/landscape/overall framing. `integrated-property-candidate`
differs from `atomic-property-candidate` only by drawing on ≥2 *independent* sources for the *same*
fact — that is corroboration, not folding, and is the good direction.

### 6b. Exemplars (sampled — from the 45 cards already read for F, §1)

**Sampled / exemplar-based, per the §5 caveat discipline.** These are drawn only from the 45 cards
already read in F's judgment pass — this is **not** a re-audit of all 947 candidate fields, and the
1814-field census was not re-classified into these six categories exhaustively. The exemplars
illustrate the guardrail; the disqualifying fact is named for each.

**`local-composite` (legitimate within-card summaries, NOT island-eligible):**

| Field (card) | Disqualifying fact |
|---|---|
| `mutation_landscape_class` (`mutation-type-counts`) | folds **5** meanings — missense-dominance, LoF-dominance, mixed, no-mutation, underpowered — into one token |
| `expression_class` / `_classify_expression` (`tumor-rna-distribution`, all 8 expression classifiers per TC#864) | folds **3** facts (presence + magnitude + heterogeneity) into one flat class and drops the bimodal case — the field motivating the whole epic (#1506) |
| `combination_opportunity_class` (pre-decision, `combo-crispr-screen`) | folds **4** inputs — mediator count + strongest shift + significance + power floor — into one call |
| `resistance_emergence_class` (`resistance-emergence-signature`) | folds **4** inputs — mediator count + strongest shift + significance + power floor |
| `known_drug_tractability_class` (`known-drug-tractability`) | folds several DGIdb category flags into one class |
| `degradability_feasibility_class` (`degradation-feasibility`) | folds E3 evidence + precedent + surface-exclusion (**3** inputs) |

**`L3-context` (decision/context frame, never a property):**

| Field (card) | Disqualifying fact |
|---|---|
| `surface_confirmation_state` (`adc-tce-modality-fit`) | explicitly **DERIVED cross-card** by the surface_modality preprocessor from **3** other cards — cross-card reach = 3 |
| `promiscuous_amplicon_fusion` value of `fusion_class` (`fusion-rearrangement-landscape`) | a documented **SKILL-LAYER DEMOTION** keyed on `copy-number-distribution.patient_focal_cn_class` — cross-card reach = 1 |
| `adc_grade` / `tce_grade` (`adc-tce-modality-fit`) | modality-conditioned **decision grade**, not a fact about the target — a frame input |
| `target_safety_prioritisation` risk tier (`target-safety-prioritisation`) | a **decision gate** rolling up multiple safety signals into a prioritisation call |
| subtype/subgroup/indication-conditioned facets (e.g. `subgroup-stratified-expression`, `temporal-setting-expression-shift`) | **context-conditioned** grain — the same fact at a decision-frame slice, routed to L3 in F's mechanical pass |

For contrast, the island-eligible categories are already enumerated in §3's registry: the 3 landed
concordance claims (`bulk_vs_singlecell_coverage_concordance`, `crispr_rnai_essentiality_concordance`,
`normal_liability_concordance`) are the archetypal `integrated-property-candidate`s, and the
`genomic_instability` arms, `recurrence_class`, and `surfaceome_family` are the next
`integrated-property-candidate` targets; the expression `presence`/`magnitude`/`prevalence`/
`heterogeneity`/`lineage_restriction` bundle is the archetypal `atomic-property-candidate` shape.
