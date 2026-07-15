# iDAS Subtype Pipeline — Master Design

**Status**: Phase 0 complete. Design incorporates Phase-0d agent verdicts (resolver-product shape, method-level iteration, list-typed card records). Ready for user sign-off before Phase 1 code work begins.

**Parent plan**: `/home/sagemaker-user/.claude/plans/deep-foraging-thompson.md`

## Purpose

Integrate three previously-independent workstreams into one coherent pipeline:

1. **Scope-flexibility** — the target-evaluation skill accepts any combination of `{target, indication, indications, subtypes}` with 5 explicit modes
2. **Signal-vocabulary redesign** — rules layer grows from modality-only to target-first channels (`target_essentiality`, `target_tractability`, `axis_fit`, `indication_fit_*`, `subtype_fit_*`)
3. **Subtype-membership data layer** — data-catalog + methods gain the ability to iterate over iDAS strata; today the framework is single-target × single-indication throughout

These three cannot land independently: signal channels reference subtype tiers, subtype-tier rules require subgroup-metadata that only makes sense with a scope contract, scope resolution needs a subtype-membership resolver. This document is the integrated view.

## Framework reframing

**Old framework question**: "Given target X and indication Y, which modality wins?"

**New framework question**: "Given a target and a scope (which may be target-only, one indication, a list of indications, an indication × subtype, or indications × subtypes), what evidence supports viability as a cancer drug target — first target-level, then indication-level, then subtype-level, then modality-level?"

The modality question is the LAST tier, not the ONLY tier. Rules today make a modality claim per firing; rules under the new schema make a **tier-tagged claim** per firing, and killer semantics operate within-tier so a target-essentiality killer doesn't disqualify a specific-subtype rescue.

**Every iDAS = one indication** (2026-07-14 reframe). Strategic groupings (Thoracic, GI-upper, Heme) are metadata that resolve to indication-lists at query time; they are NOT first-class iDAS entities. This eliminates the earlier "panel with dual-membership" complication.

## Locked design decisions

Decisions 1-7, 9 are from the parent plan. Decisions 8, 10, 11 are Phase-0d verdicts that OVERTURNED parent-plan straws based on concrete evidence:

1. **Scope typed record**: `Scope = {indication?, indications?, subtypes?}` — singular `indication` (str) or plural `indications` (list[str]) but not both; `.mode` computed from populated fields; enumerated ids validated at construction time against `idas_indications.yaml`. Strategic-bucket queries (e.g. Thoracic) resolve to `indications=[...]` at invocation via `idas_strategic_buckets.yaml`
2. **Five modes**: `target_only | indication | multi_indication | indication_subtype | multi_indication_subtype`
3. **Same-skeleton output, mode-specific header block**. Mode badge visible on every verdict
4. **Signal-absence split**: `insufficient` (evidence in scope but weak) vs `not_applicable` (evidence out of scope) — rules declare which they emit; validator enforces
5. **Channel-precedence**: `axis_fit → target_essentiality → target_tractability → indication_fit_* → subtype_fit_* → modality_fit_*`. Killers short-circuit within their tier only
6. **Modality-fit stays context-blind for iter-1** (avidity-gated bispecifics deferred)
7. **Cross-context reasoning stays in synthesis**, not rules. Rules match single-context per rule
8. **Card output convention: list-typed records** (`per_subgroup_metrics: [{stratum, class, subgroup_n, subgroup_n_floor_met, ...}]`) — **overturned Phase-0d** from parent-plan straw of flat-tagged fields. Reason: card schema `summary_fields: maxItems=50` overflows on Lung (18 strata × 3+ fields per stratum ≈ 60+); precedent already ships in `subgroup-stratified-expression.card.yaml`; `subgroup_n_floor_met` naturally lives on records
9. **Backward compatibility**: current `target-profile(target, indication)` invocation stays valid for one release; deprecates after
10. **Iteration locus: method-level** (methods accept `subgroups: list[str] | None` and return `{subgroup: result}`) — **overturned Phase-0d** from parent-plan straw of dispatcher-level fan-out. Reason: ~40× I/O amortization on expensive artifacts (recount3, DepMap Chronos, resolver parquet); localizes iteration with compute; enables natural DerSimonian-Laird pooling wire-in; strictly easier synthesis-engine unification
11. **Resolver product: tall parquet per `(source × indication)` shard** with tri-valued `is_member ∈ {true, false, null}` + `row-absent` fourth state — Phase-0d verdict. Composite strata resolved at query time, not materialized. Panels resolve at dispatcher-level; resolver is panel-agnostic. Release discipline per source, with `subgroup_catalog_ref` link so catalog revisions can also trigger re-emit

