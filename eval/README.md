# eval/ — the framework's test-and-iterate loop

The **durable** home for the framework's self-testing loop. Before this directory, the loop lived
under `~/dev/framework-runs/` on ephemeral EBS — a SageMaker restart wiped the gold truth-set and
the run harness. The instruments themselves now live in-repo; only run *outputs* stay ephemeral.

This directory **orchestrates** existing instruments — it does not reimplement them. The measures
live where they belong (structural health + calibration + discrimination + ledger in
`target-contracts`; the runs-clean smoke in `skills/_skills_common`); `eval/` is the single door.

## One command

```bash
python eval/run_scorecard.py
```

Runs every durable harness in one pass, writes `eval/scorecard.json`, prints a table, and exits
non-zero iff any non-stub step is red. This is both the human dashboard and a CI-grade gate.

| # | Step | What it checks | Owner |
|---|------|----------------|-------|
| 1 | `framework_health`   | structural WIRED? dashboard staleness | `target-contracts/validators/framework_health/` |
| 2 | `runs_clean_smoke`   | RUNS-CLEAN? subskill smoke projection | `skills/_skills_common/framework_health_smoke.py` |
| 3 | `calibration`        | per-target known-target regression (snapshots) | `target-contracts/tests/calibration/` |
| 4 | `discrimination`     | aggregate predictive validity + regression floors | `target-contracts/validators/validate_framework_discrimination.py` |
| 5 | `known_target_panel` | fresh nominations **+ signal vector** vs reference_profiles (score-only) | `eval/run_known_target_panel.py` |
| 6 | `eval_ledger`        | portfolio-memory artifact integrity | `target-contracts/validators/build_eval_ledger.py` |

### Interpreters

Steps span two repos with different envs (see `run_scorecard.py` docstring). Point the orchestrator
at the right interpreters when its own can't satisfy a step's imports (the step then reports ERROR,
never crashes the pass):

```bash
SCORECARD_CONTRACTS_PY=/usr/bin/python3 \
SCORECARD_SKILLS_PY=/opt/conda/bin/python \
  /opt/conda/bin/python eval/run_scorecard.py
```

## Regenerating the human-facing panel

```bash
eval/run_example.sh KRAS COADREAD full        # needs AWS_PROFILE=cbg + BEDROCK_AWS_PROFILE=cmp-dev
```

Writes under `$FRAMEWORK_RUNS_ROOT/examples/<TARGET>-<INDICATION>/` (default `~/dev/framework-runs`).
See `CONVENTION.md` for the layout and the canonical panel.

## The known-target backtest (Phase 2) — scores the SIGNAL VECTOR, not just the word

`run_known_target_panel.py` runs `target-profile --emit evidence-package` fresh over the durable
`reference_profiles` (target-contracts `known_target_calibration_set.yaml`) and scores the emitted
output — closing the discrimination harness's "measures curation, not fresh output" gap.

Because the framework's value is the **jointly-addressable signal substrate**, not the collapsed
recommendation word (the substrate-sufficiency principle), the panel captures the full **signal
vector** per target — per-axis verdict + graded claim atoms (`signal × corroboration × conflict`)
from `synthesis.claim_vectors` — and rolls up a substrate summary (axes measured, strong, conflicted,
recommendation/confidence tallies). The one-word recommendation is scored as just ONE facet; a
`validated_lane` target that comes back a hard `veto` is a fresh regression (gates red), an approved
target the framework now `nominate`s that curation called a silent-FN is surfaced as **drift** (flip
the calibration entry, don't fail).

**Positive/negative signal ledger** (`extract_signal_ledger`, per-target `signal_ledger`): the
signals are the product, so each target carries an explicit ledger of what argues FOR the target vs
AGAINST it, read from the substrate's directional fired-rule suffix convention
(`-supportive`/`-favorable` = positive; `-veto`/`-killer`/`-opposing`/`-warning` = negative;
`-neutral`/`-insufficient` = context). Each negative is tagged with its GATE STATUS — `surviving`
(drove a hold/veto), `suppressed` (fired but cleared by modality/context escape, e.g. a biologic's
`non_dependent`), or `within_axis` (shaped the axis verdict, not a gate kill). The rollup reports
avg positive / negative signal counts and the surviving-vs-suppressed negative split — the
substrate-fidelity headline (an LLM-free, deterministic read; synthesis adds prose, never signals).

```bash
# slow: populate/refresh packages (one live run per target; needs AWS_PROFILE=cbg)
python eval/run_known_target_panel.py --emit                 # all in-scope profiles
python eval/run_known_target_panel.py --emit --only KRAS DLL3 PARP1   # fast subset
# fast: score whatever packages exist + print the signal-substrate rollup (what run_scorecard calls)
python eval/run_known_target_panel.py
```

Composite / non-gene profiles (`CLDN18.2_LRRC15`, `CA19_9`, …) and heme indications with no framework
cohort are reported `out_of_scope` / coverage-gap, never silently passed.

## The iteration cadence (Phase 3)

Each turn: read the discrimination harness's `blind_axis_load_bearingness` (the missing axis costing
the most known targets — currently `surface_antigen_biology`, ≥10 blind) and the `silent_false_negatives`
split; close the top gap; flip its calibration assertion; tighten its floor; re-run this scorecard to
prove improvement with no regression. Qualitative misses that the scorecard can't encode go in
`CASE_LOG.md`.

## Remaining (Phase 2 tail + beyond)

- **Full live sweep**: run `run_known_target_panel.py --emit` over all ~26 in-scope profiles to
  populate the packages the scorecard scores (done incrementally; the score step reports coverage).
- **Deciding-axis capture**: map each profile's `deciding_axis` to a claim-vector axis (reuse the
  discrimination harness's `deciding_axis_family`) to score the LIVE `deciding_axis_coverage` — did
  the framework's signal vector actually SEE what decides this target?
- **Release pins**: pin each run to a framework-version + data-release tag so the eval-ledger's
  cross-release trend view (verdict-flip-on-data-update) lights up.
- **`validate_gold`** (risk_rollup per-dimension bins) is a complementary, narrower harness; its
  original per-dimension gold_seed is not reconstructable from `reference_profiles` (different label
  grain) — revive separately if the risk-bin check is wanted.
