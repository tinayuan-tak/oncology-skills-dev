# immune-context — finalized data product

The **I/O contract**: data wired IN, package emitted OUT, what is locked. CD8/immune logic + history live
in SKILL.md / run.py; this file is the data-product spec.

| | |
|---|---|
| **Skill** | `immune-context` |
| **Skill code version** | 1.8.0 |
| **Contract version** | 1.0.0 (emitted-output schema; versioned independently — see §4) |
| **Role** | `descriptive` (TCE-effector CD8 read; **gateless/additive** — inline `_verdict`, no shared resolver, absent from `_SHORT_TO_GATE`; `polarity: not_scored`) |
| **Verdict field** | `headline.immune_context_verdict` (indication-level / **target-independent**) |
| **Output shape** | `data_package` |
| **Emitted schema** | `target-contracts/schemas/skills/immune-context.decision.schema.json` (generated, self-contained) |
| **Conformance target** | a FROZEN FULL emit `tests/fixtures/immune_full_emit.json` (real CD8A·COADREAD run → `immune_intermediate`) — immune-context has no card-replay harness, so this full fixture is the CI conformance target |

---

## 1. Inputs — wired data (7 cards)

Every card traces card → method → data-catalog manifest → materialized S3 product. **All 7 products LIVE.**
`run.py` has no `CARD_CONTEXT` map.

**Verdict-driving (1):** `immune-context` (`immune_context` method; pooled median CD8 fraction vs pan-cancer
Q1/Q3). Card declares source `gdc-pancanatlas-immune-2018`; reader reads the derived
`pancanatlas-cibersort-lm22-per-sample-v1` (lineage intact — declares upstream id, reads derived).

**Display-only / verdict-inert (6):** `myeloid-compartment-expression-cheng` (`sc-pseudobulk-myeloid-cheng-v1`),
`caf-compartment-expression-luo` (`sc-pseudobulk-caf-luo-pancancer-v1`), `ici-response-association`
(`ici-response-expression-per-gene-v1`, SKCM-only), `ici-response-imvigor210`
(`imvigor210-ici-response-per-gene-v1`, BLCA-only), `tcga-til-fraction-saltz`
(`tcga-til-fraction-saltz-per-sample-v1`, absolute-TIL corroborator; feeds `til_cibersort_agreement`),
`spatial-tumor-normal-colocalization` (GeoMx/Xenium/CosMx `spatial_colocalization`; feeds
`spatial_immune_phenotype`).

**Verdict-inert ≠ inert.** Two of the six are the CORROBORATION RULER's orthogonal platforms (§3a): the
Saltz card checks the CD8 read's ABSOLUTE density and the co-localization card checks its LOCALIZATION.
They move `skill_report.confidence` and `modality_scope`, never the verdict token.

---

## 2. Coverage & capability ceilings (contractual)

- **The CD8 verdict is INDICATION-LEVEL / TARGET-INDEPENDENT** (`--target` accepted but ignored). Keys on
  indication → TCGA study code(s); CIBERSORT covers all 33 TCGA studies; `applies_when` advertises 20
  indications. Unmapped indication → `data_unavailable` (card) → verdict `insufficient` (never a false 'cold').
- **Saltz absolute-TIL corroborator:** 13 TCGA studies only (else `data_unavailable`, fail-closed).
- **ICI cards** are hard target×indication ceilings: `ici-response-association` = **SKCM only**;
  `ici-response-imvigor210` = **BLCA/urothelial only** (both key on `target.symbol`).
- **TME cards** (myeloid Cheng / CAF Luo) pan-cancer, target-grain (8 / 10 cancer types).
- **Spatial co-localization** (`spatial-tumor-normal-colocalization`): ~6 covered indication families;
  `data_unavailable` elsewhere. No `n_donors` floor today — a single-donor product yields a full class.
- Only target-dependent fields the skill surfaces = the verdict-inert antigen-conditioned join
  (`antigen_conditioned_call` / `cd8_high_minus_low` / `antigen_high_immune_context_class`), degrading to
  `data_unavailable` when the CIBERSORT-barcode↔expression-UUID join is thin, plus the spatial
  co-localization reads (`spatial_coloc_class` / `spatial_immune_phenotype` /
  `spatial_immune_adjacency_fraction` / `spatial_top_enriched_compartment`).