## iter-1 scope (post Phase-0a resolution + 2026-07-14 reframe)

**Every iDAS = one indication.** Eight iDAS entries in iter-1; ninth deferred to iter-1b. Strategic groupings (Thoracic / GI-upper / Heme) are metadata annotations on each indication, NOT iDAS entities — they resolve to indication lists at query time via `idas_strategic_buckets.yaml`.

| iDAS | Display | Strategic bucket | Iter-1 status | Strata spec |
|---|---|---|---|---|
| COADREAD | CRC | (standalone) | Live; anchored in `.claude/plans/you-are-a-skilled-drifting-pixel.md` | (existing plan) |
| NSCLC | NSCLC | Thoracic | Live | [nsclc.md](idas-strata/nsclc.md) |
| SCLC | SCLC | Thoracic | Live (cell-line-only) | [sclc.md](idas-strata/sclc.md) |
| HNSC | Head & Neck Cancer | Thoracic | Live | [hnsc.md](idas-strata/hnsc.md) |
| STAD | Gastric | GI-upper | Live | [stad.md](idas-strata/stad.md) |
| ESCA | Esophageal | GI-upper | Live | [esca.md](idas-strata/esca.md) |
| PAAD | PDAC | GI-upper | Live | [paad.md](idas-strata/paad.md) |
| AML | AML | Heme | Live | [aml.md](idas-strata/aml.md) |
| CML | CML | Heme | **iter-1b deferred** | [cml.md](idas-strata/cml.md) |

**Sample annotation planning** — every stratum in every spec is mapped to a concrete annotation method (Modality A/B/C) in [SAMPLE_ANNOTATION_PLAN.md](SAMPLE_ANNOTATION_PLAN.md). Three assigner methods (`subgroup_assigner_directly_tagged`, `_maf_filter`, `_classifier`); the third is new-scaffold work in Phase 2.

## Strategic buckets (Phase 1 vocab)

Bucket = set of indications; encoded as `target-contracts/vocabularies/idas_strategic_buckets.yaml` in Phase 1. Straw content:

```yaml
Thoracic:  [NSCLC, SCLC, HNSC]
GI-upper:  [STAD, ESCA, PAAD]
GI-lower:  [COADREAD]
Heme:      [AML, CML]
```

Users never query with `bucket=X`; they resolve to `indications=[bucket_expansion]` at invocation. Buckets are display/discovery convenience only — not part of the Scope contract's semantics.

## Cross-layer canonical shape: records

Phase-0d surfaced an underlying pattern: **records-not-columns** is the canonical stratification shape across all four layers.

- **Layer 2 (resolver)**: tall rows `(sample_id, patient_id, stratum_id, is_member, derivation_source, derivation_value, evaluated_at_release)` — one row per (sample × stratum-evaluated) pair
- **Layer 3 (methods)**: `read_foo(target, indication, subgroups=[...])` returns `{stratum: result}` dict where each value is a record; when `subgroups=None`, singleton path preserved for backward compat
- **Layer 4 (cards)**: `per_subgroup_metrics: [{stratum, class, subgroup_n, subgroup_n_floor_met, subtype_defining_data, ...}]` — list of records rather than flat-tagged fields
- **Layer 4 (rules)**: `when.field: per_subgroup_metrics, in_record: {stratum: MSI_H, class: broadly_high, subgroup_n_floor_met: true}` — matches records within lists; one new sub-schema entry in `interpretation_rules.schema.json`

This consistency is not coincidental — data flowing as records from resolver through methods into cards means the rule engine's match primitive is the same shape as the compute artifact's return shape, which is the same shape as the resolver's row. **One shape, four layers.**

## Architecture — the four-layer pipeline

