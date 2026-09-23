# `r/legacy/` — quarantined, not production

Nothing in `../live/` (the production `four_cell_sensitivity` path — recount3 loader +
four-cell driver) calls anything in this directory. Two unrelated things live here, for two
different reasons — don't read "legacy" as "safe to delete":

## The single-cell GDC-STAR chain (`00_load_counts.R`, `01_build_design.R`,
## `02_combat_seq.R`, `03_deseq2.R`, `04_write_parquet.R`, `05_provenance.R`)

Retired. This is the original pre-recount3 pipeline (`--contrast tumor_vs_adjacent` in
`cli.py` / `../live/run_pipeline.R`) — it still runs if invoked, but no batch job or skill
invokes it. It is kept solely so
`methods/dge_deseq2/tests/test_byte_identity_vs_legacy_coadread.py` (the R4 carve-out's
byte-identity guard against `claude-oncology-skills/batch/expression_rna_COADREAD/`) has
something to run against. Do not extend it; do not route new indications through it.

## `00_load_xena_toil.R`

Not retired — dev-only and **currently unwired**. No production CLI path calls it; today it
is invoked only by ad-hoc scripts under `../../method_development/`
(`tss_covariate_comparison.R`, `ruvg_calibration.py`) for the Stage-1 cross-substrate
calibration work. Per the parent modernization plan
(analysis-methods#690, decision 2), Xena/Toil is slated to become its own standards-compliant
catalogued secondary-substrate derivation in S1b (#694) — at that point this file (or its
successor) is promoted OUT of `r/legacy/` into `r/live/`. It sits here only because "not
currently wired into a production CLI path" is the one thing it shares with the GDC-STAR
chain above; its future is the opposite of retirement.
