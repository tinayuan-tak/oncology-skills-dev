# Framework improvement — the routine iterative loop (runbook)

How the framework improves itself on a repeatable cadence. This generalizes the ad-hoc CASE-007…014
cadence into a standing procedure. It has two engines that feed one fix channel and one ground-truth judge.

- **Discovery** finds candidate gaps (where the framework is probably wrong).
- **Probe** decides, on live data, whether a candidate is real and *fixable from the data we have*.
- **Fix** lands through the card / rule / method channel — **never** through literature or a hand-tuned verdict.
- **Judge** is `target-contracts/vocabularies/known_target_calibration_set.yaml` — every fix is anchored there
  so it is regression-locked and a future regression turns CI red.

Non-negotiables (carry every iteration): literature stays `citable_in_nominations: false`
(`RISK_ASSESSMENT_INTEGRATION.md`); verdict-INERT changes keep a byte-stable spine; verdict-MOVING changes
regenerate the resolver golden + run the FULL skills suite + backtest the calibration set (a fix must not
regress a target it wasn't aimed at). Run live reads with `AWS_PROFILE=cbg /opt/conda/bin/python` (py3.12 —
pixi py3.14 silently returns false-`insufficient`). Work in a worktree; land via `land-pr`.

---

## Batch runner (SK#2303 Phase 0, WI-A)

`eval/loop/run_batch.py` is the per-subskill batch runner for the iteration loop (distinct from
`eval/run_known_target_panel.py`, which backtests the FULL composed `target-profile`). It invokes
one skill's `scripts/run.py --emit-envelope` per `target × indication` triple in a roster, under
pixi + `AWS_PROFILE=cbg`, JOBS-wide (default 3, ceiling 4 — 6-wide reboots the host, no swap), with
`--resume` and a run manifest:

```
pixi run python eval/loop/run_batch.py --skill tumor-presence --roster roster.json --jobs 3 --resume
```

Each emitted package is scored by a 4-clause preflight sentinel (`run_batch.preflight_sentinel`) —
a LIVENESS check (dead / partial / alive), never a verdict judgement: `n_cards_resolved > 0`;
`verdict != "insufficient"` AND `fired_rules > 0`; all four named envelope sections present
(`source_properties`/`integrated_properties`/`local_composites`/`l3d`); no card carries a
`read_error`. Output layout: `eval/loop/runs/iter-NNN-<sha>/<target>_<indication>.json` +
sibling `manifest.json`. See `eval/loop/tests/test_run_batch.py` for the synthetic dead/partial/
read-error/missing-section fixtures.

---

## The loop, one turn at a time

### 1. Discover a candidate gap (pick ONE source)
- **Literature↔deterministic discordance** — the `--literature` lane's per-axis `agreement_vs_omics`, harvested
  into the ranked ledger (`build_discordance_ledger.py`), diffed against `discordance_baseline.json`
  (`diff_discordance_ledger.py`), triaged in `CASE_LOG.md`. See `DISCORDANCE_LOOP.md`.
- **Calibration miss** — a `known_gap_watchlist` entry reading the wrong verdict, or a `reference_profiles`
  target whose deciding axis is `blind`/`partial` (the `blind_axis_load_bearingness` surface).
- **Class generalization** — once a fix lands, ask "what *else* is in this class?" (this is how CASE-014's
  EPAS1×VHL fix generalized into the WNT/Hippo conditional-dependency sweep). Enumerate biologically-motivated
  hypotheses of the same shape.

### 2. Probe on live data — BEFORE building
Reproduce the framework's read on the target, and (for a proposed new signal) probe whether the signal is
actually present and powered. **Call the existing method's own functions directly — no repo edit** — so a
"not there / underpowered" answer costs nothing:

```python
# example: is TARGET's dependency conditional on PARTNER loss? (reuses depmap_partner_conditional_dependency)
AWS_PROFILE=cbg /opt/conda/bin/python -c "
from onc_methods.depmap_partner_conditional_dependency import cli as pc
from onc_methods.depmap_chronos_distribution import cli as c1
v = pc.build_partner_deficiency_vector('26q1','PARTNER','lof_mutation')
chr_,_,_ = c1.load_depmap_files(release_pin='26q1', target_symbol='TARGET')
print(pc.compute_partner_stratification(chr_, v))"
```

Three probe outcomes, three actions:
- **Real + powered signal** (e.g. `partner_conditional_moderately/strongly_dependent`, q < α) → go to step 3.
- **Genuinely flat / underpowered** (`not_partner_stratified`, `insufficient_*`) → the omics is HONEST; the
  gap is NOT fixable from this data. Record it as a documented known-gap (step 3, doc-only) — do NOT force it.
- **Wrong axis / inverse polarity** (e.g. MDM2×TP53 reads reverse — MDM2 needs TP53-*WT*) → the fix needs a
  different mechanism than the one you reached for; document and defer.

### 3. Fix through the card / rule / method channel
Prefer, in order: **(a) data/curation** (a `partner_map.yaml` entry, a vocabulary term) — often the whole fix
when the lane already exists; **(b) method** (a new stratifier arm); **(c) rule/resolver** (a new rung). Check
first whether the machinery already exists and only lacks a data entry — CASE-014's entire fix was one
`partner_map` line because the resolver already rescued the class. Add a hermetic **lock test** for the
curated entry.

### 4. Anchor in the judge + verify end-to-end
- Add / flip the target in `known_target_calibration_set.yaml`. New documented miss → `known_gap_expected_fail`
  (`measured:false` reasoned-only if no snapshot yet). Landed fix → `must_not_veto` (`measured:true` + a
  captured `<target>_<ind>.<skill>.json` snapshot in `tests/calibration/snapshots/`).
- **Verify the flip through the whole stack** live (the skill pins the home method repo ahead of `PYTHONPATH`,
  so a skill-level verdict flip only propagates AFTER the method PR merges — re-run the skill post-merge).
- Log the case in `CASE_LOG.md` (surfaced-by / determination / fix / ratchet / status).

### 5. Lock & measure
- Confirm `eval/run_scorecard.py` non-stub steps stay green and `diff_discordance_ledger.py` is clean
  (0 NEW / 0 RESOLVED) after re-baselining.
- Regenerate `LOOP_HEALTH.md` (`loop_health.py`) — track loop precision so you know when to tighten a guard
  (the `concordant_over_flag` guard, CASE-013, was such a tightening).

---

## Cadence & governance
- **Weekly (advisory):** the `discordance-monitor.yml` workflow re-harvests, rebuilds the ledger, and flags NEW
  sharp gaps as `::warning` — the discovery trigger.
- **Per fix:** one worktree, one PR per repo, `land-pr`, set the registry entry to `merged` by hand.
- **Scope discipline:** the loop tightens the framework's *self-honesty and coverage* — it does not chase
  literature into verdicts. When the data says a gap is not fixable today, the honest documented known-gap IS
  the deliverable.

## Worked precedents (read these as templates)
- **CASE-013** — a guard-tightening (auto-demote `dismissed_concordant` noise): discovery from `LOOP_HEALTH`,
  verdict-INERT, measured by loop precision.
- **CASE-014** — a verdict-moving conditional-dependency fix (EPAS1×VHL): discordance → live probe → one
  `partner_map` line → resolver rescues → `must_not_veto` anchor + snapshot.
- **WNT/Hippo sweep** — class generalization: the same probe applied to APC→CTNNB1, NF2→TEAD1/WWTR1; curate the
  confirmed hits, skip the honest misses (YAP1×NF2 paralog-buffered, MAP2K1×NF1 flat).
