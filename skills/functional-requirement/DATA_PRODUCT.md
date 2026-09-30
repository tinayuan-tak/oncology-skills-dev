# functional-requirement — finalized data product

The **I/O contract**: data wired IN, package emitted OUT, what is locked for production. Verdict/resolver
logic + history live in SKILL.md / run.py; this file is the data-product spec.

| | |
|---|---|
| **Skill** | `functional-requirement` |
| **Skill code version** | 1.10.0 |
| **Contract version** | 1.0.0 (emitted-output schema; versioned independently — see §4) |
| **Role** | `gating` (verdict moves the nomination; polarity dynamic — `pan_essential_killer` emits a killer override) |
| **Verdict field** | `headline.dependency_verdict` (resolved) + `dependency_verdict_by_scope` (`{pan_cancer, indication, subtype}`) |
| **Output shape** | `data_package` |
| **Emitted schema** | `target-contracts/schemas/skills/functional-requirement.decision.schema.json` (generated, self-contained) |
| **Conformance target** | the FRESH replay emit (`test_functional_requirement_replay.py`); static `kras_coadread_decision.json` golden is **trimmed** (7 keys) → not a full-decision target |

---

## 1. Inputs — wired data (16 cards)

Every card traces card → method → data-catalog manifest → materialized S3 product. **All 16 products are
LIVE** (concrete `md5`+`size`, or a materialized DepMap source-release prefix). `run.py` has no
`CARD_CONTEXT` map; the verdict resolves via the shared `dependency.resolver.yaml`.

### Verdict-driving (7 → the resolver)
`pan-cancer-crispr-dependency-distribution`, `pan-cancer-rnai-dependency-distribution`,
`crispr-rnai-dependency-concordance`, `dependency-lineage-selectivity`, `paralog-buffering`
(veto-suppressor → `non_dependent_paralog_buffered`), `partner-conditional-dependency` (→
`partner_conditional_dependent`; MODERATE-tier rescue, WRN×MSI live), `prism-crispr-concordance`
(chemical-genetic, positive-only → `chemical_genetic_confirmed_dependent`).
Substrates: `depmap-consortium-26q1` (+`-rnai`) source-releases; `depmap-paralog-buffering-per-gene-v1`;
`depmap-prism-activity-v4`.

### Confidence-only (3 → `dependency_confidence_note`, no resolver rung)
`dependency-predictability` (`depmap-predictability-26q1-v4`), `cross-consortium-dependency` (Broad↔Sanger
corroboration; also the sole certainty `corroboration` input), `coessential-module`
(`depmap-coessentiality-26q1-v1`; module-coherence lift).

### Verdict-inert render facets (5)
`expression-dependency-correlation`, `abundance-dependency` (Gygi + expression), `recommended-models`
(`bulk_rna`/`tumor`; recount3 + DepMap), `genomic-event-model-match` (MC3 + PanCanAtlas CNV + DepMap),
`organoid-crispr-dependency` (~114 GI organoid models; corroborates a positive, never a veto — machine-
enforced by `tests/test_organoid_arm_never_vetoes.py`: no dependency-resolver rung references an organoid
rule id).

FR composes these facets and projects NOTHING from them into its OWN dependency verdict; where they carry
downstream weight, a SIBLING projects them: `organoid_dependency_class` → translational-readiness;
`correlation_class` (expression-dependency-correlation) → target-profile `tp_facets_biomarker` + cis-
feature-coherence; `subtype_dependency_pattern` → example-gallery render only. (Swept 2026-09-19; no
verdict-inert facet is orphaned — each has a consumer or a render home.)

### Subtype panorama (1, `--subtypes`-gated)
`subgroup-stratified-dependency` — verdict-INERT in this standalone skill (resolved on the separate
`subtype_panorama_fn` path; `dependency_verdict` byte-identical with/without `--subtypes`); one-directional
verdict-bearing only in the composed target-profile `--subtypes` tier. Logical alias `subgroup-catalog`
→ per-indication `depmap-subgroup-assignments-{IND}-v1` shard at read time.

---

## 2. Coverage & capability ceilings (contractual)

- **DepMap CRISPR** ≈1,538 Chronos lines (26Q1); **RNAi** ≈712 (DEMETER2); concordance on the CRISPR∩RNAi
  overlap (≥30 lines, else `partially_assayed`).
- **Subtype shards** (`--subtypes`): COADREAD, ESCA, HNSC, NSCLC, PAAD, **SCLC**, STAD (SKILL.md text omits
  SCLC — doc list is behind).
- **`recommended-models`** 17-indication set; **`genomic-event-model-match`** 20-set (adds NSCLC/GC/UCEC).
- **`partner-conditional-dependency`** covers only targets with a curated partner (`partner_map.yaml`),
  else `no_partner_mapped` (abstention, not a negative).
- **`paralog-buffering`** DepMap 26Q1 dual-KO PARIS library only (~4,475 genes w/ a screened partner);
  Sanger Paralog Screen excluded (license) → absent genes `data_unavailable`.
- **`organoid-crispr-dependency`** ~114 GI-dominated models, pan-organoid target grain only.
- **`coessential-module`** drops 4,329 high-NaN genes; POLR2A absent (DepMap guide-design gap).

---

## 3. Emitted output

`output_shape: data_package` → the standard `write_package` tree. `decision.json` top-level:
`skill · target · indication · question · generated_at · headline · cards · fired_rules · provenance ·
run_health` (+ optional synthesis blocks). Contractual headline fields: `dependency_verdict` (pinned
enum), `driving_rule_id`, `dependency_verdict_by_scope`, the `skill_report` spine (`role: gating`,
dynamic `polarity`, `call` = resolved `dependency_verdict`; carries `modality_scope` for the degrader
channel), `headline_block`, `claim_vector` (DEP/SEL/COND/CHEM), `key_signals`. All else schema-open.

---

## 4. Contract & versioning (what is locked)

Pinned by the generated, self-contained `functional-requirement.decision.schema.json` (gating-scalar
pins: `role: gating` + the 13-value `dependency_verdict`/`call` enum = the shared dependency resolver's
verdict set; no polarity const; `dependency_verdict_by_scope` typed-open — dynamic scope keys).

CI: fresh-replay conformance (`test_functional_requirement_replay.py`), schema-well-formedness +
static-golden-if-full (`tests/test_data_product_schema.py`, CI-fail-not-skip), the cross-skill coverage
ratchet, and the target-contracts schema meta-test. Change policy: new verdict token → pins enum +
regenerate (minor); spine key → SHARED source (coordinate; major on rename); new facet → no schema change.

## 5. Known gaps & notes (non-blocking)

- **`coessential-module.card.yaml` `status: dormant_pending_data` is STALE** — its method
  (`depmap_coessentiality`) + product (`depmap-coessentiality-26q1-v1`, materialized) are built and the
  skill actively reads `coessential_module_class` into `dependency_confidence_note`. Fix the card status
  (a target-contracts `cards/` change, separate from this schema).
- **`depmap-paralog-buffering-per-gene-v1`** uses a legacy S3 path not mirroring its manifest id
  (materialized + md5-verified → LIVE; cosmetic id/path mismatch).
- **SKILL.md subtype list omits SCLC** (shard landed after the doc) — doc reconciliation.
