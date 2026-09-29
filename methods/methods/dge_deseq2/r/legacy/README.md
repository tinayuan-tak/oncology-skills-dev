# `r/legacy/` — quarantined, not production

Nothing in `../live/` (the production `four_cell_sensitivity` path — recount3 loader +
four-cell driver) calls anything in this directory. What lives here is the retired
single-cell GDC-STAR chain, kept for one narrow reason — don't read "legacy" as
"safe to delete":

## The single-cell GDC-STAR chain (`00_load_counts.R`, `01_build_design.R`,
## `02_combat_seq.R`, `03_deseq2.R`, `04_write_parquet.R`, `05_provenance.R`)

Retired. This is the original pre-recount3 pipeline (`--contrast tumor_vs_adjacent` in
`cli.py` / `../live/run_pipeline.R`) — it still runs if invoked, but no batch job or skill
invokes it. It is kept solely so
`methods/dge_deseq2/tests/test_byte_identity_vs_legacy_coadread.py` (the R4 carve-out's
byte-identity guard against `claude-oncology-skills/batch/expression_rna_COADREAD/`) has
something to run against. Do not extend it; do not route new indications through it.

## `00_load_xena_toil.R` — PROMOTED to `../live/` (S1b, #694)

The Xena/Toil loader used to sit here (dev-only, unwired). S1b (analysis-methods#694)
made it a standards-compliant catalogued **secondary/diagnostic** substrate, so it now
lives at `../live/00_load_xena_toil.R` and is reachable through
`../live/run_pipeline.R --contrast four_cell_sensitivity --substrate xena_toil` (and
`scripts/run_indication_batch.sh` with `SUBSTRATE=xena_toil`). Its products carry a
`-xenatoil` id infix and are NOT verdict inputs. See that file's header + the S1b PR.
