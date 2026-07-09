"""TMbed-based topology-prediction method module.

Produces the `topology-predictions-tmbed-v1` derived manifest for the
data-catalog. Per-gene predicted membrane topology + extracellular domain
boundary + signal-peptide + orientation, computed by TMbed (Bernhofer & Rost
2022, Apache-2.0) against the catalog's UniProt SwissProt human snapshot.

Companion spec:
    oneTakeda/rnd-computational-biology-oncology-data-catalog:
        specs/topology-predictions-tmbed-v1.md

Modules:
    prepare_fasta  — DAT.gz → cleaned FASTA (Biopython SwissProt parser)
    reduce_predictions — TMbed .pred (format 3) → per-gene topology Parquet
"""
METHOD_VERSION = "0.1.0"
