# translational-readiness — finalized data product

The **I/O contract**: data wired IN, package emitted OUT, what is locked. Model/readiness logic + history
live in SKILL.md / run.py; this file is the data-product spec.

| | |
|---|---|
| **Skill** | `translational-readiness` |
| **Skill code version** | 1.5.0 |
| **Contract version** | 1.0.0 (emitted-output schema; versioned independently — see §4) |
| **Role** | `descriptive` — **GATELESS** (`verdict_fn=None` → `skill_report.call` is null; `driving_rule_id` null; `polarity: not_scored`) |
| **Verdict field** | none (multi-vector: `model_availability_class` / `genotype_matched_class` / `pdx_drug_response_class` / `organoid_dependency_class` + `organoid_lineage_class`) |
| **Output shape** | `data_package` |
| **Emitted schema** | `target-contracts/schemas/skills/translational-readiness.decision.schema.json` (generated, self-contained) |
| **Conformance target** | a FROZEN FULL emit `fixtures/translational_full_coadread_decision.json` (real KRAS·COADREAD run; `call=null`, `role=descriptive`) — no replay harness, so this full fixture is the CI conformance target |
| **Composition status** | `partial` — the PD-assay / imaging-tracer / internal-Takeda-model legs are un-wired (absent, not placeholder cards) |

---

## 1. Inputs — wired data (4 cards)

Every card traces card → method → data-catalog manifest → materialized S3 product. **All 4 (5 manifests)
LIVE.** No verdict-driving cards (gateless): all 4 are translational-context display legs.

| card_id | method / manifest | leg |
|---|---|---|
| `target-model-availability` | `hcmi_model_availability` → `hcmi-model-availability-per-indication-v1` | HCMI model coverage (indication-grain, target-independent) |
| `target-genotype-matched-model` | `hcmi_model_availability` → `hcmi-genotype-matched-model-per-gene-v1` | does an available model carry THIS target's alteration? |
| `target-pdx-drug-response` | `pdxe_drug_response` → `pdxe-drug-response-per-gene-v1` | Novartis PDXE in-vivo drug response (RESEARCH-ONLY license) |
| `organoid-crispr-dependency` | `organoid_dependency_precompute` → `organoid-crispr-dependency-26q1-v1` + `-by-lineage-26q1-v1` | patient-derived organoid CRISPR dependency (home = functional-requirement; read as display here) |

Un-wired legs (absent, not placeholder): PD-assay, imaging-tracer, internal Takeda PDX/organoid/GEMM;
genotype-STRATIFIED PDX response (per-model genomics join) is a stated-but-unbuilt v2.

---

## 2. Coverage & capability ceilings (contractual)

- **HCMI availability:** 12 mapped indications / 631 of 805 models (174 unmapped); depth bands
  deep≥50 / moderate 15–49 / sparse<15; outside the 12 → `data_unavailable`.
- **Genotype-matched:** WXS **coding mutations only** (no CN/fusion/expression); coarse gene-level match.
- **PDXE:** 39 curated target tokens only, **target-grain (no per-indication split)**; 30/39 (76.9%)
  HGNC-resolvable; drug→target rollup (no per-model genotype join); RESEARCH-ONLY license.
- **Organoid:** 114 models; only 5 lineages emitted (GI-skewed); Prostate n=9 / Breast n=16 fall below the
  card's `min_organoid_models=20` floor but still emit a class — surfaced by the `organoid_lineage_small_cohort`
  verdict-inert reliability flag.

---

## 3. Emitted output

`output_shape: data_package` → the standard `write_package` tree. `decision.json` top-level:
`skill · target · indication · question · generated_at · headline · cards · fired_rules · provenance ·
run_health` (+ optional synthesis). Contractual headline fields: the 4 stable `*_class` vectors (each with
a card-declared enum) + `organoid_lineage_class` (schema-open, enum-by-reuse), the `skill_report` spine
(`role: descriptive`, `polarity: not_scored`, `call: null`, `driving_rule_id: null`), `headline_block`,
`claim_vector` (MODEL/GENOTYPE/ORGANOID/PDX — MODEL is the only critical axis), `key_signals`. No aggregate
rollup class (no gate to roll into). All else schema-open.

---

## 4. Contract & versioning (what is locked)

Pinned by the generated, self-contained `translational-readiness.decision.schema.json` (gateless-descriptive
pins: `role: descriptive` + `polarity: not_scored` const + `call: null`; NO headline verdict field required —
the `*_class` vectors are schema-open). CI: full-emit conformance (`tests/test_data_product_schema.py`
against the frozen full golden, CI-fail-not-skip), cross-skill coverage ratchet, target-contracts schema
meta-test. Change policy: promote a `*_class` field to contractual → add as a named property + minor bump;
spine key → SHARED source (coordinate; major on rename).

## 5. Known gaps & notes (non-blocking)

- **STALE-METADATA:** the `target-model-availability` card header/caveat, SKILL.md line 98, and the
  manifest's `query_optimization.notes` still describe the pre-broaden **4-indication / 376-model** HCMI
  state, but the product was expanded to **12 indications / 631 models** on 2026-08-24. Data is current;
  the docs/metadata lag. Reconcile the card + SKILL.md + manifest notes.
- **Internal alias inconsistency (verdict-inert):** the skill's `_TR_IND_ALIAS` maps `ESCA→GC`, but the
  reader keeps `ESCA` as its own HCMI product key (96 models). The skill map only keys the curated
  `_VALIDATED_PRECLINICAL_MODEL` false-demote crosswalk (not the data read), so counts are uncorrupted.
- **Release-pinned organoid ids** (`organoid-crispr-dependency-26q1-v1`) carry an explicit REFRESH clause
  (re-pin on each DepMap advance) — a maintenance coupling, not a stable alias.
- **No replay harness:** conformance rests on the frozen full golden (refreeze if the emitted shape changes).
