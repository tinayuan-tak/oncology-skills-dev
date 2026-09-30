"""Shared version-stripped Ensembl gene-ID authority across dge_deseq2 substrates.

Produces the `gene-id-authority-v23-v116-v1` derived-manifest artifact for the
data-catalog: one row per unversioned Ensembl gene ID in the UNION of the two
dge_deseq2 count substrates' native annotations —

  * recount3 tcga-gtex-2023-01-04 — GENCODE v26, symbols via Ensembl release-116
    id-mapping (`ensembl-id-mapping-release-116-snapshot-2026-06-18`)
  * Xena/Toil TcgaTargetGtex        — GENCODE v23, symbols via the v23 probemap
    (`xena-toil-tcga-target-gtex-snapshot-2026-09-20`)

— carrying each release's symbol so cross-substrate joins can key on the stable
Ensembl id instead of the drifting/reused HGNC symbol string (analysis-methods#699).

Capability-first scope: this builds the authority table + drift/reuse audit +
coverage report + the fail-loud join the S3c concordance QC (#732) consumes. It
does NOT repoint the live R loaders' symbol collapse — that rewire is
verdict-affecting and sequenced separately.

Modules:
    build      — build the authority DataFrame from the two source files; entry
                 point for the catalog derived-manifest producer
    loader     — S3-catalogued read of the derived parquet with md5 verification
                 (mirrors gencode_exon_index.loader)
    harmonize  — resolve native ids onto the authority + fail-loud join
    audit      — symbol-drift / symbol-reuse audit + per-substrate coverage
    product    — resolve a symbol-keyed dge_deseq2 product back onto the
                 authority gene_id (the join key #732 consumes), fail-loud
"""

METHOD_VERSION = "0.1.0"
