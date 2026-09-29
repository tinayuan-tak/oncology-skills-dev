# iDAS Strata Spec — Heme-AML (Acute Myeloid Leukemia)

## Panel identity

| Field | Value |
|---|---|
| Panel canonical code | `Heme-AML` |
| Member indication | AML |
| TCGA cohort mapping | TCGA-LAML (single cohort, ~200 patients) |
| Adjunct patient cohorts | BeatAML1.0-COHORT (~501 adults), TARGET-AML (~1000 pediatric), TARGET-ALL-P2/P3 (ALL) |
| GENIE coverage | `Leukemia` case-list, `Myeloid_Neoplasms_with_Germ_Line_Predisposition`; panels `PROV-AMLC`, `VICC-01-MYELOID` |
| DepMap lineage | `Myeloid` (part of DepMap Blood/Lymphoid subtree — ~8 Myeloid cell lines per personal-notes synleth v2 memory) |
| CPTAC coverage | **AML drug-resistance cell-line studies only** — Gilteritinib Resistance / TimeCourse, Quizartinib Resistance (NOT patient-cohort proteomics) |
| GTEx normal | `Whole Blood` (functional matched-normal; not a matched-adjacent) |
| Adjacent-normal manifest | **None** — AML has no matched-adjacent-normal concept |

## iter-1 scope

- **7 atomic strata**: 5 mutation strata (FLT3-ITD, NPM1, IDH1, IDH2, TP53) + 1 fusion stratum (CBF-AML) + 1 cytogenetic-risk stratum (adverse cyto)
- **Data readiness gaps**: CBF-AML fusion calls (surmountable at derived-manifest level); cytogenetic-risk annotation manifest (surmountable via TCGA-LAML clinical + BeatAML supplement ingestion)
- **Composite iDAS strata**: age × cyto-risk × relapsed/refractory — drafted speculatively, **requires clinical-lead sign-off**
- **Deferred to iter-2**: KMT2A-rearranged (all rearrangement partners); RUNX1 germline predisposition; measurable residual disease (MRD) strata; APL (PML-RARA, treated distinctly)

## Atomic strata

| stratum_id | derivation_source | data_source_of_record | expected_n_patient (TCGA-LAML + BeatAML) | expected_n_depmap (Myeloid) | literature_anchor_pmid | iter1_status |
|---|---|---|---|---|---|---|
| `FLT3_ITD` | `maf_filter_per_rule` (ITD-aware) | TCGA-LAML MAF + BeatAML MAF; **ITD requires length-insertion-aware caller — standard MC3 may under-call** | ~50 (TCGA) + ~130 (BeatAML) | ~1 (MV4-11 canonical); MOLM-13, MOLM-14 also FLT3-ITD | 15374970 (Bacher review); 34547095 (BeatAML) | live (with ITD-caller caveat) |
| `NPM1_mut` | `maf_filter_per_rule` (exon-12 hotspots) | TCGA-LAML + BeatAML MAF | ~50 (TCGA) + ~150 (BeatAML) | ~1 (OCI-AML3) | 15659725 (Falini) | live |
| `IDH1_mut` (R132) | `maf_filter_per_rule` | TCGA + BeatAML MAF | ~15 (TCGA) + ~40 (BeatAML) | ~2 | 20393096 (Marcucci) | live |
| `IDH2_mut` (R140, R172) | `maf_filter_per_rule` | same | ~15 (TCGA) + ~50 (BeatAML) | ~2 | 20393096 | live |
| `TP53_mut` | `maf_filter_per_rule` | same | ~15 (TCGA) + ~50 (BeatAML); enriched in tAML/sAML | ~3 | 27305732 (Papaemmanuil) | live |
| `CBF-AML` (RUNX1-RUNX1T1 OR CBFB-MYH11 fusion) | `directly_tagged_source_provided` OR `classifier_run` (fusion caller on TCGA RNA) | **No derived fusion manifest today** — needs Phase-2 derivation from TCGA-LAML STAR-Counts + fusion caller | ~30 (~10% of TCGA-LAML) | ~2 (Kasumi-1 canonical) | 12384520 (Marcucci) | deferred (needs Phase-2 fusion derivation) |
| `adverse_cytogenetics` (complex karyotype, -5/-7, inv(3), etc.) | `directly_tagged_clinical` | **TCGA-LAML clinical supplement + BeatAML clinical** — not surfaced as catalog manifest today | ~40 (TCGA) + ~100 (BeatAML) | ~5 (varies) | 22417203 (Dohner) | deferred (needs Phase-1 clinical-annotation ingestion) |

## Composite iDAS strata (DRAFT — requires clinical-lead sign-off)

