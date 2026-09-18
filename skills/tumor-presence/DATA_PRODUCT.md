# tumor-presence — finalized data product

The **I/O contract** for the tumor-presence skill: the data wired IN, the package emitted OUT, and what
is locked for production. Design rationale + verdict-ladder logic live in [CONTRACT.md](CONTRACT.md);
this file is the data-product spec.

| | |
|---|---|
| **Skill** | `tumor-presence` |
| **Skill code version** | 1.22.0 (see CONTRACT.md § Version history) |
| **Contract version** | 1.0.0 (the emitted-output schema; versioned independently of the skill code — see §4) |
| **Role** | `descriptive` (emits a real read; **not** a nomination gate — presence ∉ target-profile `_SHORT_TO_GATE`) |
| **Verdict field** | `headline.presence_verdict` (collapsed) + `headline.presence_verdict_by_modality` (per-bucket) |
| **Output shape** | `data_package` (see § Emitted output) |
| **Emitted schema** | `target-contracts/schemas/skills/tumor-presence.decision.schema.json` (generated, self-contained) |
| **Conformance target** | the FRESH replay emit (`test_tumor_presence_replay.py`); the static golden `tests/fixtures/epcam_coadread_decision.json` is a `--synthesize`-era snapshot (its `run_health.skill_version` may lag) validated as a secondary check |

---

## 1. Inputs — wired data (17 cards)

Every card resolves card → method/reader → data-catalog manifest → materialized S3 product. **All 17 are
LIVE** (concrete `s3_uri` + `md5` + `size_bytes`, or a materialized source prefix); no placeholders, no
stale refs, and every card's `measurement/sample_context` matches `run.py`'s `CARD_CONTEXT`. Per-field
utilization of each card's `summary_fields` is ratcheted by [field_disposition.yaml](field_disposition.yaml)
(`tests/test_field_disposition_complete.py`).

### Verdict-bearing (7) — feed the presence ladders
| card_id | layer · context | method / reader | catalog manifest(s) | status |
|---|---|---|---|---|
| `cellline-rna-distribution` | bulk_rna · cell_line | `depmap_expression_distribution` (+`depmap_isoform_expression`) | `depmap-consortium-26q1` (src); `allgene-depmap-rank-26q1-v1`; `depmap-isoform-expression-per-gene-v1` | LIVE |
| `tumor-rna-vs-adjacent` | bulk_rna · tumor | `dge_deseq2` (`read_dge_gene_row`) | **logical** `expression-rna-tumor-vs-adjacent` → per-indication DGE (e.g. `coadread-dge-df06320`) | LIVE · see §1a |
| `tumor-rna-distribution` | bulk_rna · tumor | `tcga_gtex_expression_distribution` (+`tcga-spliceseq-psi`) | `tcga-tumor-tpm-recount3-long-v1` (3.03 GB); `gtex-tpm-recount3-long-v1`; `allgene-tumor-rank-v1`; `tcga-spliceseq-psi-per-gene-v1` | LIVE |
| `tumor-protein-abundance-cptac` | bulk_protein_ms · tumor | `cptac_protein_deg` (`read_target_summary`) | `cptac-protein-tumor-vs-normal-per-cohort-v1` | LIVE · 10 cohorts |
| `cellline-protein-abundance` | bulk_protein_ms · cell_line | `depmap_protein_abundance` (`read_target_summary`) | `depmap-gygi-protein-abundance-per-protein-v1` | LIVE |
| `tumor-elevation-breadth` | bulk_protein_ms · tumor | `cptac_protein_deg` (`read_tumor_elevation_breadth`) + RNA breadth | `cptac-protein-tumor-vs-normal-per-cohort-v1`; `pancan-dge-tumor-vs-normal-v1` (RNA, 27 ind.) | LIVE |
| `tumor-scrna-celltype-expression` | sc_rna · tumor | `sc_tumor_expression_celltype` (`read_sc_expression_presence`) | 9 `sc-pseudobulk-tumor-*` products | LIVE · 9 ind. (see §1b) |

