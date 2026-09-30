# Subgroup Panorama Playbook

**Status:** CRC (COADREAD) reference partially built (2026-07-15). This doc is the
persistent template for extending the *descriptive subgroup panorama* across all
iDAS indications. Companion to `IDAS_SUBTYPE_PIPELINE.md` (the full four-layer
design) and `SAMPLE_ANNOTATION_PLAN.md` (per-stratum annotation modalities).

---

## What a panorama is (and is not)

A **subgroup panorama** enumerates a target's evidence across the strata of one
axis (MSI/MSS, sidedness, KRAS-mut, line-of-therapy, …) so a human can *see the
landscape*: where a target is mutated / expressed / depended-on, and — equally
important — where it is **not**.

- **DESCRIPTIVE, not verdict-affecting.** A panorama informs via
  `interpretation_hints` / render; it does NOT emit `signals:` and does NOT
  change the target verdict. No synthesis-engine changes. (Verdict-affecting
  subtype rules via `in_record` are a deliberate, separate future step.)
- **Positive AND negative are both valuable.** "KRAS is a dependency in MSS but
  not MSI-H" is a selection signal. The panorama enumerates EVERY stratum row,
  never filters to hits.
- **Trusted-negative ≠ unknown.** Every record carries `evidence_state`:
  - `measured` — subgroup_n ≥ floor (30); the metric is trustworthy, whether the
    finding is positive OR a real negative.
  - `underpowered` — evaluated but below floor; treat as unknown.
  - `absent` — no samples in this stratum ∩ the method cohort.

## The two-filter card-selection rule

A card is worth subtyping only if **BOTH**:
1. **Biology genuinely varies by subgroup** (author attestation; PR-reviewed).
2. **Data grain supports honest per-stratum recomputation** (mechanically
   checkable — the method must read a PER-SAMPLE substrate it can re-filter, not
   a product with aggregates baked at emit time).

**Target-intrinsic cards NEVER stratify** (`tier: target` — identity,
tractability, precedent do not change by tumor subtype; stratifying them is noise).

## The "one shape, four layers" invariant

A tall `(sample, stratum, is_member)` row propagates upward unchanged in shape:
1. **catalog** (`data-catalog/subgroup-catalogs/{IND}/{quarter}.yaml`) declares
   atomic_strata.
2. **assigner** emits `assignments.parquet` (tall; `is_member ∈ {True/False/None}`).
3. **method reader** (`read_stratified_*`, `@subgroup_iterable`) groups its
   per-sample data by member-set → `{stratum: record}`.
4. **card** emits list-typed `per_subgroup_metrics` (declared in the card's
   `summary_fields_record_schemas`).

## Reference implementation (built 2026-07-15, analysis-methods PR #32 + follow-on)

- **`onc_methods/subgroup_common/panorama.py`** — the substrate-agnostic composer.
  `build_panorama(reader, *, record_projection, reducer, …)` fans a reader across
  strata, projects per-card, reduces to cross-stratum scalars. Shared rigor
  primitives `SUBGROUP_N_FLOOR=30` + `evidence_state()` live here (single source
  of truth). Named reducers: `delta_reducer(metric_key, label)`.
- **`onc_methods/subgroup_common/scoping.py`** — `compute_join_coverage()` guards the
  member-set↔data join: warns on the near-zero-match signature of a sample-id
  convention mismatch (patient-barcode assignments vs full-aliquot method data),
  which otherwise silently looks like an empty stratum.
- **Two substrates prove agnosticism:**
  - `gdc_somatic_hotspot/read.py :: read_stratified_mutation_frequency` +
    `build_mutation_frequency_panorama` (per-sample MAF; `maf_source`-parameterized
    for TCGA-MC3 molecular strata AND GENIE-registry LOT strata).
  - `depmap_chronos/read.py :: read_stratified_dependency` +
    `build_dependency_panorama` (per-ModelID Chronos matrix).

### The reader protocol (copy this)
```
@subgroup_iterable
def read_stratified_{substrate}(target, indication, *, _sample_id_filter=None,
                                **substrate_args) -> dict:
    # read the PER-SAMPLE substrate; intersect index with _sample_id_filter;
    # compute the metric WITHIN the member-set denominator (recompute, not slice).
    # return {subgroup_n, subgroup_n_floor_met, evidence_state, source_cohort, <metrics>}
```
Then a ~15-line `build_{substrate}_panorama` = a `build_panorama` call with a
projection dict + a named reducer.

### Validated CRC biology (real data, descriptive)

**Admissibility rule:** underpowered strata (below `SUBGROUP_N_FLOOR=30`) are
INADMISSIBLE in comparative prose. They appear in per-stratum panorama tables
tagged `underpowered`, but the narrator cannot compare them to admissible strata.
Comparisons here run only within measured strata (n≥30) or against floor-cleared
whole-cohort baselines. This is what prevents the panorama's descriptive
findings from producing quantitative claims on unknown data.

