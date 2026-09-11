# tractability-small-molecule — finalized data product

The **I/O contract**: data wired IN, package emitted OUT, what is locked. Chemical-genetic + structure
logic + history live in SKILL.md / run.py; this file is the data-product spec.

| | |
|---|---|
| **Skill** | `tractability-small-molecule` |
| **Contract version** | 1.0.0 (emitted-output schema; versioned independently — see §4) |
| **Role** | `gating` (verdict moves the nomination; polarity dynamic 3-band {supportive/neutral/opposing}, **no killer** — SM has no cross-target veto) |
| **Verdict field** | `headline.druggability_snapshot` (SM inhibition call) + `degrader_snapshot` (degrader arm) + `druggability_verdict_by_modality` {small_molecule, degrader} |
| **Output shape** | `data_package` |
| **Emitted schema** | `target-contracts/schemas/skills/tractability-small-molecule.decision.schema.json` (generated, self-contained) |
| **Conformance target** | the FRESH replay emit (`test_tractability_sm_replay.py`; EGFR `well_covered`, BRAF `chemically_active`, FOXA1 `structurally_ligandable`; `call == druggability_snapshot`) |

---

## 1. Inputs — wired data (9 cards) — CLEAN

Every card traces card → method → data-catalog manifest → materialized S3 product. **All 9 products LIVE**;
no placeholders, no stale refs, no stale-metadata skew. `run.py` has no `CARD_CONTEXT` map.

**Verdict-driving (5 → `tractability_small_molecule.resolver.yaml`):**
`prism-compound-activity` (`depmap-prism-activity-v4`), `prism-crispr-concordance` (shared PRISM parquet;
top-precedence on-target rungs), `structure-features-static` (`structure-ligandability-per-protein-v1` +
`pdb-alphafold-structure-features-per-uniprot-v1`), `known-drug-tractability` (`dgidb-drug-gene-per-gene-v1`
+ directional), `measured-potency-tractability` (`chembl-bioactivity-per-protein-v1` + `bindingdb-affinity-per-protein-v1`).

**Display / SM-verdict-inert (4):** `dependency-predictability` (confidence only), `gdsc-drug-activity`
(2nd-platform, verdict-inert), `degradation-feasibility` (fires **degrader-channel-only** rules —
drives `degrader_snapshot` + the `.degrader` arm, never the SM scalar; `ubibrowser-e3-substrate-per-gene-v1`
+ `surfaceome-family-classification-per-uniprot-v1`), `mutation-hotspot-frequency` (`gdc-somatic-hotspot`
→ GDC-MC3; **#993 pt1** context — the indication's mutant-allele spectrum, read ONLY by the verdict-inert
`minority_allele_coverage_caveat`; fires no rule, feeds no resolver rung).

---

## 2. Coverage & capability ceilings (contractual)

- **PRISM compound ceiling:** `depmap-prism-activity-v4` = 2,078 genes (≥1 PRISM-annotated compound);
  no-compound targets → `chemically_unhit` (a real class, not a gap) — the ceiling that motivated the
  forward-structure leg.
- **Structure/ligandability:** PDB+AlphaFold covers 20,329 reviewed-human ACs (8,936 experimental PDB);
  ligandability 20,577 proteins; UniProt→HGNC 97.8%.
- **DGIdb currency:** `dgidb-drug-gene-per-gene-v1` self-reports **Data version Dec-2023** (a repackaging)
  — treat the known-drug leg as a Dec-2023 snapshot.
- **GDSC token resolution:** free-text putative-target token, only ~65.9% resolve to a single HGNC gene
  (verdict-inert → no verdict impact; a display caveat).
- **Indication:** the SM verdict is effectively **indication-independent** (all structure/drug/potency/
  degradation cards are `tier: target`; PRISM's `target_lineage` is an additive Tier-2 display layer).

---

## 3. Emitted output

`output_shape: data_package` → the standard `write_package` tree. `decision.json` top-level:
`skill · target · indication · question · generated_at · headline · cards · fired_rules · provenance ·
run_health` (+ optional synthesis). Contractual headline fields: `druggability_snapshot` (pinned enum),
`degrader_snapshot`, `druggability_verdict_by_modality` {small_molecule: viable/caveated/opposed/not_viable/
insufficient; degrader: viable/supported/opposed/not_viable/insufficient}, the `skill_report` spine
(`role: gating`, dynamic `polarity` floored at opposing, `call` = `druggability_snapshot`), `headline_block`,
`claim_vector` (POTENCY/ACTIVITY/STRUCT/DRUG/DEGRADER), `key_signals`. All else schema-open.

---

## 4. Contract & versioning (what is locked)

Pinned by the generated, self-contained `tractability-small-molecule.decision.schema.json` (gating-scalar
pins: `role: gating` + the 13-value `druggability_snapshot`/`call` enum = the tractability resolver set =
`_DRUGGABILITY_VERDICT_PHRASE`; no run.py mints; no polarity const; `degrader_snapshot` +
`druggability_verdict_by_modality` typed-open).

CI: fresh-replay conformance (`test_tractability_sm_replay.py`), schema-well-formedness +
static-golden-if-full (`tests/test_data_product_schema.py`, CI-fail-not-skip), cross-skill coverage
ratchet, target-contracts schema meta-test. Change policy: new verdict token → pins enum + regenerate
(minor); spine key → SHARED source (coordinate; major on rename); new facet → no schema change.

## 5. Known gaps & notes (non-blocking)

- **Clean data product** — no placeholder cards, no stale-metadata. (Prose skew only: SKILL.md "What this
  skill does" says "the 7 tractability cards"; the roster is 8 — `gdsc-drug-activity` is the display-only 8th.)
- **Logical aliases:** `depmap-predictability` (→ `-26q1-v3` by release pin), PRISM `prism-activity-v4` pin.
- **Wiring nuance:** `dgidb-drug-target-directional-v1` supplies directness fields to the known-drug +
  measured-potency cards but is not listed in their `required_inputs` (read alongside the primary product).
- **Doc-vs-code nuance:** the `_DEG_ARM` map emits `supported` (not `caveated`) for `degrader_rationale`,
  though a code comment claims a shared arm vocab — the schema/DATA_PRODUCT encode both arms' enums exactly.
