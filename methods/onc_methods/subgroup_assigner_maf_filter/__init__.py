"""subgroup_assigner_maf_filter — produces per-sample subgroup assignments from MAF-filter rules.

Reads a subgroup_catalog YAML, identifies strata with `derivation_source: maf_filter_per_rule`,
applies their predicates against a somatic-MAF manifest (gdc-pancohort-somatic-dr45-0 for TCGA;
OmicsSomaticMutations.csv for DepMap), and emits a per-sample assignment Parquet.

Iter-1b scope: hotspot/codon/gene-level MAF predicates (KRAS_mut, KRAS_G12C, BRAF_V600E, etc.).
Composite rules (e.g., TP53+RB1 co-mutation requiring joint presence in same sample) are also
handled — the assigner groups MAF rows by case_id before applying multi-gene predicates.
"""

__version__ = "0.1.0"
