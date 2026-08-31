"""cooccurrence_fisher_pancohort — Fisher's exact co-mutation scanner.

Runs a per-(cohort, source) association test + BH-FDR per (target, partner) gene
pair across TCGA MC3 (whole-exome) and GENIE 19.0-public (panel-based). There is
NO cross-source pooling — `source` is only ever `tcga_mc3` or `genie_v19`, and each
(cohort, source) is tested + BH-adjusted independently. The `pooled_eligible` per-row
flag marks pairs where both genes lie in the GENIE panel-intersect gene set; it is
interpretation metadata (a "not sequenced ≠ not co-mutated" caveat for panel-absent
genes), NOT a gate on a cross-source pooled statistic (none is computed).

The per-target reader (read.read_target_summary) scopes the verdict-driving fields to
the queried indication's cohort(s) — the pan-cohort landscape is retained only as
display context. See read.py for the scoping + multiplicity discipline.

Consumer: the co-mutation-and-mutual-exclusivity evidence card (Phase E) via
the differentiation-landscape skill.

Companion:
    data-catalog:manifests/derived/pancohort-cooccurrence-fisher-v1.yaml

Modules:
    cli — Fisher scanner + panel-intersect eligibility gate
"""
METHOD_VERSION = "0.1.0"

from .read import read_target_summary  # noqa: F401,E402