- **Mutation frequency (admissible strata only):** Right-sided KRAS 49% (n=80)
  vs left-sided 33% (n=119) — the literature-consistent sidedness gradient. MSS
  40% (n=151) slightly above the pan-COAD baseline of 37.5% (n=208). G12C rare
  within MSS at 4% — a framing insight versus its NSCLC prominence rather than
  a verdict-modifier. Flat across line-of-therapy in GENIE-BPC (45/45/45 for
  LOT_1L_only/LOT_2L/LOT_3Lplus, all measured n≥198) — a trusted negative:
  KRAS-mut prevalence does not enrich in later-line CRC.
- **Dependency (Chronos, Bowel, admissible strata only):** MSS median −1.22
  (n=71, measured) — stronger than the whole-cohort Bowel call of −0.94 (n=88,
  measured). The MSS-scoped dependency is the load-bearing subtype-scoped
  signal; whole-cohort Bowel alone would rate KRAS "moderate" and miss the
  subtype divergence.
- **INADMISSIBLE and not compared:** MSI-H mutation frequency (n=24 < 30) and
  MSI-H dependency (n=17 < 30). These strata appear in the per-stratum panorama
  tables tagged `underpowered`, but no comparative claim can be made. MSI-H is
  UNKNOWN for these axes, not a confirmed negative. Larger MSI-H-specific
  cohorts are the prerequisite for evaluating KRAS's MSI-H story.

Two substrates AGREE on the admissible finding: MSS carries slightly higher
KRAS mutation prevalence (40% vs 37.5% pan-COAD) AND materially stronger
dependency (−1.22 vs −0.94 whole-cohort Bowel). This convergence is a
subtype-scoped divergence from the whole-cohort call — not a claim that MSS
"beats" MSI-H (which we cannot say from underpowered data) — worth surfacing
to human review.

## Per-indication recipe (to extend beyond CRC)
1. Author/extend the subgroup catalog (`subgroup-catalogs/{IND}/{quarter}.yaml`).
2. Emit assignments shards per source (directly_tagged / maf_filter / classifier).
   **DepMap shards must be lineage-scoped** (assigner `INDICATION_TO_DEPMAP_LINEAGE`).
3. Bind the card to a per-sample `read_stratified_*` (never an aggregate reader).
4. (Future) regenerate the coverage matrix; confirm validators green.

## Readiness tiers (2026-07-15 survey)
- **4-card (full):** COADREAD — all substrates (MAF, Chronos, recount3 expr, BPC-LOT).
- **3-card (LOT-blocked):** NSCLC, HNSC, STAD, ESCA, PAAD — MAF+Chronos+expr ready.
- **2-card:** AML — no bulk tumor expression (recount3 lacks LAML), no LOT.
- **1-card (cell-line only):** SCLC — DepMap Chronos + NAPY; no TCGA cohort.

## Remaining spine gaps (NOT yet built — required before S3 publish / rollout)
These are the "make it trustworthy across indications" items, deferred to a
dedicated session (user 2026-07-15 "pause + consolidate"):

1. **Catalog content-pin.** COADREAD/2026-Q2 was edited in place 5× (6→18 strata)
   under one version label; `evaluated_at_release` is non-diagnostic. Stamp a
   content hash of the resolved catalog into each assignments manifest (or move to
   immutable version labels). Locally-emitted assignments are ALREADY stale (11
   strata, pre-LOT) — re-emit after this lands.
2. **Schema-valid assignment manifest + S3 path.** The assigner emits
   `manifest_kind: subgroup_assignment` — invalid against BOTH the
   `subgroup_assignment_product` schema AND the data-catalog `derived` schema.
   Reconcile to `s3://onc-compbio/data-catalog/derived/subgroup-assignments/{ind}/{src}/{pin}/`.
3. **Coverage matrix + validator gates.** Derive (never hand-author) a
   `coverage/{IND}.coverage.yaml` (status ∈ live/data_blocked/below_floor/out_of_scope)
   from catalogs + cards + emitted assignments; CI-lock it. Add card validators:
   **grain-check** (refuse `stratify_by` on aggregate-substrate readers — catches
   the EXISTING `subgroup-stratified-expression.card.yaml` trap, which is bound to
   the aggregate `read_dge_gene_row`), **tier-check** (target-tier never stratifies),
   **stratification attestation** block.
4. **Card `summary_fields_record_schemas`** populated for the panorama cards +
   render contract (per-subgroup table visually distinguishing measured /
   underpowered / absent) + verify overall verdict byte-identical (descriptive-only).

## Known open risks (from multi-agent review 2026-07-15)
- **Emit-time-vs-read-time recompute trap (highest).** Most method readers bake
  aggregates at emit time and cannot honestly recompute per stratum. Only
  per-sample readers may stratify. The grain-validator (gap 3) enforces this;
  `subgroup-stratified-expression.card.yaml` is already in the trap and must be
  fixed (needs a per-sample DGE reader) or marked not-live.
- **Cross-source membership fragmentation.** "MSI-H" = TCGA-clinical-MSI for the
  mutation card but DepMap-inferred-MSI for the dependency card — different sample
  universes. Never merge strata across `source_cohort`; the field is mandatory on
  every record for exactly this reason.
- **n-floor per-substrate.** 30 may be right for tumor cohorts but high for
  cell-line dependency (Bowel MSI-H = only ~30 lines total). Consider a
  per-substrate floor when rollout hits cell-line-thin indications.
