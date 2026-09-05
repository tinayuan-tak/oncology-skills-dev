# target-intrinsic — finalized data product

The **I/O contract**: data wired IN, package emitted OUT, what is locked. Dossier logic + history live in
SKILL.md / run.py; this file is the data-product spec.

| | |
|---|---|
| **Skill** | `target-intrinsic` · v1.6.0 |
| **Contract version** | 1.0.0 (emitted-output schema; versioned independently — see §4) |
| **Role** | `descriptive` — **GATELESS** (`verdict_fn=None` → `skill_report.call` null; `polarity: not_scored`); **indication-INDEPENDENT** |
| **Verdict field** | none — a multi-field target-biology dossier (~60 headline fields, one+ per sub-axis); `headline_block.verdict.call` is null |
| **Output shape** | `data_package` |
| **Emitted schema** | `target-contracts/schemas/skills/target-intrinsic.decision.schema.json` (generated, self-contained) |
| **Conformance target** | the FRESH replay emit (`test_target_intrinsic_replay.py`; EGFR → call=null, role=descriptive); `indication` emits the `"PANCANCER"` sentinel standalone (verbatim when supplied) |

---

## 1. Inputs — wired data (20 cards) — CLEANEST OF THE FLEET

Every card is `tier: target` (target/gene grain, scope-invariant). **All 20 products LIVE — zero
placeholder, zero stale, zero stale-metadata.** `run.py` `CARDS` ≡ `SKILL.md composition.cards_used` (20).

Grouped by biology dimension:
- **Identity:** `target-identity-summary` (resolver-release alias `target-id-resolver-release` → `resolver_v1.0.0`).
- **Human-genetics safety (indication-agnostic legs):** `gnomad-lof-constraint`, `gene-burden-safety`,
  `clingen-dosage`, `clinvar-pathogenicity-safety`, `mouse-ko-phenotype`, `target-safety-prioritisation` (all
  Open Targets 26.06 / gnomAD / IMPC).
- **Surface / structure / tractability:** `surfaceome-family-classification`, `structure-features-static`,
  `shed-ectodomain-liability`, `measured-potency-tractability` (ChEMBL+BindingDB), `target-development-level`
  (Pharos TDL), `domain-modality-relevance`, `protein-domains-class` (UniProt+InterPro).
- **Network / annotation:** `signaling-network-mechanism` (SIGNOR+CollecTRI+Reactome on-read),
  `reactome-pathway-membership`, `ppi-interactome` (STRING+CORUM+BioGRID), `gene-ontology-annotation`.
- **Dependency-hardening / normal:** `paralog-buffering` (DepMap PARIS), `normal-tissue-liability` (HPA-IHC).

Every one of these signals is verdict-driving in *another* skill (safety/tractability/surface) but is
**inert display here** (gateless). Only two axes project into the (still verdict-INERT) claim_vector:
MODALITY_ROUTING (domain-modality-relevance) + TRACTABILITY_PRECEDENT (target-development-level).

---

## 2. Coverage & capability ceilings (contractual)

- **License flags (productization):** CORUM = **CC-BY-NC-4.0 (non-commercial)**; ChEMBL = CC-BY-SA-3.0
  (share-alike; aggregate rollup only).
- **paralog-buffering:** DepMap 26Q1 PARIS dual-KO only (~4,475 screened-partner genes); Sanger 2023 deferred.
- **mouse-ko IMPC leg:** ~9k genes (partial); un-phenotyped genes read `no_phenotype`.
- **measured-potency:** genes absent from both ChEMBL+BindingDB → `data_unavailable`.
- **surfaceome:** SURFY 2018 misses ~15% of validated ADC targets (mitigated by 4-source fusion).
- **GO / Reactome / TDL:** study-depth proxies, explicitly disclaimed as NOT target-quality signals.

---

## 3. Emitted output

`output_shape: data_package` → the standard `write_package` tree. `decision.json` top-level:
`skill · target · indication(=PANCANCER sentinel standalone) · question · generated_at · headline · cards ·
fired_rules · provenance · run_health` (+ optional synthesis). The headline is a multi-field dossier
(~60 `*_class` fields, no single verdict); `headline_block.verdict.call` = null. The `skill_report` spine:
`role: descriptive`, `polarity: not_scored`, `call: null`, `driving_rule_id: null`; `claim_vector`
(MODALITY_ROUTING / TRACTABILITY_PRECEDENT), `key_signals`. All `*_class` fields schema-open.

---

## 4. Contract & versioning (what is locked)

Pinned by the generated, self-contained `target-intrinsic.decision.schema.json` (gateless-descriptive pins:
`role: descriptive` + `polarity: not_scored` const + `call: null`; NO headline verdict field required — the
dossier `*_class` fields are schema-open). CI: fresh-replay conformance (`test_target_intrinsic_replay.py`),
schema well-formedness + static-golden-if-full, cross-skill coverage ratchet, target-contracts schema
meta-test. Change policy: spine key → SHARED source (coordinate; major on rename); promote a dossier field
to contractual → add as a named property + minor bump.

## 5. Known gaps & notes (non-blocking)

- **No stale-metadata / placeholder** — the cleanest data product in the fleet (all 20 cards materialized).
- **Logical alias:** `target-id-resolver-release` (`release_pin: {release_pin}`) resolves at read time to
  `resolver_v1.0.0` (which pins hgnc-2026-q2 / ensembl-116 / uniprot-2026-02 / ncbi-2026-06-18); structure/
  surfaceome cards key on `{target.uniprot_canonical}` resolved through the same resolver.
- **License caveat** (CORUM non-commercial, ChEMBL share-alike) is the main productization note.
- **`target-safety-prioritisation` is orientation-only** — its safety dims double-count gnomad-lof + mouse-ko
  (flagged via `intrinsic_provenance.ot_composite_double_counts_dedicated_cards`).
- **Sibling card not wired:** `normal-tissue-liability-gtex` (v0.1.0, GTEx RNA breadth) exists but this skill
  uses the HPA-IHC `normal-tissue-liability` (v2.0.0) — no collision in the wired roster.
