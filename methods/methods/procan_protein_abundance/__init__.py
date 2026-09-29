"""procan_protein_abundance — ProCan-DepMapSanger DIA/SWATH cell-line protein-abundance method.

The SECOND-PLATFORM sibling of depmap_protein_abundance (Gygi TMT MS). Reads the derived
long/tidy product procan-cellline-protein-abundance-per-protein-v1 (a CC-BY-4.0, commercial-use
clean DIA-NN MaxLFQ complement to the DUA-gated Gygi substrate) and emits the SAME
cellline-protein-abundance card summary shape, so the two form a clean cross-platform pair for the
tumor-presence display layer.

It REUSES the Gygi sibling's shape + classifier + symbol->UniProt resolution
(compute_summary / classify_protein_abundance / _symbol_to_uniprot_map from
depmap_protein_abundance.cli) rather than forking them, so a change to the distribution vocabulary or
classifier lands in both platforms at once. Platform differences (documented in cli.py, not forked):
  * abundance column is `log_abundance` (DIA-NN MaxLFQ log-intensity) not `log2_abundance`;
  * the cell-line axis is Sanger SIDM ids with no DepMap-ModelID/OncotreeLineage crosswalk yet, so
    per-lineage stratification is unavailable (per_lineage_stats == []); lineage is a v2 (SIDM->ACH);
  * the product ships no all-protein median-null sidecar, so the null is computed on-read (one cached
    2-column scan + groupby-median) for allgene_percentile + the panel-relative broadly_high cutoff.

Modules:
    cli  — loaders (per-protein pushdown + on-read all-protein null) + load_and_classify + CLI
    read — read_target_summary: the live-mode dispatcher entry
"""

METHOD_VERSION = "0.1.0"

from .read import read_target_summary  # noqa: E402,F401