```
Layer 1: Data sources
  tcga-marker-papers-subtypes-2018 (patient labels)
  depmap-consortium-26q1/OmicsInferredMolecularSubtypes.csv (cell-line labels)
  gdc-pancohort-somatic (MAFs → mutation-defined strata)
  BeatAML1.0-COHORT, TARGET-AML (heme adjunct patient cohorts)
        │
        │  Phase 1: subgroup catalogs per-indication authored
        ▼
Layer 2: Subtype resolver derived product
  subgroup-catalogs/{indication}/{quarter}.yaml (design)
        +
  data-catalog/manifests/derived/{source}-subgroup-assignments-{ind}-v1
  yielding subgroup_assignments.parquet per (source × indication)
        │
        │  Phase 2: assigner methods land; parquets emit
        ▼
Layer 3: Methods with subtype iteration
  Existing methods (dge_deseq2, depmap_chronos, gdc_somatic_hotspot, ...)
  gain a subtype/scope-list param OR the dispatcher fans out
  (Phase 0d agent decides the fork)
        │
        │  Phase 3: methods filter samples by resolver.parquet
        ▼
Layer 4: Cards + rules + channels
  Card outputs: either flat-tagged (expression_class__subtype_MSI) OR
  list-typed (per_subgroup_metrics: [...])  (Phase 0d agent decides)
  Rules: emit tier-tagged signals (target_*, indication_fit_*,
  subtype_fit_*, modality_fit_*) with subgroup-metadata required
        │
        │  Phase 4: schemas + rules + channels + validator
        ▼
Layer 5 (Skills): synthesis + artifact
  target-profile(target, scope=Scope(...))
  Fan-out Scope → (indication, subtype) tuples
  Per-mode artifact templates (target-only ranking, panel convergence
  table, subtype subgroup-n floor)
```

## Resolver product (Phase 0d verdict)

Per-sample subtype-membership resolver at
`s3://onc-compbio/derived/subgroup-assignments/{indication}/{data_source}/{release_pin}/assignments.parquet`
with sibling `manifest.yaml` conforming to `subgroup_assignment.schema.json`.

**Tall grain: one row per (sample × stratum-evaluated) pair.**

| column | type | notes |
|---|---|---|
| `sample_id` | string | canonical: TCGA aliquot barcode truncated to sample (`TCGA-XX-XXXX-01`), DepMap `ModelID`, GENIE `SAMPLE_ID`, BeatAML `dbgap_subject_id`, TARGET-AML `TARGET_USI` |
| `patient_id` | string | canonical patient identifier; nullable for cell-line rows |
| `source_native_id` | string | original ID before normalization (audit trail) |
| `stratum_id` | string | atomic stratum from the catalog (`MSI_H`, `KRAS_G12C`, `FLT3_ITD`) |
| `is_member` | bool, **nullable** | tri-valued semantics (see below) |
| `derivation_source` | string | one of the schema's enum values (`directly_tagged_clinical` etc.) |
| `derivation_value` | string, nullable | e.g., `p.G12C` for MAF hits; `MSI-H` for clinical field |
| `evaluated_at_release` | string | release-pin of the input manifest |

**Four-state semantics** for evidence presence, mapping onto rules-layer signals:

| Physical state | Semantic meaning | Rules-layer emission |
|---|---|---|
| `is_member = true` | Rule evaluated, predicate satisfied | rules fire per configured signal |
| `is_member = false` | Rule evaluated, predicate not satisfied | `not_applicable` |
| `is_member = null` (row present) | Stratum applicable but data missing (e.g., MAF absent) | `insufficient` |
| Row absent | Stratum out-of-scope for sample's cohort | `insufficient` (rules detect via catalog `applies_within`) |

This is the load-bearing shape that lets Phase-4 rules honor the `not_applicable` vs `insufficient` distinction without re-deriving.

**Composite strata resolved at query time, NOT materialized.** `MSS_RASMut_3Lplus` is a downstream intersect over atomic `MSS=true ∧ KRAS_*=true` + any RWD LOT constraint at Phase 2. Reason: composites are combinatorial and churn faster than atomics.

**AML cross-cohort**: separate shards `AML/tcga/`, `AML/beataml/`, `AML/target-aml/`, `AML/genie/` — cohorts version independently; unioned at query time by the shared loader.

**Panel-overlap resolved at dispatcher level, not resolver level.** Assignments live at the indication grain. `idas_panels.yaml` declares `GI ⊃ {STAD, ESCA, PAAD}`; both PDAC-mode and GI-panel-mode read the same PAAD resolver shard.

**Release discipline**: per-source `release_pin` + `subgroup_catalog_ref` in the manifest. Upstream refresh triggers per-shard re-emit; catalog revision triggers all-shard re-emit.

## Signal channels (9 new + 5 existing modality = 14)

