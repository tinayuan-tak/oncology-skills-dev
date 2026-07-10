"""Kinome-atlas PWM lookup — per-kinase position×amino-acid PWM matrix
producer + loader, melted to long-format Parquet.

Produces the `kinome-atlas-pwm-lookup-v1` derived-manifest artifact for
the data-catalog: one row per (kinase × position × amino_acid) with the
norm_scaled PWM score (log-odds enrichment). Covers 381 canonical kinases:
- 303 Ser/Thr kinases from Johnson 2023 (Nature 613:759-766)
- 78 canonical Tyr kinases from Yaron-Barir 2024 (Nature 629:1174-1181)

Downstream consumer: kinome_atlas_prediction method (Phase D
mechanism-and-pharmacology). Instead of re-parsing the two source Excel
workbooks + selecting the norm_scaled sheet each time, downstream methods
load a single compact parquet keyed by (kinase, position, amino_acid).

Modules:
    build   — parse both xlsx workbooks, melt norm_scaled matrices,
              emit per-row Parquet. Entry point for the derived-manifest
              producer.
    loader  — S3-first with md5-verify caching; mirrors
              methods/dge_deseq2/gene_lengths.load_gene_lengths shape.

## Scope note

Non-canonical Tyr kinase PWMs (15 kinases mentioned in Yaron-Barir 2024)
are NOT included in this v1 lookup — the paper does NOT publish them as
a separate supplementary MOESM. This lookup covers the 381 canonical
kinases only. If the 15 non-canonical PWMs are later located (they may
be embedded in an ED figure), a v2 sibling manifest can extend coverage.
"""
METHOD_VERSION = "0.1.0"
