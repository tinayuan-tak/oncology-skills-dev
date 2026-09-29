"""depmap_prism_precompute — batch precompute for PRISM E6 card.

Assembles a gene-level activity aggregate from two PRISM release lineages
(OncologyReference 25Q4 primary + Repurposing 24Q2 fallback) into a single
frozen derived parquet keyed by gene_symbol. The thin `depmap_prism_activity`
lookup card reads one row per target via pyarrow predicate pushdown.

Output derived product:
    s3://onc-compbio/data-catalog/derived/depmap-prism-activity-v1/
        prism_activity_per_gene.parquet
        manifest.yaml

Cross-release merge convention (locked 2026-07-01):
    - Per-compound activity stats are computed within each release's OWN
      cell-line panel — never mixed across releases.
    - Each compound row carries `source_release` ∈ {oncref-25q4, repurposing-24q2}.
    - When a compound appears in BOTH releases (BRD-ID matches), the OncRef
      25Q4 measurement wins (higher-quality dose-response; clinical priority
      library).
    - `top_compounds` is ranked across both releases by their own activity metrics.

No live-read role; this is a data-product producer only. See
`methods.depmap_prism_activity` for the card-side thin lookup.
"""
