# Phase-0 certainty-layer gate — A/B review rubric

**What Phase 0 changed:** the per-axis how-solid (certainty) block — coverage + single-rule
call-fragility per decision-relevant axis, plus the blind (un-evidenced) axes — is now routed into
the Tier-3 synthesis prompt. It was already computed (`_fragility_facet`, written to
`nomination.json`) and then **dropped at the prompt boundary**; Phase 0 delivers it to the LLM.

**Objective (locked):** narrative fidelity + analyst confidence calibration. The block is
**verdict-inert** — it does not move the recommendation, the gate, or the audited confidence tier
(those are clamped/floored deterministically). It changes only how confident and how honest the
prose is about thin/fragile axes.

**The gate decision this rubric supports:** proceed to Phase 1+ **only if** a reviewer confirms a
non-noisy, correct improvement in how thin/fragile/blind axes are described. If the prose is
unchanged or the deltas are noise, **STOP** — the equal-weight-words defect was not
decision-relevant and the rest of the certainty layer is not worth building.

## How to run

```
export AWS_PROFILE=cbg BEDROCK_AWS_PROFILE=cmp-dev
cd skills/target-profile
python3 tools/ab_fragility_synthesis.py --out-root ~/scratch/ab-fragility
# then read ~/scratch/ab-fragility/ab_report.md
```

## Panel (fixed — keep in lockstep with `ab_fragility_synthesis.py::PANEL`)

| target | indication | why in the panel (certainty regime probed) |
|---|---|---|
| KRAS | COADREAD | broad-coverage, robust call — treatment should NOT manufacture doubt |
| ERBB2 | BRCA | amplification/driver mix — coverage differs across alteration classes |
| MET | LUAD | known thin/blind axes on some indications — treatment should name them |
| FOLR1 | OV | de-differentiating surface antigen — presence coverage / proxy quality matters |
| CDK4 | GBM | expected fragile/contested on ≥1 decision axis — treatment should flag fragility |

## Pass/fail gates (hard, checked by the harness)

- **G0 — verdict-inert.** For every pair, the deterministic spine (`overall_recommendation`,
  `confidence`, every sub-verdict) is **byte-identical** across arms. The harness fails non-zero if
  not. A mismatch is a **blocker**, not a review item — the block leaked into the decision.

## Reviewer scorecard (qualitative — the actual gate)

For each pair, compare CONTROL vs TREATMENT prose and score each dimension **better / same / worse**:

1. **Names thin/blind axes.** Does TREATMENT explicitly call out low-coverage or blind
   decision-relevant axes that CONTROL glossed over or stated with false certainty?
2. **Calibrated confidence language.** Is TREATMENT's confidence hedging *proportional* to the
   evidence (more hedged where coverage is thin, not uniformly)? CONTROL tends to sound equally
   confident everywhere.
3. **MNAR discipline.** Does TREATMENT correctly treat a blind axis as *absence of evidence*
   (widened uncertainty) rather than narrating it as a negative finding? A treatment that reads a
   blind axis as "the target failed axis X" is a **regression**, not an improvement.
4. **No false doubt on robust axes.** On KRAS/COADREAD (broad coverage), TREATMENT must NOT
   invent fragility the fragility indices don't support. Manufactured hedging = worse.
5. **No scalarization.** TREATMENT must not average/sum the per-axis certainties into a single
   made-up score, and must not contradict the deterministic recommendation.

### Decision rule

- **PROCEED to Phase 1** iff ≥3 of the 5 panel pairs score **better** on dimensions 1–2 with **zero
  regressions** on dimensions 3–5, confirmed by the reviewer as signal (not LLM-run noise — if in
  doubt, re-run the pair; the spine is stable so only prose varies).
- **STOP** otherwise. Record the artifact (`ab_report.md`) and the scorecard in the PR either way,
  so the gate decision is auditable.

## Notes

- Synthesis is nondeterministic; a single-run prose delta can be noise. The spine, however, is
  stable across runs — so any *decision* difference would be a bug, and prose differences should be
  judged for *systematic* improvement, re-running a pair if a delta looks like sampling noise.
- This harness is deliberately out of CI (Bedrock + cbg S3 + slow). It is a manual, reviewed gate.
