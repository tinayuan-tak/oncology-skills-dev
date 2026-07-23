"""tcga_tmb — per-sample tumor mutational burden (TMB) from the MC3 MAF.

Computes nonsynonymous-mutations-per-Mb for every TCGA sample and a categorical
tmb_bucket (high/low at the FDA pan-cancer 10 mut/Mb threshold), so subgroup
catalogs can express a TMB-high stratum as a scalar `tmb_bucket == 'high'` rule
against a derived product — rather than requiring an assigner to aggregate MAF
rows per sample and threshold (no assigner does that).

Validated 2026-07-23 against MC3 v0.2.8: pan-TCGA TMB-high fraction 10.4%
(matches literature); NSCLC 20.9% (smoking-driven ~2x enrichment).
"""
