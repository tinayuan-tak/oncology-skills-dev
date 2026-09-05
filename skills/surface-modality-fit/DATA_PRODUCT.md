# surface-modality-fit — finalized data product

The **I/O contract**: data wired IN, package emitted OUT, what is locked. ADC/TCE composition + history
live in SKILL.md / run.py; this file is the data-product spec.

| | |
|---|---|
| **Skill** | `surface-modality-fit` |
| **Skill code version** | 1.9.0 |
| **Contract version** | 1.0.0 (emitted-output schema; versioned independently — see §4) |
| **Role** | `gating` (verdict can move the nomination; polarity dynamic 3-band with a **killer** override fired only by `fit_class == neither_viable`) |
| **Verdict fields (multi-layer)** | `headline.fit_class` (base composed call = `skill_report.call`) · `surface_modality_verdict` (resolved post safety/density/shed/escape downgrade — the sharpest signal, surfaced as top tension) · `surface_modality_verdict_by_modality` ({adc, bite_tce, antibody(, pmhc_tce)}) |
| **Output shape** | `data_package` |
| **Emitted schema** | `target-contracts/schemas/skills/surface-modality-fit.decision.schema.json` (generated, self-contained) |
| **Conformance target** | the FRESH replay emit (`test_surface_modality_replay.py`; CEACAM5/TACSTD2/ERBB2 fit_class=`both_viable` / smv=`adc_preferred_tce_unsafe`; WT1 fit_class=`neither_viable` / smv=`pmhc_tce_supported`) |

---

## 1. Inputs — wired data (surface substrate + safety + enrichment)

All consumed cards trace card → method → data-catalog manifest → materialized S3 product; **all LIVE** per
the wiring trace. `run.py` has no `CARD_CONTEXT` map. Grouped by role:

**Verdict-driving core (composed `fit_class` + resolver rungs):** `adc-tce-modality-fit` (the composed
substrate call; fuses topology + surfaceome family), `surface-topology-and-ptm`, `surfaceome-family-classification`,
`structure-features-static`, `surface-abundance-density`.

**Safety / density / shed downgrade arms (drive `surface_modality_verdict`, not `fit_class`):**
`normal-tissue-liability` (HPA-IHC), `sc-normal-celltype-expression` + `sc-surface-normal-safety` (scRNA/CITE-seq
normal), `shed-ectodomain-liability` (soluble-antigen sink), `modality-therapeutic-window`.

**Antigen-escape / presentation / patient-selection (verdict-inert or arm-scoped):** `tumor-scrna-celltype-expression`
(within-tumor escape), `pmhc-presentation`, `modality-exon-window`, `mutation-stratified-surface`,
`pathway-stratified-surface`, `cd-antigen-backbone`, `protein-surface-evidence` (CSPA), `sc-surface-rna-protein-concordance`,
`rna-protein-concordance-tumor`, `copy-number-distribution`.

---

## 2. Coverage & capability ceilings (contractual)

- **`fit_class` keys on topology + surfaceome family** (the modality-substrate call); it emits
  `neither_viable` (an honest negative) — not `insufficient` — when upstream is thin.
- **Safety/density/shed refinements** downgrade the resolved `surface_modality_verdict` (TCE-unsafe /
  below-density-floor / shed-sink / escape-risk) without changing the base `fit_class` — so the one-word
  `call` is not falsely reassuring; the downgrade rides as the top tension.
- `pmhc_tce_supported` is the inverse positive: a `neither_viable` fit_class with experimentally-validated
  pMHC epitopes surfaces a TCE-supported path.
- Structure does NOT feed the biologics `fit_class` by design (it drives the sibling small-molecule call);
  `endocytosis_confidence: unmeasured` is surfaced as an honest ADC gap (topology, not endocytosis, gates ADC).

---

## 3. Emitted output

`output_shape: data_package` → the standard `write_package` tree. `decision.json` top-level:
`skill · target · indication · question · generated_at · headline · cards · fired_rules · provenance ·
run_health` (+ optional synthesis). Contractual headline fields: `fit_class` (pinned 7-value enum — the
`skill_report.call`), `surface_modality_verdict` (pinned 17-value enum — the resolved top-tension signal),
`surface_modality_verdict_by_modality` ({adc, bite_tce, antibody(, pmhc_tce)} arms), the `skill_report`
spine (`role: gating`, dynamic `polarity` with `killer` on `fit_class==neither_viable`, `call` = `fit_class`),
`headline_block`, `claim_vector` (FIT/TOPOLOGY/DENSITY/SAFETY/SHED), `key_signals`. All else schema-open.

---

## 4. Contract & versioning (what is locked)

Pinned by the generated, self-contained `surface-modality-fit.decision.schema.json` (gating multi-layer
pins: `role: gating`; `fit_class`/`call` = the composed adc-tce-modality-fit vocabulary;
`surface_modality_verdict` = the resolver set; `surface_modality_verdict_by_modality` typed-open; no
polarity const — dynamic with a killer override at the emitter). CI: fresh-replay conformance
(`test_surface_modality_replay.py`, validates BOTH fit_class + surface_modality_verdict), schema
well-formedness + static-golden-if-full (CI-fail-not-skip), cross-skill coverage ratchet, target-contracts
schema meta-test. Change policy: new verdict token → pins enum + regenerate (minor); spine key → SHARED
source (coordinate; major on rename); new facet → no schema change.

## 5. Known gaps & notes (non-blocking)

- **`fit_class` enum over-pin (minor, to tighten):** the pinned `fit_class` enum includes `insufficient`,
  but the composed dispatcher never emits it for fit_class (it emits `data_unavailable` on missing inputs;
  `insufficient` is a `surface_modality_verdict` value). Harmless (permissive — no false-reject) but a
  fidelity inaccuracy; remove `insufficient` from the `fit_class` `$def` in a follow-up regen.
- **Two distinct vocabularies, deliberately:** `fit_class` is capitalized (`ADC_preferred`/`TCE_preferred`);
  `surface_modality_verdict` is lowercase (`adc_preferred`/…). Do not conflate — `skill_report.call` is the
  base `fit_class`; the resolved downgrade lives in `surface_modality_verdict` (top tension).
- **`surface_modality_verdict_by_modality` keys are {adc, bite_tce, antibody}** (+ optional `pmhc_tce`) —
  the binder arms, not literally "ADC/TCE"; left typed-open (per-arm enums documented in the wiring trace).
