# mechanism-and-pharmacology — finalized data product

The **I/O contract**: data wired IN, package emitted OUT, what is locked. MoA/network logic + history live
in SKILL.md / run.py; this file is the data-product spec.

| | |
|---|---|
| **Skill** | `mechanism-and-pharmacology` |
| **Skill code version** | 1.11.0 |
| **Contract version** | 1.0.0 (emitted-output schema; versioned independently — see §4) |
| **Role** | `gating` (verdict = a signaling-network **characterization** class; polarity STATICALLY neutral — annotation density is not target quality) |
| **Verdict field** | `headline.mechanism_verdict` (resolves on `network_class` alone; the has_pd_marker rung was removed as structurally dead, resolver v1.2.0) |
| **Output shape** | `data_package` |
| **Emitted schema** | `target-contracts/schemas/skills/mechanism-and-pharmacology.decision.schema.json` (generated, self-contained) |
| **Conformance target** | the FRESH replay emit (`test_mechanism_replay.py`; EGFR `well_characterized`, CEACAM5 `partial`); static `kras_coadread_decision.json` golden is **trimmed** → not a full-decision target |

---

## 1. Inputs — wired data (5 cards)

Every card traces card → method → data-catalog manifest → materialized S3 product. **All 5 products (+ all
composed lanes) are LIVE.** `run.py` has no `CARD_CONTEXT` map (mechanism is indication-agnostic / context-free).

| card_id | method / read path | catalog manifest(s) | role |
|---|---|---|---|
| `signaling-network-mechanism` | `mechanism_composed::read_target_summary` (SIGNOR lane reads the derived parquet first, TSV fallback) | `signor-jul2026` (src) + **`signor-mechanism-network-per-gene-v1`** (derived, primary read) + composed lanes `collectri-tf-regulon-per-gene-v1`, `reactome-pathway-per-uniprot-v1`, `kinome-atlas-long-edges-v1`, `depmap-coessentiality-26q1-v1` | **verdict-driving** (the only resolver card; keyed on `network_class`) |
| `tahoe-drug-perturbation` | `tahoe_drug_perturbation` | `tahoe-drug-perturbation-per-gene-v1` (~5.3 GB) | display-only |
| `phospho-pathway-activity` | `phospho_pathway_activity` (reads derived per-site) | `cptac-pdc-snapshot-2026-07-01` (src, declared) → reads `cptac-phospho-per-site-per-cohort-v1` (derived) | display-only |
| `pathway-activity-context` | `progeny_pathway_activity` (PROGENy) | `progeny-pathway-activity-per-indication-v1` | display-only |
| `dependency-predictability` | `depmap_predictability` (`depmap-predictability` alias → `-26q1-v4`) | `depmap-predictability-26q1-v4` | display-only |

**MoA composition (what feeds `network_class`):** SIGNOR (Jul2026) + CollecTRI curated-edge union **only**.
Reactome is layered as pathway **context** (not counted in the edge total).
Kinome-atlas predictions + DepMap co-essentiality are carried **alongside** (`kinome_atlas_predictions` /
`coessentiality_context`), **never merged** into `network_class`/`has_actionable_moa`. MoA ontology = 31-class (v1.0.0).

---

## 2. Coverage & capability ceilings (contractual)

- **SIGNOR** quarterly release `signor-jul2026` (Oct2026 will supersede); derived per-gene = 33,083 human
  rows → ~44,996 dual-emitted edges (~4.2% unmapped). **CollecTRI** = `collectri-tf-regulon-per-gene-v1`.
- **Phospho** ceiling = CPTAC 10-cohort set (`applies_when`). **PROGENy** = 33 indications × 14 pathways.
- **Predictability** = 26q1-v4, 9,240 genes, RF — **SHAP computed** (`shap_computed: true`;
  `top_features_rf_shap` carries mean(|SHAP|) TreeExplainer attributions.
  v4 re-materializes v3's exact gene set / model / CV with `shap` 0.52.0; the older v1/v2/v3 pins
  fell back to RF-impurity).

---

## 3. Emitted output

`output_shape: data_package` → the standard `write_package` tree. `decision.json` top-level:
`skill · target · indication · question · generated_at · headline · cards · fired_rules · provenance ·
run_health` (+ optional synthesis). Contractual headline fields: `mechanism_verdict` (pinned enum),
`driving_rule_id`, `network_class`, `has_actionable_moa`, the `skill_report` spine (`role: gating`,
dynamic `polarity`, `call` = `mechanism_verdict`), `headline_block`, `claim_vector`, `key_signals`. All else
schema-open (kinome/co-essentiality/phospho/PROGENy/tahoe facets + the confirmation/prediction-lane caveats).

---

## 4. Contract & versioning (what is locked)

Pinned by the generated, self-contained `mechanism-and-pharmacology.decision.schema.json` (gating-scalar
pins: `role: gating` + the 5-value `mechanism_verdict`/`call` enum
`well_characterized/partial/sparse/insufficient/data_unavailable` = the mechanism resolver
set (has_pd_marker removed as a dead rung, v1.2.0); no run.py mints; no polarity const; no bucket map).

CI: fresh-replay conformance (`test_mechanism_replay.py`), schema-well-formedness + static-golden-if-full
(`tests/test_data_product_schema.py`, CI-fail-not-skip), cross-skill coverage ratchet, target-contracts
schema meta-test. Change policy: new verdict token → pins enum + regenerate (minor); spine key → SHARED
source (coordinate; major on rename); new facet → no schema change.

## 5. Known gaps & notes (non-blocking)

- **`phospho-pathway-activity` declares the CPTAC source** as `required_inputs` but reads the derived
  `cptac-phospho-per-site-per-cohort-v1` — a provenance-declaration gap (both materialized; not broken).
- **`has_actionable_moa` / `has_pd_marker` are count-of-mapped-edge flags** (2026-09-12 method fix): True
  iff >=1 curated upstream (resp. downstream) edge carries a MAPPED MoA class. They do NOT assert the MoA
  is indication-operative or directly druggable — a curated edge is a context-free literature aggregate.
  The skill surfaces this via the verdict-inert `mechanism_confirmation_caveat`; directness is owned by
  tractability-small-molecule.
- **`network_class` thresholds (>=3 each arm / <=1 total) are annotation-density heuristics**, not
  biological cutoffs, and are applied to DEDUPED distinct-(partner, direction) union counts — so
  composition is non-monotonic vs a single source's raw-row count. Documented in `_classify_network`.
