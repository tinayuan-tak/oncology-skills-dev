# genomic-alteration-profile — finalized data product

The **I/O contract**: data wired IN, package emitted OUT, what is locked. Multi-class verdict logic +
history live in SKILL.md / run.py; this file is the data-product spec.

| | |
|---|---|
| **Skill** | `genomic-alteration-profile` |
| **Skill code version** | 2.17.0 |
| **Contract version** | 1.0.0 (emitted-output schema; versioned independently — see §4) |
| **Role** | `gating` (verdict moves the nomination; polarity dynamic — positive driver / negative passenger / neutral) |
| **Verdict field** | `headline.genomic_alteration_profile` (scalar, reconciled) + `genomic_alteration_by_class` {snv_indel, copy_number, fusion, splice} + `genomic_alteration_by_scope` {pan_cancer, indication, subtype} |
| **Output shape** | `data_package` |
| **Emitted schema** | `target-contracts/schemas/skills/genomic-alteration-profile.decision.schema.json` (generated, self-contained) |
| **Conformance target** | the FRESH replay emit (`test_genomic_replay.py`; KRAS/BRAF → `biomarker_stratified_dependency`); static `kras_coadread_decision.json` golden is **trimmed** → not a full-decision target |

> **Emitter note (fixed here):** this skill hand-rolls `main()` (not `run_wired_skill`). Its emitter now
> builds the envelope-required top-level `run_health` + `provenance` (`build_subskill_provenance` +
> `skills_repo_sha`), so the emitted `decision.json` is a full envelope. Previously both were absent —
> the emitter bug the data-product lock surfaced.

---

## 1. Inputs — wired data (27 cards)

24 whole-cohort spine cards + 3 `--subtypes`-gated panorama cards. **All 27 products LIVE** (concrete
`md5`+`size`, or materialized source prefix); no placeholders, no stale refs, no stale-metadata. `run.py`
has no `CARD_CONTEXT` map. Full card→manifest→S3 table is in the wiring trace; grouped here by role:

**Verdict-driving, by alteration class (`genomic_alteration_by_class`):**
- **snv_indel** — `mutation-type-counts` (primary, `mutation_landscape_class`) + `mutation-hotspot-frequency`
  (recurrence; pooled `pooled-snv-recurrence-v1` = MC3⊕GENIE⊕MSK-CHORD) + `mutation-stratified-dependency`.
- **copy_number** — `copy-number-distribution` (cell-line + patient GISTIC `tcga-patient-cn-per-gene-v1`) +
  `copy-number-stratified-dependency` + `amp-expr-stratified-dependency`.
- **fusion** — `fusion-rearrangement-landscape` (`tcga-fusion-consensus-v1`, 3-caller consensus; GENIE-SV
  additive) + `fusion-stratified-dependency`.
- **splice** — `splice-exon-skip-landscape` (`depmap-somatic-splice-variants-v1`; curated exon-skip driver, METex14).
- **role/actionability** — `alteration-role` (OncoKB×IntOGen; GoF→`confirmed_driver`, LoF→`confirmed_lof_driver`),
  `mutation-drug-response` (PRISM-OncRef → `drug_response_biomarker`).

**Confidence annotations:** `cross-consortium-dependency`, `dependency-predictability`.
**Display-only signal layers (verdict-inert):** `mutation-hotspot-frequency` recurrence facet,
`variant-level-interpretation` (CIViC), `variant-effect-mave-mavedb`, `target-clonality`,
`functional-gene-state`, `genomic-event-model-match`, `tumor-splice-{dysregulation,expression}`, + 4
indication-level cohort-context facets (`genomic-instability-state`, `mutational-signature-context`,
`ddr-deficiency-context`, `oncogenic-pathway-alteration`).
**Subtype panorama (3, `--subtypes`-gated, verdict-inert):** `subgroup-stratified-{mutation-frequency,copy-number,fusion}`.

---

