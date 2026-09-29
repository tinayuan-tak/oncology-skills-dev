# gene_id_authority

A shared, version-stripped **Ensembl gene-ID authority** across the two
`dge_deseq2` count substrates, plus the fail-loud join capability that lets a
cross-substrate comparison key on stable identity instead of the symbol string.

## Why (analysis-methods#699)

The four-cell `dge_deseq2` pipeline draws counts from two substrates annotated
against **different GENCODE releases**:

| substrate | release | symbol source |
|-----------|---------|---------------|
| recount3 `tcga-gtex-2023-01-04` | GENCODE v26 | Ensembl release-116 id-mapping (`ensembl-id-mapping-release-116-snapshot-2026-06-18`) |
| Xena/Toil `TcgaTargetGtex` | GENCODE v23 | `gencode.v23.annotation.gene.probemap` |

Both R loaders collapse counts to **HGNC symbol** and key their products by
`gene_symbol`, so any cross-substrate comparison (the S3c concordance QC, #732)
joins on the **symbol string**. That join is silently wrong two ways, both real
in this data:

- **symbol drift** — the same stable Ensembl gene has a different symbol in v23
  vs v116 (e.g. `ENSG00000000460` is `C1orf112` in v23, `FIRRM` in v116). A
  symbol join **drops** the gene: it looks one-arm-only.
- **symbol reuse** — a symbol string is reassigned to a *different* Ensembl gene
  between releases (e.g. `MEG8`, `UGT1A5`). A symbol join **mis-maps**: it fuses
  counts from two distinct genes.

The fix is to join on the release-invariant identity — the **unversioned
Ensembl gene ID** (`ENSG00000XXXXXXX`, `.split(".")[0]`). This module builds an
authority keyed on that id, carrying each release's symbol so drift/reuse are
explicit and auditable.

Against the real sources the authority has **67,070** join-relevant genes:
8,221 drift and 441 clean symbol reassignments would otherwise be silently
dropped or mis-mapped by the legacy symbol join.

## Scope

This is the **capability-first** slice of #699: authority table + audit +
coverage + a fail-loud join. It does **not** repoint the live R loaders' symbol
collapse onto the authority — that rewire is verdict-affecting and is sequenced
as a separate, separately-authorized step.

## Modules

- `build.py` — `build_authority(ensembl116_tsv, gencode_v23_probemap)` →
  `DataFrame`; `python -m methods.gene_id_authority.build --ensembl116-tsv ... --gencode-v23-probemap ... --out-parquet ...`. Emits one row per unversioned
  gene id in the **union** of the two sources (see the module docstring for the
  full schema).
- `harmonize.py` — `resolve_to_authority`, `coverage`, and `join_on_authority`.
  The join is **fail-loud**: a join resolving to fewer than `min_shared` genes
  **raises `ValueError`** rather than returning a silently empty frame that
  reads downstream as "the substrates agree on nothing."
- `audit.py` — `audit_authority`, `symbol_join_loss`, `coverage_report`,
  `full_report`; `python -m methods.gene_id_authority.audit --parquet ... --out-json ...` writes the #699 diagnostic bundle.
- `loader.py` — `load_gene_id_authority()`; local cache (md5-verified) → S3
  derived product (`gene-id-authority-v23-v116-v1`) → rebuild from the two
  catalogued sources. The md5 pin (`S3_MD5_PARQUET`) is the single source of
  truth against the paired data-catalog manifest.

## Published artifact

The authority parquet is published as data-catalog derived manifest
`gene-id-authority-v23-v116-v1` and md5-pinned in `loader.py`.

## Tests

`tests/methods/gene_id_authority/` re-derives the authority from raw source
snippets (`_fixtures.py`) — stored **raw input**, re-computed in the test, so no
assertion echoes a pre-computed blob. `test_harmonize_fail_loud.py` carries the
mutation teeth: neutering the fail-loud guard fails the empty-join,
`min_shared`, and wrong-column tests.
