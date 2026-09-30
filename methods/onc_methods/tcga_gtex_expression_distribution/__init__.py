"""tcga_gtex_expression_distribution — per-sample tumor + normal expression distribution layer.

The shared per-sample extraction layer underlying the 12-question expression target-profile spec
(Q1 tumor distribution, Q2 tumor-vs-normal percentile-crossing enrichment, Q3 normal-tissue
liability). The existing expression cards emit AGGREGATES (cohort median, one-cohort log2FC); the
spec is overwhelmingly PER-SAMPLE distribution statistics that aggregates cannot produce.

This layer reads the two long per-sample TPM products — tcga-tumor-tpm-recount3-long-v1 (tumor, per
TCGA study) + gtex-tpm-recount3-long-v1 (normal, per GTEx tissue) — which share ONE recount3/GENCODE-
v26 log2(TPM+1) axis (directly comparable by construction), and computes distribution primitives:
percentiles, detectable/moderate/high fractions, coefficient of variation, distribution_pattern
(continuous | bimodal | long_tail), and the cross metric fraction-of-tumors-above-Nth-percentile-of-
normal (the spec's headline Q2 enrichment metric).

read (read.py):   per-gene per-sample readers over the two long products (predicate-pushdown; local
                  cache mirrors the tcga_gtex_tpm_quantiles reader).
stats (stats.py): dependency-light distribution primitives (numpy only) shared across Q1/Q2/Q3.
"""