| Channel | Tier | Description | Killer semantics |
|---|---|---|---|
| `axis_fit` | axis-arbitration | Evidence supports/opposes the curated biology axis (intracellular / surface / mixed) | Killer here suggests re-curation, not veto |
| `target_essentiality` | target | Is losing this target functionally consequential in cancer? | Killer → target-tier veto; indication/subtype rules still fire but rendered "target-not-viable" |
| `target_tractability` | target | Is there a druggable pocket / degron / surface epitope? | Killer within-tier; subsets modality-fit options |
| `target_precedent` | target | Has anyone in industry validated this target class? | No killer semantics — precedent is prior, not veto |
| `indication_fit_convergence` | indication | Does the biology converge across a user-provided list of indications (multi-indication mode, potentially strategic-bucket-expanded)? | Killer → convergence-mode says "no" but single-indication may still yes |
| `indication_fit_single` | indication | Does the biology fit a single indication? | Killer within-tier |
| `subtype_fit_genomic` | subtype | Does biology fit a genomic-defined subtype (mutation, CNV, fusion, MSI, TMB)? | Killer within-tier |
| `subtype_fit_expression` | subtype | Does biology fit an expression-defined subtype (CMS, Moffitt, NAPY, PAM50, basal/luminal)? | Killer within-tier |
| `subtype_fit_immune` | subtype | Does biology fit an immune-defined subtype (Thorsson C1-C6, TAM-hi, T-cell-inflamed)? | Killer within-tier |
| `modality_fit_small_molecule` | modality | (existing) | (existing) |
| `modality_fit_degrader` | modality | (existing) | (existing) |
| `modality_fit_adc` | modality | (existing) | (existing) |
| `modality_fit_bite_tce` | modality | (existing) | (existing) |
| `modality_fit_antibody` | modality | (existing) | (existing) |

**Channel-precedence**: `axis_fit → target_* → indication_fit_* → subtype_fit_* → modality_fit_*`. `axis_fit: killer` short-circuits all downstream reasoning. `target_essentiality: killer` reports target-tier veto but does NOT prevent indication/subtype rules from firing — those still evaluate to enable "pan-essential except in subtype X" narratives. Modality-tier killers only affect their own modality column.

## Scope contract

Every iDAS = one indication (per 2026-07-14 reframe). "Panel" queries are lists of indications; strategic buckets (Thoracic, GI-upper) are resolved BEFORE Scope construction, not encoded in Scope itself.

```python
@dataclass(frozen=True)
class Scope:
    indication:  str | None = None       # canonical iDAS code (COADREAD, NSCLC, HNSC, ...)
    indications: list[str] | None = None # for multi-indication queries
    subtypes:    list[str] | None = None # canonical stratum_ids from subgroup catalogs

    @property
    def mode(self) -> Mode:
        if self.subtypes:
            return "multi_indication_subtype" if self.indications else "indication_subtype"
        if self.indications: return "multi_indication"
        if self.indication:  return "indication"
        return "target_only"

    def __post_init__(self):
        if self.indication and self.indications:
            raise ValueError("indication (singular) and indications (list) are mutually exclusive")
        if self.subtypes and not (self.indication or self.indications):
            raise ValueError("subtypes require indication or indications")
        # + enumerated-id validation against idas_indications registry + per-indication subgroup catalogs
```

**Strategic-bucket resolver** (higher-level helper, NOT part of Scope):
```python
def resolve_bucket(bucket_id: str) -> Scope:
    """Thoracic -> Scope(indications=[NSCLC, SCLC, HNSC])"""
    indications = load_yaml("vocabularies/idas_strategic_buckets.yaml")[bucket_id]
    return Scope(indications=indications)
```

**Backward compat**: `target-profile(target, indication="COADREAD")` remains legal for one release, sugar for `Scope(indication="COADREAD")`; deprecation warning emitted.

## Card output convention (Phase 0d verdict: LIST-TYPED RECORDS)

**Locked: `per_subgroup_metrics` records.** The straw for flat-tagged fields is overturned per Phase-0d evidence: `card.schema.json` has `summary_fields: maxItems: 50`, and Lung's 18 strata × 3-4 fields overflows the cap. Precedent exists (`subgroup-stratified-expression.card.yaml`); `subgroup_n_floor_met` naturally lives on records; PR diffs are readable.

