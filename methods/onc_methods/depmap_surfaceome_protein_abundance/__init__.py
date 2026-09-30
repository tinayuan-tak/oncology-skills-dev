"""depmap_surfaceome_protein_abundance — DepMap Consortium Surfaceome 26Q3 PAIRED DIA-MS method.

The THIRD-PLATFORM sibling of depmap_protein_abundance (Gygi TMT MS) and procan_protein_abundance
(ProCan DIA/SWATH). Reads the derived long/tidy product depmap-surfaceome-paired-per-protein-v1 (the
64-line gastric/esophageal surfaceome PAIRED whole-cell + surface-enriched DIA-MS release) and emits
the SAME cellline-protein-abundance card summary shape as the two siblings — computed on the
SURFACE-enriched abundance layer — PLUS the genuinely-new surface-vs-wholecell enrichment /
localization rollup that is the unique value of the paired assay.

It REUSES the Gygi sibling's shape + classifier + symbol->UniProt resolution
(compute_summary / classify_protein_abundance / _symbol_to_uniprot_map from
depmap_protein_abundance.cli) rather than forking them, so a change to the distribution vocabulary or
classifier lands in all three platforms at once. Platform differences (documented in cli.py, not
forked):
  * the abundance layer is `surface_log2` (log2 surface-enrichment DIA-MS intensity); the emitted field
    keeps the sibling's `*_log2_abundance_panel` NAME for cross-platform field parity;
  * no OncotreeLineage crosswalk in this product, so per-lineage stratification is unavailable
    (per_lineage_stats == []); lineage is a v2 join;
  * the product ships no all-protein median-null sidecar, so the null is computed on-read (one cached
    2-column scan + groupby-median over surface_log2) for allgene_percentile + the panel-relative
    broadly_high cutoff.

NEW capability — surface-vs-wholecell enrichment rollup: per (gene, cell-line) enrichment_log2ratio
gated by the Hu-2021 SVM proteomics_predicted_enriched / proteomics_pr_auc, rolled up to
median_enrichment_log2ratio, fraction_lines_predicted_enriched, median_pr_auc, and a
surface_localization_class (surface_confirmed / mixed / intracellular_contaminant / insufficient).
Verdict-INERT display (the card ships interpretation=rules_pending).

Modules:
    cli  — loaders (per-protein pushdown + on-read all-protein null) + enrichment rollup + load_and_classify + CLI
    read — read_target_summary: the live-mode dispatcher entry
"""

METHOD_VERSION = "0.1.0"

from .read import read_target_summary  # noqa: E402,F401
