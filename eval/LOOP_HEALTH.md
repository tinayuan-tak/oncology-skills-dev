# Discordance loop health — precision of the candidate-gap flagging

_Instrument (process step 6), not a gate. Source: `eval/loop_dispositions.yaml` (the CASE_LOG triage as data). Regenerate after each triage pass: `python eval/loop_health.py --out eval/LOOP_HEALTH.md`._

- **SHARP candidate gaps flagged:** 32
- **precision_strict** (fixed + real_deferred): **0.438**
- **precision_incl_scope** (+ scope caveats, honest wins): **0.562**
- **noise_rate** (concordant over-flag + data-absent): **0.438**

## Disposition counts

| disposition | n |
|---|---|
| dismissed_concordant | 10 |
| fixed | 9 |
| real_deferred | 5 |
| dismissed_data_absent | 4 |
| dismissed_scope | 4 |

## By skill

| skill | dispositions |
|---|---|
| differentiation-landscape | dismissed_data_absent:2, fixed:2 |
| functional-requirement | dismissed_concordant:3, real_deferred:1 |
| mechanism-and-pharmacology | dismissed_concordant:1, dismissed_data_absent:1, real_deferred:1 |
| on-target-safety-liability | dismissed_scope:4 |
| surface-modality-fit | dismissed_concordant:2, real_deferred:1 |
| tractability-small-molecule | dismissed_concordant:3, dismissed_data_absent:1, fixed:7, real_deferred:2 |
| tumor-selectivity | dismissed_concordant:1 |

## Read

- The **containment guard is working**: 0 confabulation rows reached the sharp set (the `≥1 verified citation` rule filters non-reproducible LLM contradictions upstream).
- The dominant NOISE source is **`dismissed_concordant`** — the lane flags `contradicts` on an axis whose omics signal already AGREES with the literature direction. The ledger-v2 claim-vector alignment now carries `claim_signal` per row, so the next guard tightening is to AUTO-DEMOTE a lane `contradicts` whose claim atom already matches the literature direction (direction cross-check), cutting this noise without touching the verdict.
- `dismissed_scope` (pharmacovigilance, CASE-009) are honest measured-axis contradictions the verdict already covers conservatively — resolved with scope caveats, counted separately.

## Governance checkpoint (RISK_ASSESSMENT_INTEGRATION.md §4-5)

Literature remains **`citable_in_nominations: false`** — verdict-blind. Re-assessed against the five `clinical_validation` preconditions: (1) corpus pin — NO (the lane is Opus, model-default temperature, `_prompt_hash` drifts); (2) source determinism — NO; (3) null≠MEDIUM — n/a for this lane; (4) drop commercial/translational — n/a; (5) staleness TTL — NO. **Verdict: NO-GO stands.** Every discordance fix to date landed via the card/rule/method channel + the ground-truth calibration set, never the literature lane. Do not flip the stance until (1),(2),(5) are met.
