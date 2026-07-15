# iDAS Strata Specifications

This directory holds per-iDAS strata design specifications. Each `{indication}.md`
document scopes the atomic strata (single-axis substratifications) and composite
iDAS cohorts (multi-axis strata that map to Takeda's iDAS "whitespace" reasoning)
for one iDAS indication.

**Every iDAS = one indication** (per user 2026-07-14 direction). Strategic
groupings ("Thoracic", "GI-upper", "Heme") are metadata annotations on each
indication, not iDAS entities themselves. See `docs/design/IDAS_SUBTYPE_PIPELINE.md`
for the Scope contract that consumes indication lists + strategic buckets.

These specs are **design inputs** to the Phase 1 subgroup catalogs
(`data-catalog/subgroup-catalogs/{indication}/{quarter}.yaml`). They are NOT
executable artifacts.

## iDAS indication coverage

| iDAS | Display name | Strategic bucket | Spec | iter-1 status |
|---|---|---|---|---|
| COADREAD | CRC | (standalone) | (`.claude/plans/you-are-a-skilled-drifting-pixel.md` anchor) | Live |
| NSCLC | NSCLC | Thoracic | [nsclc.md](nsclc.md) | Live |
| SCLC | SCLC | Thoracic | [sclc.md](sclc.md) | Live (cell-line-only; patient cohort ingestion deferred) |
| HNSC | Head & Neck Cancer | Thoracic | [hnsc.md](hnsc.md) | Live |
| STAD | Gastric | GI-upper | [stad.md](stad.md) | Live |
| ESCA | Esophageal | GI-upper | [esca.md](esca.md) | Live |
| PAAD | PDAC | GI-upper | [paad.md](paad.md) | Live |
| AML | AML | Heme | [aml.md](aml.md) | Live |
| CML | CML | Heme | [cml.md](cml.md) | **iter-1b deferred** (design note only) |

## Spec structure (each `{indication}.md` follows this template)

1. **Panel identity** — canonical code, display name, strategic bucket, TCGA-cohort mapping
2. **iter-1 scope** — one-line summary of what's in vs deferred
3. **Atomic strata** — table with columns:
   - `stratum_id` (kebab-case)
   - `derivation_source` (enum from subgroup_catalog.schema.json)
   - `data_source_of_record` (which manifest supplies the label)
   - `expected_n_patient_cohort` (rough sample count per source)
   - `expected_n_depmap` (cell-line count)
   - `literature_anchor_pmid`
   - `iter1_status` (`live` / `deferred` / `requires-clinical-lead-signoff`)
4. **Composite iDAS cohorts** — Takeda-strategy strata (multi-axis conjunctions), all marked draft pending clinical-lead sign-off unless anchored in an existing Takeda spec
5. **Cross-iDAS notes** — where the indication's biology overlaps with another iDAS (e.g. HNSC-SCC ↔ ESCC ↔ LUSC squamous)
6. **Subgroup-n floor discipline** — per-stratum minimum n for a rule to fire
7. **Deferred to iter-2** — classifier work, missing sources, novel cohorts
8. **Open questions** — items requiring stakeholder input before Phase 1

## Strategic buckets vocabulary (Phase 1 landing)

Not enumerated in this design directory — will land as
`target-contracts/vocabularies/idas_strategic_buckets.yaml` in Phase 1. Current
straw content:

```yaml
Thoracic:  [NSCLC, SCLC, HNSC]
GI-upper:  [STAD, ESCA, PAAD]
GI-lower:  [COADREAD]
Heme:      [AML, CML]
```

Strategic-bucket queries resolve to indication lists at invocation time. Users
never query the framework with `bucket=X`; they query with
`indications=[bucket_resolved_list]`.

## Cross-iDAS aggregation (Phase 5 synthesis-layer concern)

Some biology genuinely spans multiple iDAS entries:
- **Squamous** — HNSC-SCC, ESCC, LUSC share aerodigestive squamous mutation
  landscape (TP53, NOTCH1, PIK3CA-helical, SOX2/TP63)
- **HER2+ upper-GI** — STAD-HER2-amp + EAC-HER2-amp cross-iDAS
- **MSI-H pan-tumor** — checkpoint-inhibitor eligibility spans indications
  (COADREAD, STAD, endometrial-not-iter-1)

These are NOT re-encoded as strata within any single iDAS spec. They live at the
synthesis layer and produce cross-iDAS convergence signals when a target query
runs across multiple indications. See parent design's channel-precedence:
`indication_fit_panel` handles this at the rules layer.

## Sample annotation planning

**Every stratum in these specs needs a concrete annotation path** — the algorithm
that takes raw source data and emits a per-sample `(sample_id, stratum_id, is_member)`
row in the resolver product. See [SAMPLE_ANNOTATION_PLAN.md](../SAMPLE_ANNOTATION_PLAN.md)
(Phase 0e) for the per-stratum × per-source annotation-method mapping.
