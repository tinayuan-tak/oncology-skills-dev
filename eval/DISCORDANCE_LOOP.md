# Literature ↔ deterministic discordance loop

A ground-truth-anchored way to turn the verdict-INERT `--literature` lane into a systematic
source of candidate framework gaps. **Literature generates hypotheses; the calibration set
judges them.** Literature never moves a verdict (it stays `citable_in_nominations: false`,
target-contracts `docs/design/RISK_ASSESSMENT_INTEGRATION.md`).

```
harvest (--literature)  →  discordance ledger  →  triage  →  fix (card/rule/method)  →  scorecard
   Component 2               Component 1          Component 3     normal channel          the judge
```

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

## Component 2 — the harvest (live, gated on go-ahead)

Extends `run_known_target_panel.py` (or a sibling `harvest_literature.py`): run the
calibration-set targets with the lane ON, **snapshot** each `literature_synthesis` into a pinned
corpus (mirror `eval/known-target-packages/`), then feed Component 1. Because the lane is NOT
bit-reproducible (Opus, model-default temperature), the ledger is computed once over a frozen
snapshot and reviewed — never re-rolled live. Env: `AWS_PROFILE=cbg` (emit) +
`BEDROCK_AWS_PROFILE=cmp-dev` (Opus lane). Cost is bounded to the ~dozens of calibration targets
(NOT a blind 15×213 sweep — see the plan §5 for the staged expansion).

## Component 3 — triage + fix (propose-only)

For each surviving row: read the cited abstracts + the deterministic card/rule trace; write a
`CASE_LOG.md` entry; if a real gap, open the fix on the correct layer (threshold →
analysis-methods classifier; label → card YAML; precedence → resolver YAML, **never**
arithmetic) + add the `known_gap_expected_fail` anchor; run `run_scorecard.py`; merge only on
gap-closed-with-no-regression via a human-reviewed PR.