### Display-only facets (8) — additive context, feed no ladder (verdict byte-stable)
| card_id | layer · context | catalog manifest(s) | status |
|---|---|---|---|
| `tumor-rna-distribution-by-subtype` | bulk_rna · tumor | `tcga-tumor-tpm-recount3-long-v1`; `tcga-tumor-tpm-per-sample-v1`; `tcga-subgroup-assignments-coadread-v1` | LIVE · COADREAD-scoped |
| `cellline-rna-distribution-by-subtype` | bulk_rna · cell_line | `depmap-consortium-26q1` (src); `depmap-subgroup-assignments-coadread-v1` | LIVE · COADREAD-scoped |
| `tumor-protein-distribution-by-subtype` | bulk_protein_ms · tumor | `cptac-protein-tumor-vs-normal-per-sample`; CPTAC subgroup assignments | LIVE · COADREAD/MSI-scoped |
| `expression-purity-confound` | bulk_rna · tumor | `tcga-tumor-tpm-recount3-long-v1`; `gdc-pancanatlas-cnv-2018` (ABSOLUTE purity, src) | LIVE |
| `cellline-rna-protein-concordance` | bulk_rna · cell_line (RNA-anchored) | `depmap-consortium-26q1` + `-26q1-proteomics` (src) | LIVE |
| `rna-protein-concordance-tumor` | bulk_rna · tumor (RNA-anchored) | `cptac-rna-protein-matched-per-sample-v1` | LIVE |
| `cellline-protein-abundance-procan` | bulk_protein_ms · cell_line | `procan-cellline-protein-abundance-per-protein-v1` (2nd MS platform, CC-BY) | LIVE |
| `hpa-pathology-cancer-ihc` | protein_ihc · tumor | `hpa-pathology-cancer-ihc-per-gene-v1` (MS-independent) | LIVE · ~20 cancer types |

### Normal-tissue safety comparators (2) — verdict-inert window framing (safety verdict owned by `on-target-safety-liability`)
| card_id | layer · context | catalog manifest(s) | status |
|---|---|---|---|
| `normal-tissue-liability` | protein_ihc · normal | `hpa-v25-1` (src, `proteinatlas.tsv.zip`) | LIVE |
| `sc-normal-celltype-expression` | sc_rna · normal | 19 `sc-normal-celltype-expression-<tissue>-v1` products | LIVE · tissue-gated |

### 1a. Logical-alias indirection (one card)
`tumor-rna-vs-adjacent` pins the **logical** `products.yaml` id `expression-rna-tumor-vs-adjacent`, not a
concrete manifest. `dge_deseq2` resolves it per-indication at read time to the built DGE product for that
indication (e.g. `coadread-dge-df06320`, or the `<ind>-dge-tumor-vs-normal-sensitivity-v1` family). It is
therefore **per-indication gated**: only indications with a built DGE product resolve; others read
`data_unavailable`.

---

## 2. Coverage & capability ceilings (contractual, not incidental)

A gap here is an **honest capability ceiling** (emits `data_unavailable`), never a coarser fallback.

- **Single-cell tumor (`tumor-scrna-celltype-expression`)** — 9 indications via `INDICATION_TO_PRODUCT`:
  COADREAD/COAD/READ, NSCLC/LUAD, LUSC, PAAD, HNSC, KIRC, OV, STAD, BRCA. Caveats baked into the reader:
  **KIRC / OV / LUAD are multi-entity-pooled** (not entity-pure denominators); **STAD's malignant call is
  `phenotype_proxy`** (Epithelial ∩ GC, no inferCNV) — weaker than the curated (CRC/LuCA/BRCA) or inferCNV
  (3CA) cubes.
- **By-subtype panoramas** (`tumor-` / `cellline-rna-distribution-by-subtype`, `tumor-protein-distribution-by-subtype`)
  — **COADREAD-scoped as pinned** (only the COADREAD subgroup-assignment shard is in `required_inputs`).
- **Tumor protein (CPTAC)** — 10 CPTAC cohorts; elsewhere `protein_ihc/tumor` (HPA IHC, ~20 cancer types)
  is the MS-independent protein-in-tumor leg.

---

## 3. Emitted output — the data product

`output_shape: data_package` → [`_skills_common/write_package.py`](../_skills_common/write_package.py)
writes a fixed tree:

```
<out>/
├── decision.json      # the full emitted object (schema-pinned; see §4)
├── summary.yaml       # per-card summary dicts (human-readable)
├── figures/           # {card_id}_primary.{svg,png} slide-droppable
├── tables/            # {card_id}_summary_stats.csv (+ top_hits where exposed)
└── provenance.yaml    # target, indication, S3 URIs, invoked_lenses
```

### `decision.json` top-level (the promised surface)
`skill · target · indication · question · generated_at · headline · cards · fired_rules · provenance ·
run_health` (+ optional `consolidation · literature_synthesis · llm_synthesis`).

