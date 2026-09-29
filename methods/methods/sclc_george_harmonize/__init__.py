"""sclc_george_harmonize — SCLC (George 2015) FPKM → recount3-axis long product + NAPY strata.

Steps 2 + 3 of the SCLC subtype-presence vertical (step 1 = ingestion, data-catalog #212,
cbioportal-sclc-ucologne-2015). SCLC is NOT a TCGA study, so tumor-presence's subtype axis
was substrate-blocked for it; this package builds the substrate.

  build_tpm_long.py  — FPKM → TPM (per-sample re-normalization) → log2(TPM+1), mapped onto
                       the ensembl_gene_id axis via the ensembl-116 resolver, emitted as a
                       gene-sorted long product matching tcga-tumor-tpm-recount3-long-v1's
                       schema (study='SCLC'). → sclc-george-tpm-long-v1.
  build_napy_shard.py — derive SCLC-A/N/P/Y strata from ASCL1/NEUROD1/POU2F3/YAP1 (argmax with a
                       minimum-expression floor so marker-low samples are honestly uncommitted),
                       emitted as a subgroup-assignment shard. → sclc-subgroup-assignments-v1.

CAVEAT (documented at ingest): George is hg19/FPKM; after FPKM→log2(TPM+1) it shares the log2(TPM+1)
UNIT with the recount3 products but NOT the identical gene model — cross-TCGA ABSOLUTE comparison
carries a pipeline-batch caveat. The subtype use (within-SCLC NAPY stratification + within-cohort
all-gene percentile) is batch-robust because it compares each sample to the SCLC cohort itself.
"""

from __future__ import annotations
