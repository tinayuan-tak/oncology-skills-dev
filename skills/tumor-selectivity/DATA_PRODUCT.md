# tumor-selectivity — finalized data product

The **I/O contract** for the tumor-selectivity skill: data wired IN, package emitted OUT, what is locked
for production. Verdict/veto/rescue logic + version history live in the SKILL.md / run.py; this file is
the data-product spec.

| | |
|---|---|
| **Skill** | `tumor-selectivity` |
| **Skill code version** | 1.23.0 |
| **Contract version** | 1.0.0 (emitted-output schema; versioned independently of the skill code — see §4) |
| **Role** | `gating` (verdict moves the nomination; polarity is **dynamic** — the normal-breadth / stromal vetoes emit `canonical_polarity_override="killer"`) |
| **Verdict field** | `headline.selectivity_class` (RESOLVED, post-veto) + `axis_a_selectivity_class` (raw pre-veto) |
| **Output shape** | `data_package` |
| **Emitted schema** | `target-contracts/schemas/skills/tumor-selectivity.decision.schema.json` (generated, self-contained) |
| **Conformance target** | the FRESH replay emit (`test_selectivity_replay.py`); the static `kras_coadread_decision.json` golden is a **trimmed** fixture (7 keys — no envelope/skill_report), so it is NOT a full-decision target |

---

## 1. Inputs — wired data (14 cards)

Every card traces card → method/reader → data-catalog manifest → materialized S3 product. **All 14 are
LIVE** (concrete `s3_uri` + `md5` + `size_bytes`, or a materialized source prefix); no placeholders, no
stale refs. `run.py` has no `CARD_CONTEXT` map (verdict keys off the resolver + Python veto clamp).

### Verdict-driving
| card_id | layer · context | method / reader | catalog manifest(s) | role |
|---|---|---|---|---|
| `tumor-vs-normal-selectivity` | bulk_rna · tumor | `dge_deseq2::read_tumor_vs_normal_selectivity` | **per-indication** `{ind}-dge-tumor-vs-normal-sensitivity-v1` (29 landed) + `-by-subgroup-v1` | **RESOLVER spine** (the only card the resolver reads) |
| `modality-therapeutic-window` | `modality_window` · *(no sample_context)* | `tcga_gtex_tpm_quantiles` | `tcga-gtex-tpm-tissue-quantiles-v1` | veto-clamp → `selective_but_broadly_normal` (KILL) |
| `tumor-scrna-celltype-expression` | sc_rna · tumor | `sc_tumor_expression_celltype` | 9 `sc-pseudobulk-tumor-*` | veto-clamp → `selective_but_stromal_confound` (INT KILL; outranks window) |
| `sc-normal-celltype-expression` | sc_rna · normal | `sc_normal_expression` | 19 `sc-normal-celltype-expression-<tissue>-v1` | veto-clamp → `selective_with_normal_liability` |
| `normal-tissue-protein-abundance-tphp` | bulk_protein_ms · normal | `tphp_normal_protein` | `normal-tissue-protein-abundance-per-gene-v1` | veto-clamp (4th arm) → `selective_with_normal_liability` |
| `tumor-vs-normal-percentile-crossing` | bulk_rna · tumor | `tcga_gtex_expression_distribution` | `tcga-tumor-tpm-recount3-long-v1`; `gtex-tpm-recount3-long-v1` | rescue conjunction (with CPTAC → `field_effect_tumor_selective`) |
| `tumor-protein-abundance-cptac` | bulk_protein_ms · tumor | `cptac_protein_deg::read_target_summary` | `cptac-protein-tumor-vs-normal-per-cohort-v1` | rescue conjunction arm + certainty sidecar (verdict-disjoint) |

### Display-only (verdict-inert)
`surface-abundance-density` (bulk_protein_ms, *no sample_context*; `surface_antigen_density_ladder`),
`expression-purity-confound`, `tumor-vs-normal-protein-abundance-tphp` (`tphp-tumor-vs-normal-protein-per-cohort-v1`),
`spatial-region-rna-expression` (5 products), `spatial-tumor-normal-colocalization` (10),
`spatial-surface-protein-abundance` (3), and `tumor-vs-normal-percentile-crossing-by-subtype`
(`--subtypes`-gated panorama; never enters `fired`; spine byte-identical with/without `--subtypes`).