## 2. Coverage & capability ceilings (contractual)

- **SNV recurrence:** verdict fires on `pooled_driver_recurrence_class == top_1pct` (pooled MC3⊕GENIE⊕
  MSK-CHORD); MC3 = whole-exome, GENIE = panel-covered genes only (coverage-denominator, `data_unavailable`
  if panel-absent) — an inherent panel-intersect ceiling.
- **Fusion:** `tcga-fusion-consensus-v1` = pan-TCGA 3-caller consensus, **TCGA-tissue only** (no commercial
  catalog); amplicon-artifact SVs at amplified oncogenes (ERBB2/STAD) demoted via the v2.16.0 copy-number gate.
- **Splice:** surgical curated-driver ceiling — `splice_exon_skip_driver` only for a registered curated
  exon-skip event in its oncogenic indication (today MET in LUAD/LUSC/NSCLC) with live DepMap carriers.
- **CN:** cell-line `copy_number_class` = pan-cancer relative-CN; the verdict-bearing focal-vs-arm call is
  the merged patient GISTIC `patient_focal_cn_class`.
- **mutation-drug-response:** PRISM-OncRef pan-cell-line (NOT an indication-patient biomarker); only
  `mutant_strongly_drug_sensitive` fires.
- **Subtype panorama:** assignment shards **COADREAD-only** today; other indications → honest per-axis data-note.

---

## 3. Emitted output

`output_shape: data_package` → the standard `write_package` tree. `decision.json` top-level:
`skill · target · indication · question · generated_at · headline · cards · fired_rules · **provenance** ·
**run_health**` (+ optional synthesis). Contractual headline fields: `genomic_alteration_profile` (pinned
enum), `driving_rule_id`, `genomic_alteration_by_class`, `genomic_alteration_by_scope`, `scope_of_driving_verdict`,
the `skill_report` spine (`role: gating`, dynamic `polarity`, `call` = reconciled `genomic_alteration_profile`),
`headline_block`, `claim_vector` (SNV/CN/FUS/SPL/DEP), `key_signals`. All else schema-open. NOTE: the composed
target-profile GATE reads the RAW resolver ladder (`genomic_alteration_profile_ladder`), not the reconciled
scalar; both are in the pinned enum.

---

## 4. Contract & versioning (what is locked)

Pinned by the generated, self-contained `genomic-alteration-profile.decision.schema.json` (gating-scalar
pins: `role: gating` + the 19-value `genomic_alteration_profile`/`call` enum = `_GENOMIC_VERDICT_PHRASE`
(genomic_alteration resolver rungs + the reconciled `biomarker_dependency_unconfirmed`); no polarity const;
`genomic_alteration_by_class`/`_by_scope` typed-open).

CI: fresh-replay conformance (`test_genomic_replay.py`), schema-well-formedness + static-golden-if-full
(`tests/test_data_product_schema.py`, CI-fail-not-skip), cross-skill coverage ratchet, target-contracts
schema meta-test. Change policy: new verdict token → pins enum + regenerate (minor); spine key → SHARED
source (coordinate; major on rename); new facet → no schema change.

## 5. Known gaps & notes (non-blocking)

- **No stale-metadata bugs** (unlike other skills — genomic's cards are clean). Several verdict-driving
  cards are sub-1.0 versions (`splice-exon-skip-landscape` v0.1.0, `alteration-role`, `functional-gene-state`,
  …) yet fully wired + materialized — low version ≠ placeholder.
- **Logical aliases resolved at read time:** `gdc-pancohort-somatic` (→ `-dr45-0`, per-indication pushdown),
  `depmap-predictability` (→ `-26q1-v3` by release pin). Indication-scoped derived products carry an
  `indication` column filtered per-indication at read.
- **`provenance.resolved_releases`** may omit `is_stale` for indeterminate-head families (e.g.
  `gdc-pancohort-somatic`) — the envelope treats `is_stale` as optional for exactly this reason.
