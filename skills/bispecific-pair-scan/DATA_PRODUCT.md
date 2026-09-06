# bispecific-pair-scan — finalized data product

The **I/O contract**: data wired IN, package emitted OUT, what is locked. This is an **auxiliary
(non-fan-out) skill**: a logic-gated antigen-**PAIR** tumor-selectivity **ranking scan** (candidate
generation), NOT a target-profile fan-out member and NOT a per-target verdict. Logic + history live in
SKILL.md / run.py; this file is the data-product spec.

| | |
|---|---|
| **Skill** | `bispecific-pair-scan` |
| **Contract version** | 1.0.0 (emitted-output schema; versioned independently — see §4) |
| **Role** | `descriptive` — **GATELESS** (∉ target-profile `_SHORT_TO_GATE` → `skill_report.polarity: not_scored`). A RANKING scan: it nominates pairs to confirm, it does not gate a nomination |
| **Verdict field** | **none** — the output is a RANKED pair table, not a scalar verdict, so `skill_report.call` is **null** by contract (`role: descriptive`, `polarity: not_scored`) |
| **Output shape** | `decision` (standard `write_package` tree; single hand-built scan-card spine — this skill does not resolve cards through the dispatcher) |
| **Emitted schema** | `target-contracts/schemas/skills/bispecific-pair-scan.decision.schema.json` (generated, self-contained) |
| **Conformance target** | the **FRESH emit** — the real `run.py` driven end-to-end offline (an in-test `pair_selectivity_gate` double supplies the ranked rows; no live S3), plus the `data_unavailable` degrade case, via `tests/test_data_product_schema.py`. No hand-frozen decision fixture to go stale |

---

## 1. Inputs — wired data

**LIVE.** Not a card-resolver skill — it drives `methods.pair_selectivity_gate.scan_partner_set` over
per-sample TCGA-tumor vs GTEx-normal TPM and ranks each `--target × partner` pair under `--gate`
(AND / OR / NOT). The default partner universe is the ~40 clinical-seed surface antigens (`--partners`
overrides).

| declared input (product_id) | role |
|---|---|
| `tcga-tumor-tpm-recount3-long-v1` | per-sample tumor TPM (gate-positive tumor fraction) |
| `gtex-tpm-recount3-long-v1` | per-sample normal TPM (essential- + full-normal-panel denominators) |

Both are DECLARED as the scan-card's `input_manifest_ids` (stable across a read miss), so the emitted
`provenance.resolved_releases` fingerprint holds even on the `data_unavailable` degrade. AND-gate pairs
additionally carry a best-effort single-cell same-cell confirmation (`samecell_confirmation`) from the
`sc-samecell-coexpr` cube; absent for the indication → `samecell_avidity_call: data_unavailable`.

---

## 2. Coverage & capability ceilings (contractual)

- **Candidate GENERATION, never a call.** The framework spine is single-target (no `target_pair`
  grain), so pair selectivity is emitted as a ranked derived list OUTSIDE the per-target verdict spine.
  `skill_report.call` is null by contract — a ranked table is not a scalar verdict.
- **HARD ceiling — bulk ≠ same-cell.** Bulk co-expression in a SAMPLE is necessary but NOT sufficient
  for same-CELL co-expression (avidity — what an AND-gate bispecific needs). Surfaced verdict-inert as
  the mandatory `skill_report.top_tension` avidity caveat on **every** emit; AND-gate pairs attach the
  best-effort same-cell confirmation, never a fabricated one.
- **TCGA-cohort bound.** An indication that maps to no TCGA study resolves an honest empty ranked list
  (`n_pairs_scored: 0` → `run_health.status: degraded`, the data_unavailable contract).
- **Bounded BACKGROUND job** (~60-90s/pair — the GTEx per-sample read dominates); keep the partner set
  to dozens (a surfaceome / clinical-seed subset), not thousands.

---

## 3. Emitted output

`output_shape: decision` → the standard `write_package` tree. `decision.json` top-level:
`skill · target · indication · question · generated_at · headline · cards · fired_rules · provenance ·
run_health`. Contractual: the `skill_report` spine (`role: descriptive`, `polarity: not_scored`,
`call: null`), and a `headline_block` (top-ranked-pair `honest_phrase` — or the honest data_unavailable —
+ a scan-coverage `confidence` sidecar + the avidity caveat as `top_tension`). Display fields are
schema-open: the headline's `gate · n_partners_scanned · n_pairs_scored · top_pair{partner, selectivity,
tumor_fraction, call, samecell_avidity_call, samecell_both_fraction} · cards_available · cards_missing`,
the full `ranked_pairs` list inside `cards[].summary`, and `run_health.{n_partners_scanned,
n_pairs_scored, load_error}`.

---

## 4. Contract & versioning (what is locked)

Pinned by the generated, self-contained `bispecific-pair-scan.decision.schema.json` (gateless-descriptive
pins: `skill_report.call` type `null` + `role` const `descriptive` + `polarity` const `not_scored`; the
full `skill_decision` envelope required, including top-level `provenance` + `run_health`; `skill` const
`bispecific-pair-scan`). CI: fresh-emit conformance (`tests/test_data_product_schema.py`,
CI-fail-not-skip), the cross-skill coverage ratchet (`skills/tests/test_data_product_lock_coverage.py`),
and the target-contracts schema meta-test.

---

## 5. Known gaps & notes (non-blocking)

- Same-cell avidity (CELLxGENE Census) is the documented next layer; until it lands for an indication,
  AND-gate pairs carry `samecell_avidity_call: data_unavailable` — the bulk verdict + avidity caveat
  still stand, never a fabricated confirmation.
- Single ranked-scan spine (no multi-axis claim_vector) → `skill_report.claim_chips` is `[]` and
  `confidence` is a scan-coverage sidecar (`weak` bulk-only / `moderate` when same-cell confirmed /
  `insufficient` when zero pairs scored), not weakest-link over axes.
- The fresh-emit conformance harness drives `run.py` with an in-test `pair_selectivity_gate` double (no
  live S3 / credentials) — it locks the ENVELOPE SHAPE, which is sound here because the skill is gateless
  (there is no verdict to guard, unlike the resolver-replay guards on the verdict-bearing skills). The
  scan science is unchanged; a live run assembles the identical envelope.
