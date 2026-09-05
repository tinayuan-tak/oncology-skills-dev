# immune-context — finalized data product

The **I/O contract**: data wired IN, package emitted OUT, what is locked. CD8/immune logic + history live
in SKILL.md / run.py; this file is the data-product spec.

| | |
|---|---|
| **Skill** | `immune-context` |
| **Skill code version** | 1.6.1 |
| **Contract version** | 1.0.0 (emitted-output schema; versioned independently — see §4) |
| **Role** | `descriptive` (TCE-effector CD8 read; **gateless/additive** — inline `_verdict`, no shared resolver, absent from `_SHORT_TO_GATE`; `polarity: not_scored`) |
| **Verdict field** | `headline.immune_context_verdict` (indication-level / **target-independent**) |
| **Output shape** | `data_package` |
| **Emitted schema** | `target-contracts/schemas/skills/immune-context.decision.schema.json` (generated, self-contained) |
| **Conformance target** | a FROZEN FULL emit `fixtures/immune_full_coadread_decision.json` (real CD8A·COADREAD run → `immune_intermediate`) — immune-context has no card-replay harness, so this full fixture is the CI conformance target |

---

## 1. Inputs — wired data (6 cards)

Every card traces card → method → data-catalog manifest → materialized S3 product. **All 6 products LIVE.**
`run.py` has no `CARD_CONTEXT` map.

**Verdict-driving (1):** `immune-context` (`immune_context` method; pooled median CD8 fraction vs pan-cancer
Q1/Q3). Card declares source `gdc-pancanatlas-immune-2018`; reader reads the derived
`pancanatlas-cibersort-lm22-per-sample-v1` (lineage intact — declares upstream id, reads derived).

**Display-only / verdict-inert (5):** `myeloid-compartment-expression-cheng` (`sc-pseudobulk-myeloid-cheng-v1`),
`caf-compartment-expression-luo` (`sc-pseudobulk-caf-luo-pancancer-v1`), `ici-response-association`
(`ici-response-expression-per-gene-v1`, SKCM-only), `ici-response-imvigor210`
(`imvigor210-ici-response-per-gene-v1`, BLCA-only), `tcga-til-fraction-saltz`
(`tcga-til-fraction-saltz-per-sample-v1`, absolute-TIL corroborator; feeds `til_cibersort_agreement`).

---

## 2. Coverage & capability ceilings (contractual)

- **The CD8 verdict is INDICATION-LEVEL / TARGET-INDEPENDENT** (`--target` accepted but ignored). Keys on
  indication → TCGA study code(s); CIBERSORT covers all 33 TCGA studies; `applies_when` advertises 20
  indications. Unmapped indication → `data_unavailable` (card) → verdict `insufficient` (never a false 'cold').
- **Saltz absolute-TIL corroborator:** 13 TCGA studies only (else `data_unavailable`, fail-closed).
- **ICI cards** are hard target×indication ceilings: `ici-response-association` = **SKCM only**;
  `ici-response-imvigor210` = **BLCA/urothelial only** (both key on `target.symbol`).
- **TME cards** (myeloid Cheng / CAF Luo) pan-cancer, target-grain (8 / 10 cancer types).
- Only target-dependent fields the skill surfaces = the verdict-inert antigen-conditioned join
  (`antigen_conditioned_call` / `cd8_high_minus_low` / `antigen_high_immune_context_class`), degrading to
  `data_unavailable` when the CIBERSORT-barcode↔expression-UUID join is thin.

---

## 3. Emitted output

`output_shape: data_package` → the standard `write_package` tree. `decision.json` top-level:
`skill · target · indication · question · generated_at · headline · cards · fired_rules · provenance ·
run_health` (+ optional synthesis). Contractual headline fields: `immune_context_verdict` (pinned enum:
immune_hot/immune_intermediate/immune_cold/insufficient — **not** data_unavailable), the `skill_report`
spine (`role: descriptive`, `polarity: not_scored`, `call` = `immune_context_verdict`), `headline_block`,
`claim_vector`, `key_signals`. NOTE: the headline HERO badge has its own dynamic display polarity
(immune_hot→positive / immune_cold→negative, discordance→neutral) — separate from the canonical
`skill_report.polarity` (fixed `not_scored`). All else schema-open.

---

## 4. Contract & versioning (what is locked)

Pinned by the generated, self-contained `immune-context.decision.schema.json` (descriptive-scalar pins:
`role: descriptive` + `polarity: not_scored` const + the 4-value `immune_context_verdict`/`call` enum =
`_IMMUNE_VERDICT_PHRASE`; no run.py mints). CI: full-emit conformance (`tests/test_data_product_schema.py`
against the frozen full golden, CI-fail-not-skip), cross-skill coverage ratchet, target-contracts schema
meta-test. Change policy: new verdict token → pins enum + regenerate (minor); spine key → SHARED source
(coordinate; major on rename); new facet → no schema change.

## 5. Known gaps & notes (non-blocking)

- **Provenance indirection:** the verdict card declares `required_inputs: gdc-pancanatlas-immune-2018`
  (source) but reads the derived `pancanatlas-cibersort-lm22-per-sample-v1` (lineage intact; advertises
  upstream id, reads derived) — a provenance-declaration nuance.
- **Manifest measurement_type skew (display card):** `caf-compartment-expression-luo` card declares
  `sc_tumor_caf_state_expression` but its manifest declares `sc_tumor_celltype_expression` + a stray
  `card:` attribution — cosmetic manifest skew, verdict-inert.
- **`ici-response-imvigor210` legacy-symbol resolver gap (filed, verdict-inert):** the Genentech eSet's
  `fData$symbol` is not run through the gene resolver, so a modern HGNC symbol misses its legacy alias
  (NECTIN4 absent / PVRL4 present). Display card only; fix belongs in the data product (re-derive through
  resolver) or reader (alias-fold on read).
- **No replay harness:** conformance rests on the frozen full golden (refreeze from a real emit if the
  emitted shape changes).