**Veto clamp mechanism:** the 4 veto arms are a Python clamp (`_skills_common/selectivity_veto.py`), not
resolver rungs — verdict-**MOVING** but tagged `display` in the rule-role partition. **Rescue** (#978)
is a one-directional upgrade applied BEFORE the veto; it is a byte-stable defensive guard (inert on the
current replay panel).

---

## 2. Coverage & capability ceilings (contractual)

- **Tumor-vs-normal DGE (resolver spine):** 29 indications; **per-subgroup (subtype grain) only COADREAD
  (msi_status, cms) + STAD (tcga_molecular_subtype)**. Adjacent-only cohorts fall back to a 2/2 cap
  (`tvn_adjacent_only`); GTEx is the true population-normal arm.
- **CPTAC (rescue + density anchor):** 10 cohorts (BRCA, CCRCC, COAD, GBM, HNSCC, LSCC, LUAD, OV, PDAC,
  UCEC); elsewhere `data_unavailable`.
- **TPHP tumor-vs-normal protein:** 22 carcinoma cohorts — a **different set** than CPTAC (adds
  gallbladder/laryngeal/GIST/testis/thymoma…; BRCA/HNSC/ovarian not resolvable).
- **Normal-breadth VETO (`modality-therapeutic-window`):** keyed on `tcga-gtex-tpm-tissue-quantiles-v1`;
  indications with no TCGA study (e.g. SCLC) → `data_unavailable`, so the window KILL cannot arm there.
- **Stromal-confound VETO (`tumor-scrna-celltype-expression`):** 10 indications; KIRC cube is
  **pan-renal pooled** and OV **pan-gynecologic pooled** (not entity-pure) — lower-trust ceilings the
  veto's provenance gate (`entity_specific` + curated/inferCNV) further narrows.
- **Spatial (display-only):** region-RNA 5 (NSCLC is a ~1.7k-gene panel → off-panel `data_unavailable`);
  coloc 5; surface-protein 2.

---

## 3. Emitted output — the data product

`output_shape: data_package` → the standard `write_package` tree (`decision.json`, `summary.yaml`,
`figures/`, `tables/`, `provenance.yaml`).

`decision.json` top-level: `skill · target · indication · question · generated_at · headline · cards ·
fired_rules · provenance · run_health` (+ optional `consolidation`/`literature_synthesis`/`llm_synthesis`).

**Contractual headline fields:** `selectivity_class` (RESOLVED, pinned enum), `axis_a_selectivity_class`
(raw pre-veto), `therapeutic_window_class`, the `skill_report` spine (`role: gating`, **dynamic**
`polarity`, `call` = resolved `selectivity_class`), `headline_block`, `claim_vector` (WIN/DIST/INT/SAFE
axes), `key_signals`. All other facets (spatial, density, purity, `sc_normal_*`, veto detail…) are
schema-open additive context (byte-frozen by the replay guard).

---

## 4. Contract & versioning (what is locked)

Pinned by a **generated, self-contained** per-skill schema (house style; no cross-file `$ref`) — see
`target-contracts/schemas/skills/tumor-selectivity.decision.schema.json`, generated from the SHARED
`skill_report`/`skill_decision` sources + `_skill_output/pins/tumor-selectivity.pins.json`
(**gating-scalar** variant: pins `role: gating` + the 11-value `selectivity_class`/`call` enum; **no**
polarity const — gating polarity is dynamic; no per-modality bucket map).

**CI (ratchet is live, never a silent skip):**
- `tests/test_selectivity_replay.py::test_replay_conforms_to_data_product_schema` — validates the FRESH
  run.py emit (load-bearing; the static golden is trimmed).
- `tests/test_data_product_schema.py` — schema well-formedness + static-golden-if-full (skips the trimmed
  kras golden); **fails (not skips) in CI** when the schema is unresolvable.
- `skills/tests/test_data_product_lock_coverage.py` — completeness ratchet (`tumor-selectivity` ∈ LOCKED).
- target-contracts `tests/schemas/test_skill_output_contract.py` — meta-validity + self-contained + generator in-sync.

**Change policy:** new `selectivity_class` token → add to the pins enum + regenerate (minor bump);
new/renamed `skill_report` spine key → SHARED source (coordinate; major on rename); new verdict-inert
facet → no schema change.

## 5. Known gaps & notes (non-blocking)

- **Two consumed cards declare no `sample_context`:** `modality-therapeutic-window` and
  `surface-abundance-density` — a card data-contract completeness gap (not a wiring gap). Worth closing on
  the target-contracts side.
- **SKILL.md `rules_scope` omits `tumor-protein-abundance-cptac`** although the #978 rescue reads that
  card's fired rules. Documentation gap to reconcile (the rescue is currently inert on the replay panel).
- **Logical `products.yaml` aliases** (`expression-rna-tumor-vs-*`) remain `status: partial`, but
  tumor-selectivity binds the **concrete** `{ind}-dge-tumor-vs-normal-sensitivity-v1` derived manifests,
  not those aliases — so the skill is fully live despite the logical layer being partial.