Card shape:
```yaml
outputs:
  summary_fields:
    - n_cell_lines_evaluated
    - expression_class_panel              # panel-wide scalar (retain flat)
    - per_scope_expression                # list of per-scope records
    - cross_scope_delta_class             # scalar summary of divergence

  summary_fields_vocabulary:
    expression_class_panel: [broadly_high, broadly_moderate, lineage_restricted, broadly_low, data_unavailable]
    cross_scope_delta_class: [uniform, mildly_divergent, strongly_divergent]

  summary_fields_record_schemas:          # NEW addition to card.schema.json
    per_scope_expression:
      scope_type:   [indication, subtype, lineage]
      scope_id:     string                 # e.g. "MSI_H", "EGFR_mut_ex19del"
      subgroup_n:   integer
      subgroup_n_floor_met: boolean
      subtype_defining_data: string        # genomic | expression | immune
      expression_class:
        enum: [broadly_high, broadly_moderate, lineage_restricted, broadly_low, data_unavailable]
```

Rule shape (with new `in_record` predicate):
```yaml
- rule_id: any-subtype-broadly-high
  when:
    card_id: expression-distribution
    field: per_scope_expression
    in_record: {scope_type: subtype, expression_class: broadly_high, subgroup_n_floor_met: true}
  signals: {target_essentiality: supportive}
  dominant: true
```

One rule, all subtypes, `subgroup_n_floor_met` enforced declaratively.

Schema deltas in Phase 4:
- `card.schema.json` — add `summary_fields_record_schemas` block for list-typed field shapes
- `interpretation_rules.schema.json` — add optional `in_record` sub-schema to `when` block (~20 lines): map of `record_field → value | [values]` predicates, all conjunctive within one rule

## Method-vs-dispatcher iteration (Phase 0d verdict: METHOD-LEVEL / Path B)

**Locked: method-level iteration.** The straw for dispatcher-level fan-out is overturned per Phase-0d evidence: recount3 gene counts, DepMap CRISPRGeneEffect, and the resolver parquet each cost ~50 MB / 1 file read per invocation. Under dispatcher-level with 6 indications × 5 subtypes × 8 methods, we'd re-fetch these ~40× per top-level query. Method-level amortizes to 1 fetch per method per invocation.

Method signature:
```python
def read_dge_gene_row(
    target: str,
    manifest_id: str,
    subgroups: list[str] | None = None,          # None = whole cohort (backward compat)
    subgroup_assignments_manifest: str | None = None,
) -> dict | dict[str, dict]:
    """
    Singleton path (subgroups=None): returns one card-field dict as before.
    Panel path (subgroups=[...]): loads data + assignments ONCE, iterates,
    returns {subgroup_id: card_field_dict}.
    """
    table = pq.read_table(path, filesystem=s3, filters=[("gene_symbol", "=", target)])
    if subgroups is None:
        return _row_to_card_fields(table, manifest_id)
    assignments = _load_assignments(subgroup_assignments_manifest)   # ONE read
    return {s: _row_to_card_fields(_filter(table, assignments, s), manifest_id)
            for s in subgroups}
```

**Downstream wins beyond I/O amortization:**
- **Synthesis-engine unification**: both compose-dashboard and target-profile read the same panel-shaped return dict; unifying them (parent-plan top-of-list interpretation-layer refactor) is strictly easier
- **Meta-analysis extensibility**: DerSimonian-Laird pooling drops in as `def pool(result: dict) -> dict` post-processor next to the compute code, not scattered across the dispatcher
- **Test realism**: panel path is the production shape; per-method tests exercise real code path

**Shared primitive** (Phase 2 new module): `analysis-methods/subgroup_common/loaders.py` — `load_assignments(manifest_id) -> DataFrame` reads the tall parquet from the resolver product and returns a normalized DataFrame that methods filter against. Cached with `functools.lru_cache`.

## What's out of iter-1

