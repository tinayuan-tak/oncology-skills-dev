# Literature ↔ deterministic discordance loop

A ground-truth-anchored way to turn the verdict-INERT `--literature` lane into a systematic
source of candidate framework gaps. **Literature generates hypotheses; the calibration set
judges them.** Literature never moves a verdict (it stays `citable_in_nominations: false`,
target-contracts `docs/design/RISK_ASSESSMENT_INTEGRATION.md`).

```
harvest (--literature)  →  discordance ledger  →  triage  →  fix (card/rule/method)  →  scorecard
   Component 2               Component 1          Component 3     normal channel          the judge
                                  │
                                  └─ diff vs baseline  →  NEW sharp gaps  →  (weekly monitor)
                                     Component 4            review queue
```

## The matching resolution is the CLAIM-VECTOR AXIS, not the verdict (ledger v2)

The `--literature` lane computes `agreement_vs_omics` **per claim-vector axis** (DEP/SEL/COMUT/
SURVIVAL/DRUG/…), comparing against that axis's omics signal — NOT against the reduced gate verdict.
So the ledger joins each lane axis to its **claim atom** (`build_discordance_ledger._claim_atom`;
the lane's `axis_key` IS the claim-axis key) and classifies on the atom's measured-ness:
- a `contradicts` against a **measured** claim axis (signal present, incl. a measured floor `absent`
  / wrong-direction `negative`) + a verified citation → a real per-axis gap (calibration/verdict_rule);
- a `contradicts` against a **positively unmeasured** claim axis → blind-spot (you can't contradict an
  absent signal), not a verdict contradiction;
- no matching claim atom → cannot check → prior behavior (trust the lane).

Each row carries `claim_signal` / `claim_corroboration` / `claim_measured`. The **verdict** is retained
only as CONTEXT/priority (a contradiction on the axis that drove the gate is higher-stakes than one on a
context axis). This is why every landed fix (CASE-007 COMUT, 008 DRUG, 009 PHARMACOVIGILANCE, 010
SURVIVAL) was per-axis — the axis is the actionable unit.

## Component 4 — the monitored cadence

`eval/diff_discordance_ledger.py` diffs a fresh ledger's SHARP gaps (calibration_gap + verdict_rule_gap
— blind/staleness drift run-to-run under the LLM lane, so they are trended by COUNT only) against
`eval/discordance_baseline.json` (the sharp keys seen as of the last run). It surfaces NEW (appeared →
triage), RESOLVED (fix landed → prune the baseline), and coarse count deltas. The weekly
`.github/workflows/discordance-monitor.yml` re-harvests the calibration set, rebuilds the v2 ledger, and
diffs — emitting a `::warning` + artifact on NEW sharp gaps (advisory review queue; gated on the OIDC
role having S3 + Bedrock, skip-safe until then). Regenerate the baseline after a triage pass with
`diff_discordance_ledger.py --write-baseline`.

## Component 1 — the ledger (this branch, offline + byte-safe)

`build_discordance_ledger.py` is a **read-only** aggregator over a corpus of normalized harvest
records. It never calls an LLM and never mutates a decision. Each record:

```json
{"target": "MET", "indication": "LUAD", "skill": "genomic-alteration-profile",
 "sub_verdict": {"gate": "...", "verdict": "...", "driving_rule_id": "...", "fired_rule_ids": []},
 "claim_vector": {"AXIS": {"signal": "...", "corroboration": "..."}},
 "literature_synthesis": { <the --literature lane output> },
 "_provenance": {"model_id": "...", "prompt_hash": "..."}}
```

Run:

```bash
pixi run python eval/build_discordance_ledger.py \
    --corpus eval/fixtures/discordance_corpus.example.json \
    --calibration-set ../rnd-computational-biology-oncology-target-contracts/vocabularies/known_target_calibration_set.yaml \
    --out eval/discordance_ledger.json
```

### Gap taxonomy (ranked, most-actionable first)

| class | trigger | route |
|---|---|---|
| `calibration_gap` | verified `contradicts` on a **ground-truth** target | add a `known_gap_expected_fail` assertion, then fix |
| `verdict_rule_gap` | verified `contradicts` (≥1 verified citation) | resolver ladder / card class-vocab / method threshold |
| `blind_spot_gap` | `omics_blind` / `omics_unavailable` / a `blind_spots[]` entry | data-catalog / new card / new axis |
| `staleness_gap` | blind-spot on an axis the frozen atlas has no anchor for | **atlas session** (`atlas-rebuild`) |
| `confabulation_or_unverified` | `contradicts` with **no verified citation** | discard (non-reproducible LLM read) |

**Containment guard:** a `contradicts` read is only a real-gap candidate when it carries a
verified citation — mirrors `literature-risk-assessment/scripts/risk_rollup.py`
(`engine_literature_discordance`, escalate-only). Concordant (`agree`/`extends`) axes yield no
row.

## Component 2 — the harvest (`harvest_literature.py`, live)

Runs the fan-out (`_run_sub_skills`) with the `--literature` lane ON for a set of
(target, indication) pairs, **snapshots** each `literature_synthesis` (joined with its
sub-verdict + claim_vector) into a pinned corpus dir, then optionally feeds Component 1.
Because the lane is NOT bit-reproducible (Opus, model-default temperature), the ledger is
computed once over the frozen snapshot and reviewed — never re-rolled live. Snapshots and the
derived ledger are gitignored (run artifacts, not source).

```bash
AWS_PROFILE=cbg BEDROCK_AWS_PROFILE=cmp-dev pixi run python eval/harvest_literature.py \
    --use-calibration-pairs --literature-scope gating \
    --calibration-set ../rnd-computational-biology-oncology-target-contracts/vocabularies/known_target_calibration_set.yaml \
    --snapshot-dir eval/literature-snapshots --build-ledger
```

`--literature-scope gating` bounds Bedrock spend to the gating axes. Keep the pair list to the
calibration set (dozens), NOT a blind 15×213 fleet sweep — see the plan §5 for the staged
expansion. Env: `AWS_PROFILE=cbg` (live readers) + `BEDROCK_AWS_PROFILE=cmp-dev` (Opus lane).

## Component 3 — triage + fix (propose-only)

For each surviving row: read the cited abstracts + the deterministic card/rule trace; write a
`CASE_LOG.md` entry; if a real gap, open the fix on the correct layer (threshold →
analysis-methods classifier; label → card YAML; precedence → resolver YAML, **never**
arithmetic) + add the `known_gap_expected_fail` anchor; run `run_scorecard.py`; merge only on
gap-closed-with-no-regression via a human-reviewed PR.
