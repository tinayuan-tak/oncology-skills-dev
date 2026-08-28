"""til_fraction_saltz — per-indication absolute TIL fraction (Saltz 2018 H&E deep-learning maps).

Indication-tier reader (like immune_context): resolves OncoTree → TCGA study, pushdown-reads
tcga-til-fraction-saltz-per-sample-v1 on cancer_type, reduces to a median til_percentage +
til_fraction_class. The ABSOLUTE, morphology-derived corroborator of the immune-context CIBERSORT
CD8 hot/cold call. 13-study coverage → data_unavailable elsewhere (fail-closed).
"""
from .read import read_til_fraction, read_target_summary, METHOD_VERSION  # noqa: F401