- **CMS1-4 classifier work** — TCGA marker-paper CMS labels are ingested (Layer 1) but no derived per-sample assignment. iter-2 pending Ellrott / Sadanandam-adapted classifier per `iter1b-executive-summary.md:122`
- **Cross-indication meta-analysis (DerSimonian-Laird / heterogeneity)** — Phase 5b. Panel mode in iter-1 shows per-indication signals + convergence table, no pooled point-estimate
- **Immune-defined subtypes (Thorsson C1-C6)** — Ingested (`gdc-pancanatlas-immune-2018`) but requires `extrinsic` biology axis + microenvironment cards
- **Modality-context awareness** (avidity-gated bispecifics) — modality-fit stays context-blind iter-1
- **CML** — deferred to iter-1b per Phase 0a
- **LCC (large-cell lung), SCLC patient cohorts, KMT2A-rearranged AML, MRD-defined heme strata, germline BRCA in PDAC** — all deferred per per-panel spec details
- **RWD line-of-therapy** — composite iDAS strata that require LOT (all draft "requires sign-off" entries) resolve against Tempus/Flatiron RWD in Phase 2; TCGA-only analyses default to indication-level in the meantime
- **Chromosome-arm CN biomarkers** (3p loss, 17p loss, 8q gain, etc.) — the four existing `derivation_source` enum values (directly_tagged_clinical, directly_tagged_source_provided, maf_filter_per_rule, classifier_run) don't naturally cover arm-level copy-number ratios. iter-2 addition: extend enum with `arm_cn_ratio` + build `subgroup_assigner_cn` method reading DepMap `OmicsCNGene.csv` + TCGA CN products with a per-arm aggregator (analog of the ad-hoc `compute_arm_cn_ratio(chr3, arm=p)` pattern in `project_nedd8_3ploss_hypothesis.md`). Enables VHL-intact-squamous-3p-loss style strata as first-class catalog entries.
- **Numeric threshold predicates in Modality A/B rules** (`clinical.age >= 65`, `sample.tmb_score >= 12`) — MAF-filter parser supports these for MAF fields; extending to clinical/sample fields is a small parser change but not iter-1.
- **Runtime-constructed / ad-hoc bespoke strata** — decision LOCKED iter-1: all strata must be catalog-registered. No ephemeral-catalog or in-memory rule-passing API. Preserves governance + subgroup-n discipline uniformly across all queries. Users who need a bespoke stratum author it via a follow-up catalog PR (e.g., `subgroup-catalogs/COADREAD/2026-Q3.yaml` layered on top of 2026-Q2).

## Rigor discipline

Enforced at schema-level (Phase 4):

1. Rules firing on subtype-tier context REQUIRE `subtype_defining_data: {genomic|expression|immune}`, `subgroup_n: int`, `subgroup_n_floor_met: bool`. Validator error, not warning
2. `signal_channel_id` enum enforced at rule-schema level; rules cannot emit into un-declared channels
3. Signal-absence enum extended to `[supportive, opposing, killer, neutral, insufficient, not_applicable]`; rules declare emitted values in `emits: [...]`
4. Extrapolation discipline (cell-line → tumor, pan-cancer → indication, RNA → protein): rules that make cross-modal claims flag them; synthesis renders as "hypothesis-generating" not equal-weight

## Verification plan

Per phase:

- **Phase 0** (this pass): heme survey lands (done); 5 strata specs land (done); master design doc lands (this file); 3 agent perspectives added; user sign-off before Phase 1
- **Phase 1**: `validate-catalog` passes for 5 subgroup catalogs; `indication_crosswalk.yaml` validates against companion schema; spot-check `dge_deseq2 --indication COAD` still produces same output vs the new crosswalk
- **Phase 2**: End-to-end `subgroup_assigner_directly_tagged` against COADREAD-2026-Q2 emits real parquet; MSI_H stratum has ~60 TCGA COADREAD patients (matches literature); DepMap Colorectal MSI lines HCT116/DLD1/RKO/LoVo appear in MSI stratum
- **Phase 3**: `dge_deseq2 --target KRAS --indication COADREAD --subtype MSI_H` produces different result from `--subtype MSS` (filter took effect)
- **Phase 4**: Existing 96+ rules validate under new schema (backward-compat); new subtype-tier rule fails validation without subgroup-metadata (enforcement works); Pass 1 PR #6 rules re-validate under new channel enum
- **Phase 5**: E2E `target-profile(target="KRAS", scope=Scope(panel="GI", subtypes=["MSI_H"]))` produces artifact with mode-badge + subgroup-n floor visible; regression `target-profile("KRAS", "COADREAD")` byte-identical modulo `_prompt_hash`

## Cross-references

- Parent plan: `/home/sagemaker-user/.claude/plans/deep-foraging-thompson.md`
- Per-panel strata specs: `docs/design/idas-strata/{lung,pdac,gi,heme-aml,heme-cml}.md`
- CRC strata anchor: `/home/sagemaker-user/.claude/plans/you-are-a-skilled-drifting-pixel.md` lines ~1360-1700
- Iter-2 classifier deferral: `/home/sagemaker-user/.claude/plans/iter1b-executive-summary.md` line 122
- Existing card that already emits subgroup-stratified evidence: `cards/subgroup-stratified-expression.card.yaml`
- Existing schemas that Phase 2 outputs conform to: `schemas/subgroup_catalog.schema.json`, `schemas/subgroup_assignment.schema.json`
- Modality-first Pass 1 that established the categorical → signal pattern: PR #6 (`chore/protein-modality-rules-pass1`)
