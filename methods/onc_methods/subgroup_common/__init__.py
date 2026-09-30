"""subgroup_common — shared utilities for subgroup-assigner methods (Phase 2a.4).

Mirrors depmap_common's pattern: cached loaders + parquet helpers. Consumed by:
- methods/subgroup_assigner_directly_tagged/  (Modality A)
- methods/subgroup_assigner_maf_filter/       (Modality B)
- methods/subgroup_assigner_classifier/       (Modality C)
- Phase-3 methods with subgroups= param (Path-B iteration; loads
  subgroup_assignments.parquet once per invocation via lru_cache).

See target-contracts docs/design/IDAS_SUBTYPE_PIPELINE.md for the resolver-
product design + Path-B I/O amortization argument.
"""

MODULE_VERSION = "0.1.0"
