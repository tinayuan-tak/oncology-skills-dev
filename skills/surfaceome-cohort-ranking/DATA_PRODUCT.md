# surfaceome-cohort-ranking — finalized data product

The **I/O contract**: data wired IN, package emitted OUT, what is locked. This is an **auxiliary
(non-fan-out) skill**: a per-indication whole-surfaceome **ranking scan**, not a target-profile fan-out
member. Logic + history live in SKILL.md / run.py; this file is the data-product spec.

| | |
|---|---|
| **Skill** | `surfaceome-cohort-ranking` |
| **Contract version** | 1.0.0 (emitted-output schema; versioned independently — see §4) |
| **Role** | `descriptive` — **GATELESS** (∉ target-profile `_SHORT_TO_GATE` → `skill_report.polarity: not_scored`). It emits **no verdict / no call** (`skill_report.call: null`); it is a percentile-context readout, never a nomination gate |
| **Facet field** | `headline.cohort_rank_class ∈ {top_1_percent, top_5, top_25, below_25_percent, data_unavailable}` \| `null` — where a queried `--target` lands in the tumor-up surfaceome ranking (a READOUT, not a gate). `null` in whole-cohort scan mode or when the target is not in the ranking |
| **Output shape** | `decision` (standard `write_package` tree; single-card scan spine) |
| **Emitted schema** | `target-contracts/schemas/skills/surfaceome-cohort-ranking.decision.schema.json` (generated, self-contained) |
| **Conformance target** | the **FRESH in-process emit** — the real `run.py main()` over a frozen REAL reader return (only the S3-backed `_load_ranking` stubbed), via `tests/test_data_product_schema.py`. No hand-frozen decision fixture to go stale |

---

## 1. Inputs — wired data (1 product)

**LIVE.** Single derived product, streamed by indication (pyarrow S3 pushdown on the `indication`
column). The skill hand-rolls `main()`; it does NOT resolve cards through the shared dispatcher — it
calls the method reader directly and degrades to `data_unavailable` on any read failure.

| card_id / product | reader | role |
|---|---|---|
| `surfaceome-cohort-ranking` / `surfaceome-cohort-ranking-per-indication-v1` | `methods.surfaceome_cohort_ranking.read.load_indication_ranking` | the per-indication whole-surfaceome effect-size ranking (pre-filtered at build: `cells_supporting >= min(2, cells_ran)`, `dominant_direction == up`) |

Two invocation modes (both emit the same contract):
- **whole-cohort scan** (`--indication COADREAD`): emits the full ranking; `target_context`/`cohort_rank_class` = null.
- **target-in-cohort** (`--indication COADREAD --target MSLN`): adds `headline.target_context` (rank, RNA/protein percentile, concordance) + the `cohort_rank_class` facet.

---

## 2. Coverage & capability ceilings (contractual)

- **No verdict, by design.** This is a biology-agnostic effect-size *ordering*; it makes no
  ADC-vs-TCE / druggability call (that lives in `surface-modality-fit` / `tractability-small-molecule`).
  The unified `skill_report` is therefore `call: null`, `role: descriptive`, `polarity: not_scored`.
- **Confidence is a data-availability sidecar** (`moderate` when the live product answered, `insufficient`
  when it degraded to `data_unavailable`) — the scan has no multi-axis claim_vector, so `skill_report.claim_chips`
  is `[]` and confidence rides a certainty sidecar rather than weakest-link over axes.
- The ranking is **per-indication** (no cross-indication rank pattern) and covers **only the
  SURFY-confirmed surfaceome** — not the full druggable-genome / TF-ome / secretome universe.
- Graceful degradation: any reader failure (creds / broken env / genuine product absence) →
  `n_ranked == 0`, `cohort_rank_class: null`, `run_health.status: degraded`, `_missing` card — an
  honest `data_unavailable`, never a crash.

---

## 3. Emitted output

`output_shape: decision` → the standard `write_package` tree (`decision.json` · `summary.yaml` ·
`provenance.yaml` · `figures/` · `tables/`). `decision.json` top-level:
`skill · target · indication · question · generated_at · headline · cards · fired_rules · provenance ·
run_health`. Contractual: the `skill_report` spine (`call: null`, `role: descriptive`,
`polarity: not_scored`), the `headline_block` (descriptive phrase + data-availability confidence + null
top-tension), the `cohort_rank_class` facet, and the run-level `provenance` (`build_subskill_provenance`
— skills sha, `data_mode: live`, resolved-release digests) + `run_health` telemetry that the hand-rolled
`main()` now backfills (the shared dispatcher would otherwise inject them). Display fields
(`n_ranked`, `robustness_filter`, `target_context`, `cards_available`, `cards_missing`) are schema-open.

---

## 4. Contract & versioning (what is locked)

Pinned by the generated, self-contained `surfaceome-cohort-ranking.decision.schema.json`
(gateless-descriptive pins: `skill_report.call` const `null` + `role` const `descriptive` + `polarity`
const `not_scored`; optional `headline.cohort_rank_class` enum). CI: fresh-emit conformance
(`tests/test_data_product_schema.py`, CI-fail-not-skip), the cross-skill coverage ratchet
(`skills/tests/test_data_product_lock_coverage.py`), and the target-contracts schema meta-test.

## 5. Known gaps & notes (non-blocking)

- **evidence_graph orphan (target-contracts gap):** the `surfaceome-cohort-ranking` card lacks a
  `measurement_type`, so the evidence-graph card↔question join treats it as an orphan (pinned in
  `surface-modality-fit`'s evidence-graph test). Contract-side gap, not an emit-shape defect; out of
  scope for this lock.
- The frozen reader fixture (`tests/fixtures/surfaceome_cohort_ranking_ranking.json`, MSLN/COADREAD =
  `top_5`) is a real captured `_load_ranking` return; refreeze it if the product's row schema or the
  `cohort_rank_class` binning changes.
- Iter-2 backlog (SKILL.md): cross-indication rank-summary product + modality-calibrated ranking. Neither
  changes this emitted contract.
