"""depmap_paralog_aggregator — paralog-buffering signal from DepMap screens.

Aggregates DepMap PARIS 2024 paralog CRISPR screens + Sanger Paralog Screen 2023
+ Ensembl paralog annotation into a per-gene paralog-buffering summary. A
target's dependency-hardening / kill-switch risk is captured categorically for
the paralog-buffering card (Phase C-adjacent).

Companion:
    data-catalog:manifests/derived/depmap-paralog-buffering-per-gene-v1.yaml

Consumer: paralog-buffering evidence card (Phase C-adjacent) via
functional-requirement skill extension.
"""
METHOD_VERSION = "0.1.0"
