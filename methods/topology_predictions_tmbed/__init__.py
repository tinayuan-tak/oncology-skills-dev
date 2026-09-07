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
    classify — derive topology_class from raw fields (read-side)
    read — read_target_summary: the live-mode dispatcher entry (added 2026-07-19; the
           compose-dashboard dispatcher imports this — it was missing, so the
           surface-topology card resolved unavailable)
"""

METHOD_VERSION = "0.1.0"

from .read import read_target_summary  # noqa: E402,F401
