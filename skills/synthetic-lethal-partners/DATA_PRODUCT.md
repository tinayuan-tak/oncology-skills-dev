# synthetic-lethal-partners — finalized data product

The **I/O contract**: data wired IN, package emitted OUT, what is locked. This is an **auxiliary
(non-fan-out) skill**: a verdict-bearing nomination-gate **veto-suppressor**, not a target-profile
fan-out member. Logic + history live in SKILL.md / run.py; this file is the data-product spec.

| | |
|---|---|
| **Skill** | `synthetic-lethal-partners` |
| **Contract version** | 1.0.0 (emitted-output schema; versioned independently — see §4) |
| **Role** | `descriptive` — **GATELESS** (∉ target-profile `_SHORT_TO_GATE` → `skill_report.polarity: not_scored`). It never nominates; it *suppresses* a strong-dependency veto on a paralog-buffered target |
| **Verdict field** | `sl_partner_verdict ∈ {has_experimental_sl_partner, has_computational_sl_partner, no_curated_sl_partner, insufficient, data_unavailable}` (→ `skill_report.call`) |
| **Output shape** | `decision` (standard `write_package` tree; single-card spine) |
| **Emitted schema** | `target-contracts/schemas/skills/synthetic-lethal-partners.decision.schema.json` (generated, self-contained) |
| **Conformance target** | the **FRESH replay emit** — the real `run.py` over a frozen real reader summary (only the live dispatcher monkeypatched), via the `test_sl_partners_replay.py` harness. No hand-frozen decision fixture to go stale |

---

## 1. Inputs — wired data (1 card)

**LIVE.** Single-card veto-suppressor; the verdict rides the shared `synthetic_lethal_partners` resolver.

| card_id | method / manifest | role |
|---|---|---|
| `synthetic-lethal-partners` | `synthetic_lethal_partners` over `synlethdb-sl-partners-per-gene-v1` | verdict-bearing (curated SL partner presence + experimental-vs-computational tier) |

---

## 2. Coverage & capability ceilings (contractual)

- The verdict is a **NOMINATION-GATE VETO-SUPPRESSOR**: `has_experimental_sl_partner` is what lets a
  strong-dependency-veto'd but paralog-buffered target (e.g. SMARCA2←SMARCA4) escape the veto. A card
  reader drift that stops the experimental-partner rule firing silently **re-arms** that veto — guarded
  by `test_sl_partners_replay.py` (SMARCA2 experimental / STAG1 computational / CEACAM5 none).
- A curated SynLethDB SL edge is **context-aggregated**, NOT a validated/portable/druggable SL (SL is
  genotype-dependent + often non-replicating; KO ≠ pharmacological inhibition). Surfaced verdict-INERT via
  `sl_partner_confidence_caveat` (3-tier: computational-only / curated-not-validated / validated-precedent).
- Confidence is a **verdict→certainty sidecar** (experimental=moderate, computational/none=weak,
  collapsed=insufficient), not coverage-derived (the skill has no multi-axis claim_vector).

---

## 3. Emitted output

`output_shape: decision` → the standard `write_package` tree. `decision.json` top-level:
`skill · target · indication · question · generated_at · headline · cards · fired_rules · provenance ·
run_health · consolidation`. Contractual: the `skill_report` spine (`role: descriptive`,
`polarity: not_scored`, `call = sl_partner_verdict`), `headline_block` (verdict + certainty-sidecar
confidence + top-tension = the SL confidence caveat). Display fields (`sl_partner_class`,
`sl_partner_count`, `n_experimental_partners`, `has_experimental_partner`, `best_evidence_tier`,
`sl_partner_confidence_caveat`, `sl_partner_provenance`, `question_table`) are schema-open.

---

## 4. Contract & versioning (what is locked)

Pinned by the generated, self-contained `synthetic-lethal-partners.decision.schema.json`
(descriptive-scalar pins: `role: descriptive` + `polarity: not_scored` const + `call ∈ sl_partner_verdict`
enum; `headline.sl_partner_verdict` required + enum-pinned). CI: fresh-replay conformance
(`tests/test_data_product_schema.py`, CI-fail-not-skip), the cross-skill coverage ratchet, and the
target-contracts schema meta-test.

## 5. Known gaps & notes (non-blocking)

- Single-card skill: no multi-axis claim_vector, so `skill_report.claim_chips` is `[]` and confidence is
  the verdict-derived certainty sidecar (§2) rather than weakest-link over axes.
- The frozen reader fixtures are refreshed by the nightly-live re-freeze (card-behavior-matrix-nightly);
  refreeze if a card reader field the rules key on is renamed.