- **`headline`** — the presence declaration + ~150 verdict-inert facet fields. Contractual fields:
  `presence_verdict` (collapsed one-word call, pinned enum), `driving_rule_id`,
  `presence_verdict_by_modality` (one `{measurement, sample_context, verdict, driving_rule_id,
  evidence_state}` per of the 8 buckets), the `skill_report` spine (below), `headline_block`,
  `claim_vector`, `key_signals`. All other facets (`sc_*`, `subtype_*`, `abundance_floor_flag`,
  `presence_confirmation_caveat`, …) are **schema-open** additive context — documented in CONTRACT.md,
  byte-frozen by the golden, and free to grow without churning the schema.
- **`skill_report`** — the SHARED cross-skill object (`_skills_common/skill_report.py`): `call` (=
  reconciled `presence_verdict`), `role: descriptive`, `polarity: not_scored`, `honest_phrase`,
  `confidence`, `top_tension`, `claim_chips[]`, `question_table[]`, `per_phase_metrics[]`, `figures[]`,
  `provenance`. This is the object `target_report` composes over — the primary consumer contract.
- **`provenance.resolved_releases`** — per-manifest `{used, head, is_stale}`; the wiring staleness audit.
- **`run_health`** — `{skill_name, skill_version, status, n_cards_*, timings}`.

---

## 4. Contract & versioning (what is locked)

Emitted shape is pinned in `target-contracts/schemas/` by a **generated, self-contained** per-skill
schema (house style — no cross-file/network `$ref`, validates with no registry):
- **Sources (canonical):** `skill_report.schema.json` (SHARED spine, **strict** `additionalProperties:false`),
  `skill_decision.schema.json` (SHARED envelope: required top-level keys + `provenance.resolved_releases`
  with mandatory `is_stale` + lineage digests + the embedded `skill_report`), and
  `_skill_output/pins/tumor-presence.pins.json` (THIN per-skill pins: `presence_verdict`/`call` enum,
  per-modality bucket shape, `role: descriptive` + `polarity: not_scored`).
- **Generated:** `validators/gen_skill_output_schemas.py` inlines the spine+envelope as `$defs` and merges
  the pins → `schemas/skills/tumor-presence.decision.schema.json` (committed, self-contained). Regenerate
  with the generator; CI runs `--check` to fail on drift.

Fields pinned beyond the verdict (so a rename can't silently break a consumer): the `skill_report` spine
incl. `evidence_graph` + `subgroup_signals` (render inputs); `headline.headline_block`/`claim_vector`/
`key_signals` (carried into `nomination.json` + the cross-evidence reasoner); `skill_report.call` (same
enum as `presence_verdict`); the `provenance` lineage digests + per-manifest `is_stale`.

**CI (the ratchet is *live*, never a silent skip):**
- `tests/test_tumor_presence_replay.py::test_replay_conforms_to_data_product_schema` — validates the
  **FRESH** run.py emit (load-bearing output-drift guard).
- `tests/test_data_product_schema.py` — static golden + schema well-formedness; **fails (not skips) in
  CI** when the schema is unresolvable (land the contracts schema PR first).
- `skills/tests/test_data_product_lock_coverage.py` — completeness ratchet across the fan-out.
- target-contracts `tests/schemas/test_skill_output_contract.py` — meta-validity + self-contained +
  generator in-sync.

**Change policy (contract semver; append-only within a major):**
- New `presence_verdict`/`call` value → add to the pins enum + regenerate; **minor** bump. Consumers must
  treat an unknown token as passthrough, not a hard switch failure.
- New verdict-inert **facet** field → **no** schema change (headline is `additionalProperties:true`); the
  fresh-replay validation + `field_disposition.yaml` ratchet cover it. Facet **promotion** to contractual
  = add as a named property in the source schema + **minor** bump.
- New/renamed `skill_report` spine key → change the SHARED source (fans out to all 14 — coordinate);
  rename/removal/enum-narrowing = **major** bump.

## 5. Known gaps & headroom (non-blocking)

- **Materialized-but-unwired sc-tumor cubes:** `sc-pseudobulk-tumor-3ca-npc-v1`,
  `-coadread-vumc-v1`, `-hnsc-bu-v1` exist in the catalog but are not in `INDICATION_TO_PRODUCT`
  (deliberate — single-reader-per-indication; swapping regressed the primary reader). Available headroom.
- **By-subtype non-COADREAD shards** (esca, hnsc, nsclc, paad, stad, sclc) exist in the catalog but are
  not pinned in the by-subtype cards' `required_inputs`. Extending subtype coverage is additive.
- **Heavy substrates** (`gtex-tpm-recount3-long-v1` 7.57 GB, `tcga-tumor-tpm-recount3-long-v1` 3.03 GB):
  fine for gene-sorted predicate-pushdown per-gene reads; relevant only on re-materialization.
