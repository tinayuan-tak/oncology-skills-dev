"""spatial_region_rna — region-RNA tumour-compartment expression reader (GeoMx DSP WTA).

Reads spatial-region-rna-{indication}-v1 (data-catalog scripts/aggregate_spatial_region_rna.py;
NanoString GeoMx DSP Whole Transcriptome Atlas). Reports the MEASURED, spatially-resolved RNA expression
of a target in the TUMOUR compartment vs the microenvironment (TME) — region-level (ROI = a segmented
tissue region), a distinct measured claim from BOTH the dissociated scRNA products (no architecture) and
the region-PROTEIN products (in-situ antibody signal, not RNA).

- read.py  — pyarrow predicate-pushdown reader + compartment assembler; INDICATION_TO_REGION_RNA.
- stats.py — DONOR-is-replicate cross-donor-median roll-up + spatial_rna_class classifier.
- cli.py   — build_summary(target, indication) -> dict (live-reader entry) + METHOD_VERSION.
"""
