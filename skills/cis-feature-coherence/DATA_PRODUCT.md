# cis-feature-coherence — finalized data product

The **I/O contract**: data wired IN, package emitted OUT, what is locked. Coherence logic + history live
in SKILL.md / run.py; this file is the data-product spec.

| | |
|---|---|
| **Skill** | `cis-feature-coherence` · v1.4.0 |
| **Contract version** | 1.0.0 (emitted-output schema; versioned independently — see §4) |
| **Role** | `inert` — verdict-shaped but explicitly NOT a call (gateless; dedicated `cis_coherence` axis, not in the gating axes); `polarity: not_scored` |
| **Verdict field** | `headline.cis_coherence_verdict` (a locus→expression→dependency coherence CLASS; `skill_report.call` carries this inert string, by contract not a nomination call) |
| **Output shape** | `data_package` |
| **Emitted schema** | `target-contracts/schemas/skills/cis-feature-coherence.decision.schema.json` (generated, self-contained) |
| **Conformance target** | a FROZEN FULL emit `fixtures/cis_full_emit.json` (real KRAS·COADREAD run → `coherent_cis_driver`, role=inert) — no replay harness |

---

## 1. Inputs — wired data (8 cards)

Every card traces card → method → data-catalog manifest → materialized S3 product. **All 8 products LIVE.**
`run.py` has no `CARD_CONTEXT` map.

**Verdict-driving (4 → `cis_coherence.resolver.yaml`):** `cis-feature-expression-coherence` (leg-1 CN→RNA
dosage; `depmap-consortium-26q1`), `cellline-methylation-expression-coherence` (LoF epigenetic silencing;
CCLE-2019 RRBS), `expression-dependency-correlation` (leg-2 RNA→dep), `amp-expr-stratified-dependency` (leg-2 conjoint).

**Inert display (4):** `cis-feature-protein-coherence` (Gygi), `abundance-dependency` (Gygi/Olink),
`patient-cis-coherence` (TCGA CN+meth+TPM crosswalk), `cellline-isoform-expression`
(→ `depmap-isoform-expression-per-gene-v1`).

---

## 2. Coverage & capability ceilings (contractual)

- **Patient methylation** (`tcga-sesame-promoter-methylation-v1`) covers 6 cohorts (LUAD/LUSC/HNSC/PAAD/STAD/ESCA)
  — **no COADREAD** → the patient silencing leg returns `insufficient` there.
- **Cell-line legs are `pan_no_indication`** (decoupled from indication by design).
- Isoform product maps ~83% of DepMap ENST columns to GENCODE-v26 genes; crosswalk attrition ~88% CN / 95% meth / 98% MC3.

---

## 3. Emitted output

`output_shape: data_package` → the standard `write_package` tree. `decision.json` top-level:
`skill · target · indication · question · generated_at · headline · cards · fired_rules · provenance ·
run_health` (+ optional synthesis). Contractual headline fields: `cis_coherence_verdict` (pinned 6-value
enum), the `skill_report` spine (`role: inert`, `polarity: not_scored`, `call` = the inert
`cis_coherence_verdict` string), `headline_block`, `claim_vector`, `key_signals`. All else schema-open.

---

## 4. Contract & versioning (what is locked)

Pinned by the generated, self-contained `cis-feature-coherence.decision.schema.json` (inert-scalar pins:
`role: inert` + `polarity: not_scored` const + the 6-value `cis_coherence_verdict`/`call` enum =
`cis_coherence.resolver.yaml` = `_CIS_COHERENCE_VERDICT_PHRASE`; no run.py mints). CI: full-emit conformance
(`tests/test_data_product_schema.py` against the frozen full golden, CI-fail-not-skip), cross-skill coverage
ratchet, target-contracts schema meta-test. Change policy: new verdict token → pins enum + regenerate (minor);
spine key → SHARED source (coordinate; major on rename); new facet → no schema change.

## 5. Known gaps & notes (non-blocking)

- **CN matrix — WGS-primary (migrated #598/#704 6a, 2026-09-11):** the CN-consuming cards (#1 cis-dosage,
  #2 cis-protein-dosage, #6 amp-expr) now read the DepMap-CANONICAL `OmicsCNGeneWGS` matrix as primary via
  `depmap_cn_distribution.load_cn_files` (legacy `OmicsCNGeneMC_WES` is fallback-only for genes absent from
  WGS). Same relative-CN scale; focal-amp thresholds carry over unchanged.
- **cis-dosage focal-amplification subset escape (2026-09-12):** the pan-panel Spearman dilutes focal-amp
  oncogenes (ERBB2 r=0.23) below the moderate gate; the method now PROMOTES an uncoupled call to coupled
  when the amplified subset over-expresses strongly + significantly (`cis_dosage_driver=focal_amplification_subset`).
  Paired with methylation `MIN_HYPERMETHYLATED` 10→20 (power floor). Fixes the ERBB2/MET-class silencing-override.
- **Stale source:** CCLE-2019 RRBS methylation is 2018-era hg19, name-keyed (cross-build) to hg38/26q1 expression.
- **Undeclared derived input:** `cellline-methylation-expression-coherence`'s reader uses derived
  `ccle-rrbs-promoter-methylation-mean-per-gene-v1` as primary, but the card `required_inputs` names only the
  source `depmap-consortium-ccle-2019` (lineage consistent; card understates wiring).
- **Protein product-id inconsistency:** #2 declares derived `depmap-gygi-protein-abundance-per-protein-v1`; #5
  declares source `depmap-consortium-26q1-proteomics` (same Gygi data) — granularity-convention mismatch.
