# framework-runs — output-workspace convention

Canonical location for **curated** target-profile dev outputs. The harness (`run_example.sh`)
lives durably in the repo (`eval/`); the OUTPUTS it produces live in the ephemeral workspace
`~/dev/framework-runs/` (override `FRAMEWORK_RUNS_ROOT`). A SageMaker restart wipes the outputs,
never the harness. Throwaway scratch the user can't easily reach lives in `~/scratch`, not here.

## Layout

```
$FRAMEWORK_RUNS_ROOT/            # default ~/dev/framework-runs
  examples/                      # the canonical panel — what we show the team
    <TARGET>-<INDICATION>/
      latest -> <YYYY-MM-DD>-<runtype>     # symlink to the newest run
      <YYYY-MM-DD>-<runtype>/              # one run snapshot
        evidence_package.json
        subskills/           # all sub-skill packages
        grounded_*.json      # ONLY when run with --ground (not default)
        MANIFEST.{json,md}
        target_profile.{md,html}
        nomination.json
        provenance.yaml
        figures/
        run.log              # argv + full run log
        run.console.log      # stdout/stderr capture
  experiments/              # iteration / one-offs — SAFE TO DELETE ANY TIME
    <YYYY-MM-DD>-<slug>/
  _archive/                 # staged for deletion; empty it once confirmed
```

## Rules

1. **Every full package** is produced by `eval/run_example.sh` — never hand-rolled paths.
2. **Naming**: the `<TARGET>-<INDICATION>` example folder never repeats in the leaf;
   the leaf is `<YYYY-MM-DD>-<runtype>`. `runtype` ∈ {`full`, `verdict-only`, `review`}.
3. `examples/<X>/latest` always points at the most recent run for that example.
   Gallery / review tooling should glob `examples/*/latest`.
4. **Experiments** (dashboard mockups, one-off probes, previews) go in `experiments/`,
   never in `examples/`. They carry no `latest` and are disposable.
5. **The canonical panel** is the target set the scorecard regenerates for the human-facing
   check: `KRAS-COADREAD`, `KRAS-LUAD`, `DLL3-SCLC`, `ERBB2-STAD`, `BRAF-COADREAD`,
   `EGFR-LUAD`, `MET-LUAD`, `CLDN18-STAD` (positives, a hold, and the documented
   MET-LUAD false-negative — a range that exercises the verdict spine).

## Which code runs

`run_example.sh` executes `run.py` from `$TP_RUN_PY` (override via env). Default is the committed
checkout this script lives in (`$CLAUDE_ONCOLOGY_SKILLS_ROOT/skills/target-profile/scripts/run.py`),
i.e. current `v2-architecture`. The Phase-0 output-fidelity fixes (LLM XML-dialect recovery #849,
`homogeneity` "unmeasured" sentinel, machine-mode-scoped envelope `SystemExit`) are on trunk, so
the older `~/dev/wt-tp-verify` pin is no longer needed.

Interpreter: system conda (`/opt/conda/bin/python`, override `TP_PY`) — it carries both the card
stack (`openpyxl`, `lifelines`, `pyreadr`, `gseapy`) and `anthropic[bedrock]`; the pixi env lacks
`anthropic` and crashes the synthesis tail. `AWS_PROFILE=cbg` (account 557690623046) is forced for
S3 reads; `BEDROCK_AWS_PROFILE=cmp-dev` for the Bedrock synthesis / `review` runtype.
