"""Kinome-atlas PWM lookup — per-kinase position×amino-acid PWM matrix
producer + loader, melted to long-format Parquet.

Produces the `kinome-atlas-pwm-lookup-v1` derived-manifest artifact for
the data-catalog: one row per (kinase × position × amino_acid) with the
norm_scaled PWM score (log-odds enrichment). Covers 396 kinases:
- 303 Ser/Thr kinases from Johnson 2023 (Nature 613:759-766)
- 93 Tyr kinases from Yaron-Barir 2024 (Nature 629:1174-1181):
    - 78 canonical Tyr kinases
    - 15 non-canonical Tyr/dual-specificity kinases (with `_TYR` suffix:
      BMPR2_TYR, LIMK1/2_TYR, MKK4/6/7_TYR, MYT1_TYR, NEK10_TYR,
      PDHK1/3/4_TYR, PINK1_TYR, TESK1_TYR, TNNI3K_TYR, WEE1_TYR).
      These live in the same `tyrosine_all_norm_scaled_matric` sheet as
      the 78 canonical entries — they are NOT a separate MOESM.

This module is INDEPENDENT of `kinome_atlas_prediction`. That sibling
module reads the PRE-COMPUTED PREDICTED-SUBSTRATES tables (Johnson Supp
Table 3 + Yaron-Barir Supp Table 3, ~89k phosphosites × 303 kinases wide)
and produces the `kinome-atlas-long-edges-v1` derived parquet for answering
"which kinases were predicted to phosphorylate this KNOWN phosphosite?".

This module reads the RAW PWM MATRICES (Johnson Supp Table 2 + Yaron-Barir
Supp Table 2) and produces the `kinome-atlas-pwm-lookup-v1` derived
parquet for answering "score this ARBITRARY substrate sequence against
kinase Y's PWM specificity model." Downstream consumers score arbitrary
sequences against the atlas without re-parsing xlsx.

Modules:
    build   — parse both xlsx workbooks, melt norm_scaled matrices,
              emit per-row Parquet. Entry point for the derived-manifest
              producer.
    loader  — S3-first with md5-verify caching; mirrors
              methods/dge_deseq2/gene_lengths.load_gene_lengths shape.
"""
METHOD_VERSION = "0.1.0"
