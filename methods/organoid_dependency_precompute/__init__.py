"""organoid_dependency_precompute — DepMap 26Q1 organoid-native CRISPR dependency substrate.

Producer (build.py) reads the organoid-only Chronos gene-effect matrix
(OrganoidGeneEffect.csv, 114 organoid ModelIDs × ~18k genes — a SEPARATE Chronos run
normalized WITHIN the organoid cohort, distinct from the cell-line CRISPRGeneEffect.csv)
and emits a tiny gene-sorted per-gene dependency summary parquet.

Reader (lookup.py::build_summary) does a single-gene predicate-pushdown read so the
`organoid-crispr-dependency` card can answer "is {target} a dependency in the organoid
panel?" WITHOUT scanning the 42 MB source matrix at render time.

WHY a separate organoid substrate (not the cell-line CRISPR cards): the organoid matrix
is Chronos-normalized against organoid peers, so its gene-effects are the DepMap-recommended
values for organoid-specific analysis. The two runs correlate at r≈0.99 on shared models, so
this is NOT an orthogonal dependency signal — it is the organoid-native READING of the same
screens, surfaced as its own facet because organoids retain 3D architecture / differentiation
that 2D lines lose. The cohort is GI-dominated (Esophagogastric, Pancreatic, Colorectal,
Breast), matching the iDAS indications.
"""
