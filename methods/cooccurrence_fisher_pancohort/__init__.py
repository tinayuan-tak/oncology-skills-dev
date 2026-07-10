"""cooccurrence_fisher_pancohort — Fisher's exact co-mutation scanner.

Runs Fisher's exact + BH-FDR per (target, partner) gene pair across TCGA MC3
(whole-exome) and GENIE 19.0-public (panel-based), with a critical reviewer-
driven statistical fix: pooled analysis is restricted to the panel-intersect
gene set. Genes absent from GENIE panels are treated as "not sequenced" for
pooled Q-values, NOT as "not co-mutated" — the naive-pooling failure mode
that inflates artifactual mutual-exclusivity signals.

Consumer: the co-mutation-and-mutual-exclusivity evidence card (Phase E) via
the differentiation-landscape skill.

Companion:
    data-catalog:manifests/derived/pancohort-cooccurrence-fisher-v1.yaml

Modules:
    cli — Fisher scanner + panel-intersect eligibility gate
"""
METHOD_VERSION = "0.1.0"

from .read import read_target_summary  # noqa: F401,E402
