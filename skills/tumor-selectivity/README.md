# tumor-selectivity — quickstart

A first-run guide for a new contributor. `tumor-selectivity` answers: *"How selectively
is target X expressed in indication Y's tumor vs normal tissue, and how robust is that call
across independent comparators — bulk, single-cell, and in-situ spatial?"* See
[SKILL.md](SKILL.md) for the full contract.

The key idea: tumor-vs-origin over-expression (the "axis-A" call) is **necessary but not
sufficient**. A gene can be strongly up in tumor yet still be a bad target — because it is
also broadly expressed in *normal* tissue (no therapeutic window), or because the bulk signal
is driven by *stroma* rather than the malignant cells. This skill layers those checks on top of
the fold-change.

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
export AWS_PROFILE=cbg SKILLS_READ_POOL=process
python3 skills/tumor-selectivity/scripts/run.py \
  --target CEACAM5 --indication COADREAD \
  --out /tmp/tumor-selectivity/CEACAM5-COADREAD
```

`SKILLS_READ_POOL=process` is optional — it reads the ten cards in a forked process pool for the
fastest cold run (~15% faster; safely degrades to threads on any failure, byte-identical output).
Omit it and the reads still run concurrently on a thread pool. See SKILL.md § Performance.

`CEACAM5` / `COADREAD` is the canonical clean-selective example — a field-effect epithelial
antigen with a real therapeutic window and a malignant-cell-intrinsic single-cell signal, so all
ten cards resolve and no veto fires.

`--target` is an HGNC gene symbol (uppercase); `--indication` is an AACR OncoTree code
(uppercase, e.g. `COADREAD`, `LUAD`, `BRCA`).

### Three contrasting reads worth running

| Target | Indication | What it demonstrates |
|--------|-----------|----------------------|
| `CEACAM5`  | `COADREAD` | **Clean-selective** — `field_effect_tumor_selective`, no veto; sc `caf_low` (malignant-intrinsic). |
| `TACSTD2` (TROP2) | `COADREAD` | **Veto downgrade** — axis-A `strong_tumor_selective` but broadly normal → `selective_but_broadly_normal`. |
| `GAPDH`   | `COADREAD` | **Housekeeping trap** — huge fold-change (log2FC ~4.8) caught by the therapeutic-window veto. |
| `APC`     | `COADREAD` | **Not selective** — a down-regulated tumor suppressor → `not_selective`. |

## Reading the output

The run writes a data-package tree under `--out`:

- **`decision.json`** — the machine-readable answer. Start with `headline`:
  - `selectivity_class` — the **resolved** (post-veto) call. Possible values include
    `strong_tumor_selective`, `modest_tumor_selective`, `field_effect_tumor_selective`,
    `selective_but_broadly_normal` (the veto outcome), `not_selective`, `data_unavailable`.
  - `driving_rule_id` — the exact rule that produced it (a veto rule when downgraded).
  - `axis_a_selectivity_class` — the **raw** tumor-vs-origin class *before* the veto. Compare it to
    `selectivity_class`: if they differ, a normal-breadth veto fired (read the window fields).
  - **Single-cell + spatial facets** (verdict-inert): `sc_tumor_expression_class`,
    `sc_malignant_detection_fraction`, `sc_caf_vs_malignant_class` (malignant-cell-intrinsic vs
    stroma), `spatial_rna_class`, `spatial_coloc_class`,
    `spatial_normal_epithelium_adjacency_fraction` (bystander risk), `spatial_protein_class`.
    **Always read these** — they tell you whether a "selective" bulk call is real tumor-cell biology
    or a microenvironment artifact.
- **`summary.yaml`** — per-card summary dicts (the full four-cell log2FC/q-value detail, the
  therapeutic-window ratios, the per-compartment single-cell fractions).
- **`tables/`** — per-card summary-stat CSVs.
- **`provenance.yaml`** — the audit anchor: skill version, `skills_repo_sha`, and every resolved
  data-product release digest.
- **`run.log`** — a timestamped tee of the run's stdout + stderr (card resolution, veto firing,
  verdict, warnings), written by the shared dispatcher. Always on; a durable backend trace for
  development and provenance. Live terminal output is unchanged; each line carries a UTC timestamp +
  `OUT`/`ERR` tag. Follow a run live with `tail -f <out>/run.log`.

## Running the tests (no AWS needed)

The verdict logic is fully offline-testable — the tests feed synthetic fired-rule sets or a frozen
CEACAM5 / TACSTD2 replay, so no S3 credentials are required:

```
export PATH="$HOME/.pixi/bin:$PATH"
pixi run python -m pytest skills/tumor-selectivity/tests/ -q
```

- `tests/test_verdict.py` — pins the rule-id → verdict mapping and **all three normal-breadth
  veto arms** (window, pan-normal, sc-normal), plus the verdict-inert density facet contract.
- `tests/test_selectivity_replay.py` — replays the frozen real reader summaries through the real
  `run.py`, guarding against **reader field-name drift** that would silently collapse the verdict
  (false negative) or silently kill a veto (false positive — TROP2 reading as tumor_selective).

Refreshing the frozen fixtures (needs AWS): `pixi run python
skills/tumor-selectivity/tests/freeze_fixture.py --target CEACAM5 --indication COADREAD`.

## Optional: LLM narration (`--synthesize`)

`--synthesize` attaches a natural-language narration of the deterministic verdict under
`decision["llm_synthesis"]`. It **never** changes the verdict — the decision is byte-identical
without it. It needs a Bedrock-entitled interpreter with `anthropic[bedrock]` installed (the default
skills pixi env does not include it, so under pixi it degrades gracefully to a `_synthesis_error`
note; run it under a system Python that has the package):

```
export AWS_PROFILE=cbg BEDROCK_AWS_PROFILE=cmp-dev
python3 skills/tumor-selectivity/scripts/run.py \
  --target CEACAM5 --indication COADREAD --out /tmp/tvn/CEACAM5-COADREAD --synthesize
```
