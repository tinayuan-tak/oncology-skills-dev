# Discordance loop health — precision of the candidate-gap flagging

_Instrument (process step 6), not a gate. Source: `eval/loop_dispositions.yaml` (the CASE_LOG triage as data). Regenerate after each triage pass: `python eval/loop_health.py --out eval/LOOP_HEALTH.md`._

- **SHARP candidate gaps flagged:** 29
- **precision_strict** (fixed + real_deferred): **0.483**
- **precision_incl_scope** (+ scope caveats, honest wins): **0.621**
- **noise_rate** (concordant over-flag + data-absent): **0.379**
- **auto_demoted** (concordant-over-flag guard removed upstream, excluded from n_sharp): **3**

## Disposition counts

| disposition | n |
|---|---|
| fixed | 9 |
| dismissed_concordant | 7 |
| real_deferred | 5 |
| dismissed_data_absent | 4 |
| dismissed_scope | 4 |
| auto_demoted_concordant | 3 |

## By skill

| skill | dispositions |
|---|---|
| differentiation-landscape | dismissed_data_absent:2, fixed:2 |
| functional-requirement | auto_demoted_concordant:1, dismissed_concordant:2, real_deferred:1 |
| mechanism-and-pharmacology | dismissed_concordant:1, dismissed_data_absent:1, real_deferred:1 |
| on-target-safety-liability | dismissed_scope:4 |
| surface-modality-fit | auto_demoted_concordant:1, dismissed_concordant:1, real_deferred:1 |
| tractability-small-molecule | auto_demoted_concordant:1, dismissed_concordant:2, dismissed_data_absent:1, fixed:7, real_deferred:2 |
| tumor-selectivity | dismissed_concordant:1 |

## Read

- The **containment guard is working**: 0 confabulation rows reached the sharp set (the `≥1 verified citation` rule filters non-reproducible LLM contradictions upstream).
- The dominant NOISE source was **`dismissed_concordant`** — the lane flags `contradicts` on an axis while its own holistic read agrees. **LANDED (guard-tightening):** `build_discordance_ledger` now AUTO-DEMOTES a lane `contradicts` to the non-sharp `concordant_over_flag` class whenever the lane's OWN `overall_consistency == concordant` — an isolated axis contradiction against a concordant summary is an internal over-flag. This keys off the lane's self-consistency, NOT a `claim_signal`-direction heuristic: direction alone is not separable here (`absent`+supporting-lit and `strong`+supporting-lit each occur in BOTH real gaps — MET/COMUT, PARP1/COND — and concordant noise), whereas `overall_consistency==concordant` isolates the noise with 0 real-gap collisions on the pinned 37-row corpus (4 rows demoted: DLL3/SEL, FOLR1/TOPOLOGY, XPO1/DEGRADER, SCD1/DENSITY). Verdict-INERT; literature untouched. Residual `dismissed_concordant` (lane `partially_concordant`) stays in the queue by design — separating those requires biology the lane fields do not carry, and a broader rule would demote real gaps.
- `dismissed_scope` (pharmacovigilance, CASE-009) are honest measured-axis contradictions the verdict already covers conservatively — resolved with scope caveats, counted separately.

## Governance checkpoint (RISK_ASSESSMENT_INTEGRATION.md §4-5)

Literature remains **`citable_in_nominations: false`** — verdict-blind. Re-assessed against the five `clinical_validation` preconditions: (1) corpus pin — NO (the lane is Opus, model-default temperature, `_prompt_hash` drifts); (2) source determinism — NO; (3) null≠MEDIUM — n/a for this lane; (4) drop commercial/translational — n/a; (5) staleness TTL — NO. **Verdict: NO-GO stands.** Every discordance fix to date landed via the card/rule/method channel + the ground-truth calibration set, never the literature lane. Do not flip the stance until (1),(2),(5) are met.
