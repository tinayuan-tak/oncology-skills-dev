"""depmap_protein_abundance — cell-line protein-abundance distribution method.

The PROTEIN twin of depmap_expression_distribution. Reads the DepMap 26Q1
proteomics Gygi Lab CCLE TMT MS matrix (harmonized_MS_CCLE_Gygi.csv,
ModelID x UniProt-accession, ~12,558 proteins) and emits the
`cellline-protein-abundance` card summary: per-target abundance distribution across
cell lines + per-lineage breakdown, primary categorical protein_expression_class
∈ {broadly_high | broadly_moderate | lineage_restricted | sub_broad_detection |
broadly_low | data_unavailable} (the cellline-rna-distribution distribution vocab plus
sub_broad_detection, for a middle-band detection fraction whose per-lineage breakdown is
unavailable — NOT the tumor-vs-normal contrast vocab of tumor-protein-abundance-cptac).

The substrate that catches the RNA-high / protein-absent false-positive the
measurement-modality taxonomy names. Resolves target→UniProt accession via the
source's target_resolution sidecar (matrix columns are accessions); lineage via
Model.csv (read-side groupby, per-ModelID).

Modules:
    cli  — loaders (matrix + sidecar + Model.csv) + distribution classifier + CLI
    read — read_target_summary: the live-mode dispatcher entry
"""

METHOD_VERSION = "0.1.0"

from .read import read_target_summary  # noqa: E402,F401
