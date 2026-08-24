# tumor-presence — quickstart

A first-run guide for a new contributor. `tumor-presence` answers: *"Is target X
present in indication Y's tumor tissue, and how does it distribute across cell lines,
tumor samples, protein, and single cells?"* See [SKILL.md](SKILL.md) for the full contract
and [CONTRACT.md](CONTRACT.md) for the design rationale (ladders, collapse invariants, the
single-cell layer, and version history).

## Prerequisites

1. **The three sibling repos checked out alongside each other** (the skill reads card
   specs + rules from them by relative path):
   - `rnd-computational-biology-oncology-claude-oncology-skills`  (this repo)
   - `rnd-computational-biology-oncology-target-contracts`        (card specs + rules)
   - `rnd-computational-biology-oncology-analysis-methods`        (method modules)

2. **`pixi`** on your `PATH` (the project's environment manager):
   ```
   export PATH="$HOME/.pixi/bin:$PATH"
   ```

3. **AWS access as the `cbg` profile** for the live card reads. The card data lives in
   `s3://onc-compbio/...`; only the `cbg` profile can read that bucket. Export it before
   a live run:
   ```
   export AWS_PROFILE=cbg
   ```
   (The default / cmp-dev profiles are DENIED on that bucket.)

## First run

From the repo root:

```
export AWS_PROFILE=cbg
python3 skills/tumor-presence/scripts/run.py \
  --target EPCAM --indication COADREAD \
  --out /tmp/tumor-presence/EPCAM-COADREAD
```

`EPCAM` / `COADREAD` is the canonical example — a broadly-present epithelial antigen in
the indication with the fullest card coverage (paired tumor-adjacent RNA, CPTAC protein,
single-cell, subtype shard), so nearly all 14 cards resolve.

`--target` is an HGNC gene symbol (uppercase); `--indication` is an AACR OncoTree code
(uppercase, e.g. `COADREAD`, `LUAD`, `BRCA`). Omit `--indication` for a target-only query.

## Reading the output

The run writes a data-package tree under `--out`:

- **`decision.json`** — the machine-readable answer. Start with `headline`:
  - `presence_verdict` — the one-word collapsed call (e.g. `broadly_high_expression`).
  - `driving_rule_id` — the exact rule that produced it (traceable to the rules YAML).
  - `presence_verdict_by_modality` — the per-`(measurement, sample_context)` breakdown
    (`bulk_rna/cell_line`, `bulk_rna/tumor`, `bulk_protein_ms/tumor`, `sc_rna/tumor`, …).
    **Always read this** — the collapsed headline is a roll-up; the per-lens buckets carry
    distinct evidence.
  - `cell_line_vs_tumor_discordant` — an invariant guard; should be `False`. If `True`,
    read `presence_interpretation_note` and the `bulk_rna/tumor` bucket.
- **`summary.yaml`** — per-card summary dicts.
- **`tables/`** — per-card summary-stat CSVs.
- **`figures/`** — per-card figures where a card emitter is wired.
- **`provenance.yaml`** — the audit anchor (which code + data posture produced the run).
- **`run.log`** — a timestamped tee of the run's stdout + stderr (card resolution, verdict,
  warnings), written by the shared dispatcher. Always on; a durable backend trace for development
  and provenance. Live terminal output is unchanged; each line carries a UTC timestamp + `OUT`/`ERR`
  tag. Follow a run live with `tail -f <out>/run.log`.

## Running the tests (no AWS needed)

The verdict logic is fully offline-testable — the tests feed synthetic fired-rule sets or
a frozen EPCAM/COADREAD replay, so no S3 credentials are required:

```
export PATH="$HOME/.pixi/bin:$PATH"
pixi run python -m pytest skills/tumor-presence/tests/ -q
```

Two cross-repo guards worth knowing about (they skip cleanly if `target-contracts` isn't
checked out alongside):
- `tests/test_per_modality_verdict.py::test_card_context_matches_target_contracts_specs`
  — asserts `CARD_CONTEXT` matches each card's `measurement:` / `sample_context:` tags.
- `../tests/test_card_field_conformance.py` — asserts every `get_card_field(...)` read
  names a field the card actually declares (catches silent field-name drift).

## Optional: LLM narration (`--synthesize`)

`--synthesize` attaches a natural-language narration of the deterministic verdict under
`decision["llm_synthesis"]`. It **never** changes the verdict — the decision is byte-identical
without it. It needs a Bedrock-entitled interpreter:

```
export AWS_PROFILE=cbg BEDROCK_AWS_PROFILE=cmp-dev
python3 skills/tumor-presence/scripts/run.py \
  --target EPCAM --indication COADREAD --out /tmp/tp/EPCAM-COADREAD --synthesize
```

If `anthropic[bedrock]` or the Bedrock profile is unavailable, the run still exits 0 and
`llm_synthesis` becomes a `_synthesis_error` note — the deterministic answer is unaffected.
