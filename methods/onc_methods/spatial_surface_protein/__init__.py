"""spatial_surface_protein — region-PROTEIN tumour-compartment abundance reader (GeoMx DSP).

Reads spatial-surface-protein-{indication}-v1 (data-catalog scripts/aggregate_spatial_region_protein.py;
NanoString GeoMx DSP protein). Reports the MEASURED in-situ protein abundance of a target in the TUMOUR
compartment vs the microenvironment (TME) — a distinct measured claim from the bulk-CPTAC×HPA copies/cell
estimate (surface-abundance-density / Axis-3). Region-level, NOT absolute copies/cell.

- read.py  — pyarrow predicate-pushdown reader + compartment assembler; INDICATION_TO_SURFACE_PROTEIN.
- stats.py — DONOR-is-replicate cross-donor-median roll-up + spatial_protein_class classifier.
- cli.py   — build_summary(target, indication) -> dict (live-reader entry) + METHOD_VERSION.
"""