- **The class token is a pan-cancer RANK, not an absolute density** (see §3a). Cuts are the 33-study Q1
  (0.084) / Q3 (0.113) of the CD8 SHARE of the LEUKOCYTE compartment, so ~9 studies are hot and ~9 cold BY
  CONSTRUCTION. Consumers must read `reference_frame` alongside the token.
- **Lymphoid-denominator ceiling (open, filed — analysis-methods):** CIBERSORT's denominator is the
  LEUKOCYTE compartment, so in a leukemia/lymphoma or a normal lymphoid organ the denominator IS the
  malignant clone (LAML 0.0216 → cold, DLBC 0.1142 → hot, THYM 0.2782 → hot). Currently masked only by the
  indication map omitting those studies; a fail-closed guard belongs in the method, not the map.
- **No `n_samples` floor** on the CIBERSORT read (the sibling Saltz reader has `MIN_N=30`), and the cohort
  MEDIAN dilutes bimodal cohorts (MSI-H CRC ~15% CD8 → whole-cohort `intermediate`). Filed.

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

### 3a. The CARD-DATA RULERS (v1.8.0) — how a card value becomes a graded read

Two rulers turn the raw CD8 fraction into something a consumer can weigh. Both are **verdict-INERT**: the
`immune_context_verdict` token is unchanged, byte-for-byte, by either.

**(i) CORROBORATION → `skill_report.confidence`.** The IMMUNE atom's `corroboration` tier is a function of
the ORTHOGONAL platforms, not a constant (it *was* the constant `moderate` until 2026-09-12, which made
`strong`/`weak` unreachable and the whole confidence field uninformative):

| tier | when | `confidence.level` | `claim_chips[0].conflict` |
|---|---|---|---|
| `high` | an orthogonal ABSOLUTE (Saltz H&E-DL TIL) or SPATIAL (co-localization) read AGREES | `strong` | `null` |
| `moderate` | CIBERSORT alone — no orthogonal coverage for the indication | `moderate` | `null` |
| `low` | an orthogonal platform CONTRADICTS | `weak` | the prose naming it |
| `unmeasured` | no CIBERSORT cohort (`data_unavailable`) | `insufficient` | `null` |

A CONTRADICTION always outranks a corroboration (weakest-link honesty). The two contradiction shapes:
`til_cibersort_agreement is False` (relatively CD8-rich but absolutely T-cell-sparse — the PRAD case, and
its mirror on a cold call) and `spatial_immune_phenotype == "excluded"` on a positive bulk read (effectors
in the leukocyte compartment but DEPLETED from the target-positive malignant nest — the inflamed-vs-excluded
distinction a bulk fraction structurally cannot make). ONE builder,
`_skills_common/immune_context_claims.orthogonal_discordance_text`, produces the string for all three
surfaces (`claim_chips[].conflict`, `key_signals.caveat`, `headline_block.top_tension.text`), so they
cannot drift apart.

**(ii) REFERENCE FRAME → `skill_report.claim_scalars.reference_frame`.** A STRING scalar (the tumor-presence
`homogeneity` precedent — the evidence_package claim_vector schema is `oneOf[string, object]`, and a string
renders verbatim in every consumer) gauging the value against its own frame: the CD8 share, its denominator
(LEUKOCYTE compartment, relative), `n_samples`, that the statistic is a cohort MEDIAN, the two pan-cancer
cuts, and the explicit disclaimer that the class is *"a pan-cancer RANK of the CD8 share, NOT an absolute
T-cell density and NOT a spatial or functional read"*. `"unmeasured"` (never `null`) when there is no cohort.

**`modality_scope` (the FOR-WHAT projection)** rides the spine as
`{"_refinements": {"bite_tce": favorable|conditional}}` — `favorable` on `immune_hot`, `conditional` on
`immune_intermediate`/`immune_cold` (effector absence is a TCE-EFFICACY risk, never a target veto), `null`
on `insufficient`. `spatial_immune_phenotype == "excluded"` caps it at `conditional`: **DEMOTE-ONLY**, since
the coloc products carry no donor floor and the immune rules are `opposing`, never `killer`.

**Not yet on the salience spec (filed):** `evidence_salience.py`'s `immune_context` SALIENCE_SPEC has no
`reference_frame` entry, so the frame reaches the spine and the renderers but not the salience ranking
(collides with PR #1309 `feat/cohort-percentile-meters`).

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