| iDAS composite | Constituent atomic strata | Rationale | iter1_status |
|---|---|---|---|
| `FLT3-ITD_1L_intensive` | `FLT3_ITD` × 1L × intensive-chemo-eligible | midostaurin + gilteritinib maintenance paradigm; RATIFY | draft — requires sign-off |
| `FLT3-ITD_relapsed-refractory` | `FLT3_ITD` × R/R | gilteritinib post-relapse label; ADMIRAL; also CPTAC AML resistance proteomics land here | draft — requires sign-off |
| `IDH-mut_R/R` | `IDH1_mut ∪ IDH2_mut` × R/R | enasidenib (IDH2) + ivosidenib (IDH1) approved; distinct from 1L intensive | draft — requires sign-off |
| `TP53-mut_venetoclax-refractory` | `TP53_mut` × venetoclax+aza-refractory | TP53-mut is worst-prognosis AML; unmet need | draft — requires sign-off |
| `NPM1-mut_FLT3-WT_favorable` | `NPM1_mut` × FLT3-WT × 1L | favorable-risk cohort under ELN guidelines; supports observation/stratification decisions | draft — requires sign-off |
| `adverse-cyto_elderly_azacit-based` | `adverse_cytogenetics` × age≥75 × ven+aza | dominant elderly AML treatment paradigm | draft — requires adverse-cyto ingestion + sign-off |
| `Secondary-AML` (tAML/sAML) | prior-MDS OR prior-chemo × TP53-mut-enriched | distinct biology, distinct outcomes | draft — requires clinical annotation |

## Line-of-therapy definition

LOT axis in heme is different from solid:
- **1L intensive**: 7+3 induction (daunorubicin + cytarabine) for fit patients
- **1L non-intensive**: ven+aza / ven+dec for unfit / elderly
- **Maintenance**: post-consolidation (midostaurin, oral azacit CC-486, gilteritinib in some contexts)
- **R/R (relapsed/refractory)**: post-induction-failure or post-relapse

RWD source for AML LOT: **not currently in catalog**. Tempus / Flatiron heme datasets would be Phase-1 ingestion candidates. Placeholder: composite LOT strata resolve at Phase 2 against a to-be-ingested heme RWD source.

## Subgroup-n floor discipline

Same rule (subgroup_n ≥ 30 for adjusted claim). Notes:
- **TCGA-LAML alone** puts several strata below floor (IDH1: n≈15, IDH2: n≈15, TP53: n≈15). **BeatAML boost is essential** to clear floors.
- **CBF-AML at ~10% of AML** is ~20 patients on TCGA-LAML — insufficient alone; combined with BeatAML clears floor.
- **DepMap Myeloid lineage** (~8 cell lines total per synleth memory) is fundamentally below any reasonable floor for cell-line-only strata. AML iter-1 is inherently patient-side-primary; DepMap acts as mechanistic validator, not as an evidence source per stratum.

## Deferred to iter-2

- **CBF-AML derived fusion manifest** — pull TCGA-LAML RNA-seq, run fusion caller (Arriba / STAR-Fusion), emit fusion parquet. Phase-2 or later; iter-1 CBF-AML flagged as `deferred`
- **Cytogenetic-risk annotation manifest** — ingest TCGA-LAML clinical cytogenetic karyotype supplement + BeatAML risk-annotation. Phase-1 net-new ingestion
- **APL (PML-RARA)** — clinically treated as distinct disease (ATRA + ATO); typically excluded from "AML" analyses. Not in iter-1 spec
- **KMT2A-rearranged AML** — spans many rearrangement partners (KMT2A-AF9, KMT2A-AF10, etc.). Deferred to iter-2 with fusion-derivation
- **MRD-defined strata** — measurable residual disease positive vs negative post-consolidation. Requires longitudinal RWD source
- **Germline predisposition** (RUNX1-GATA2-DDX41 etc.) — germline data not in TCGA catalog; deferred
- **Pediatric-AML strata** (TARGET-AML) — different biology (KMT2A-MLL, NUP98-NSD1); TARGET-AML MAFs are in catalog but not stratified

## Open questions

1. **ITD-caller for FLT3_ITD** — MC3 caller is Mutect2-based; ITD detection may be poor. Should Phase-2 add a dedicated ITD-aware fusion / structural caller?
2. **BeatAML expression data** — currently only MAFs are in the catalog for BeatAML. Should Phase-1 add BeatAML RNA-seq if available on GDC?
3. **CPTAC AML proteomics** — the FLT3-inhibitor-resistance cell-line proteomes are useful for FLT3-R/R composite strata but are **cell-line studies**, not patient-cohort. Should they be flagged as such in the crosswalk (`cptac_cohort: FLT3-resistance-cell-line-only`)?
4. **Adverse-cyto ingestion path** — TCGA-LAML has cytogenetic annotations in the clinical supplement (`gdc-pancanatlas-clinical-2018` per data-catalog survey). Is that manifest accessible for cytogenetic-risk derivation, or does it need re-ingestion?

## AML-specific reviewer notes

AML reviewers reading a target profile need to see:
- **ELN-2022 risk-group summary** (favorable / intermediate / adverse) as a top-of-page — because that's how clinicians actually think
- **Fit-vs-unfit** patient stratification as a first-order LOT axis (this is different from solid tumors)
- **DepMap cell-line n is inherently low** — extrapolation from ~8 Myeloid cell lines to patient AML biology is a rigor risk

The extrapolation-discipline agent's concern (cell-line lineage ≠ patient biology) is more acute for AML than for any solid tumor. iter-1 AML rules should default cell-line evidence to "hypothesis-generating, requires patient-cohort confirmation" unless BeatAML/TCGA-LAML corroborates.
