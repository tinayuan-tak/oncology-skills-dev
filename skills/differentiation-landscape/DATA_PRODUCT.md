# differentiation-landscape — finalized data product

The **I/O contract**: data wired IN, package emitted OUT, what is locked. Co-mutation/mutual-exclusivity
logic + history live in SKILL.md / run.py; this file is the data-product spec.

| | |
|---|---|
| **Skill** | `differentiation-landscape` |
| **Skill code version** | 1.12.0 |
| **Contract version** | 1.0.0 (emitted-output schema; versioned independently — see §4) |
| **Role** | `gating` (verdict = a co-mutation / mutual-exclusivity landscape class; all values hero-polarity `neutral` — a descriptive landscape, direction lives in the claim atom) |
| **Verdict field** | `headline.differentiation_verdict` (resolves on `co-mutation-and-mutual-exclusivity`) |
| **Output shape** | `data_package` |
| **Emitted schema** | `target-contracts/schemas/skills/differentiation-landscape.decision.schema.json` (generated, self-contained) |
| **Conformance target** | the FRESH replay emit (`test_differentiation_replay.py`; KRAS→`both_patterns_present`, FBXW7→`strong_cooccurring`); static `kras_coadread_decision.json` golden is **trimmed** → not a full-decision target |
| **Composition status** | `partial` — the sole reason is the unbuilt `patent-landscape` (see §5) |

---

## 1. Inputs — wired data (9 cards + 1 placeholder)

Every wired card traces card → method → data-catalog manifest → materialized S3 product. **All 9 wired
products LIVE**; no non-materialized manifests, no stale refs, no stale-metadata. `run.py` has no
`CARD_CONTEXT` map.

**Verdict-driving (1 → `differentiation.resolver.yaml`):**
`co-mutation-and-mutual-exclusivity` (`cooccurrence_fisher_pancohort`, `panel_intersect_mode: strict`) →
`pancohort-cooccurrence-fisher-v1` (~102 MB; TCGA MC3 ⊕ GENIE 19.0-public).

**Display-only / verdict-inert (8):** `stemness-context` (mRNAsi), `expression-clinical-association`
(recount3 TPM + PanCanAtlas clinical), `precog-prognostic-association` (PRECOG meta-Z),
`pathway-node-leverage` (DepMap 26Q1 + CORUM + MSigDB + Pharos; feeds cross-evidence agent, **not** the
differentiation resolver), `alteration-clinical-association` (MC3 MAF + clinical), `subtype-survival-association`
(`subgroup-catalog` → per-indication shard), `clinical-precedent` (AACT + DGIdb), `competitor-landscape`
(Open Targets 26.06, CC0).

**Placeholder (1, unbuilt):** `patent-landscape` — no card / method / manifest (PatBase-equivalent
licensing unresolved). Absent from `CARDS` + `cards_used`; it is the sole reason `composition.status: partial`.

---

## 2. Coverage & capability ceilings (contractual)

- **Pooled Fisher panel-intersect (the verdict):** pooled q-values only when BOTH target+partner sit on
  ALL contributing GENIE panels (166 panels); else per-source only (`pooled_eligible: false`). run.py
  deterministically fires a `_panel_absent_signal` (top_tension severity 3) when the pooled-eligible pair
  count is 0 but per-source > 0. Sources: TCGA MC3 (~10k aliquots / 33 types) + GENIE 19.0-public.
  Per-subgroup co-mutation is **BLOCKED** (`blocked_needs_per_sample_reader`).
- **Clinical-association facets:** ~20 OncoTree codes (`applies_when`); off-list → data_unavailable.
- **subtype-survival-association:** needs a registered TCGA subtype shard (COADREAD/NSCLC/ESCA/HNSC/PAAD).
  <!-- #1272: STAD dropped to match the reader's INDICATION_TO_TCGA_SUBTYPE_SHARD. A tcga-subgroup-assignments-stad-v1
  manifest exists (295 samples, ESCA-compatible schema) — wiring it is a verdict-affecting enhancement, tracked separately. -->
- **PRECOG:** 39 cancer-type columns, some approximate mappings (`precog_indication_approx`).
- **clinical-precedent (AACT):** framework `mesh_terms` crosswalk (9 iter-1 indications); off-crosswalk → insufficient.
- **competitor-landscape:** ChEMBL clinical+approved only (excludes preclinical/undisclosed/patent-stage).

---

## 3. Emitted output

`output_shape: data_package` → the standard `write_package` tree. `decision.json` top-level:
`skill · target · indication · question · generated_at · headline · cards · fired_rules · provenance ·
run_health` (+ optional synthesis). Contractual headline fields: `differentiation_verdict` (pinned enum),
`driving_rule_id`, the `skill_report` spine (`role: gating`, `polarity` neutral, `call` =
`differentiation_verdict`), `headline_block`, `claim_vector`, `key_signals`. All else schema-open.

---

## 4. Contract & versioning (what is locked)

Pinned by the generated, self-contained `differentiation-landscape.decision.schema.json` (gating-scalar
pins: `role: gating` + the 8-value `differentiation_verdict`/`call` enum = the differentiation resolver
set = `_DIFFERENTIATION_VERDICT_PHRASE` (has_cooccurring_driver removed as a dead rung, resolver v1.2.0);
no run.py mints; no polarity const; no bucket map). NOTE `role: gating` — as of gate v1.11.0 the
strong_mutually_exclusive verdict is a SUPPORTIVE positive_signal (grouped with genomic_alteration+
cis_coherence so it raises confidence but never independently mints `strong`); the other verdicts remain
advisory (reach the LLM synthesis + hypothesis agent, not the deterministic recommendation).

CI: fresh-replay conformance (`test_differentiation_replay.py`), schema-well-formedness +
static-golden-if-full (`tests/test_data_product_schema.py`, CI-fail-not-skip), cross-skill coverage
ratchet, target-contracts schema meta-test. Change policy: new verdict token → pins enum + regenerate
(minor); spine key → SHARED source (coordinate; major on rename); new facet → no schema change.

## 5. Known gaps & notes (non-blocking)

- **`patent-landscape` is a genuine PLACEHOLDER** (unbuilt — no card/method/manifest; PatBase-equivalent
  licensing unresolved). It is the sole reason `composition.status: partial`. A real capability gap, not a
  wiring bug — locking the data product does not resolve it; it is documented here as the known ceiling.
- **Doc-skew (stale narrative, not a data bug):** SKILL.md prose + `PARTIAL_STATUS_NOTE` still say
  `clinical-precedent` is "wired but NOT yet in this skill's cards_used" — it **is** in `cards_used` +
  `CARDS`. And `aact-oncology-trial-precedent-…-v1.yaml` description still says the clinical-precedent card
  is "placeholder_not_wired" (now `status: wired`). Doc reconciliation.
- **`pathway-node-leverage`** is in `rules_scope` but explicitly NOT wired to the differentiation resolver
  (its fired rules feed the cross-evidence-hypothesis agent only).
- **Logical alias:** `subgroup-catalog` (subtype-survival-association) → per-indication TCGA subtype shard.
