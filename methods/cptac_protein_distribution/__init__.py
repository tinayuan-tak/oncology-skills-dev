"""cptac_protein_distribution — subtype-stratified CPTAC tumor-protein panorama.

The PROTEIN analogue of tcga_gtex_expression_distribution's tumor-rna-distribution-by-subtype:
per-molecular-subtype CPTAC whole-cell-lysate protein abundance (tumor-vs-reference log2 ratio) for
a target, computed WITHIN each stratum's member aliquots. Consumes the CPTAC protein per-sample
product (cptac_protein_deg.read_per_sample) + a CPTAC subgroup-assignment shard
(cptac-subgroup-assignments-coadread-v1, MSI_H/MSS) via the shared subgroup_common machinery.

DESCRIPTIVE / verdict-inert — surfaced side-by-side with the RNA subtype panorama; never averaged
across measurement types, never moves a presence verdict. Today COADREAD (MSI_H/MSS) is the only
landed CPTAC assignment shard; other indications return subtype_axis_available:false (honest).
"""
