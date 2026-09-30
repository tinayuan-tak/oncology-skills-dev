"""subgroup_assigner_directly_tagged — produces per-sample subgroup assignments
from directly-tagged source fields (clinical metadata columns, source-provided
classifier outputs).

Reads a subgroup_catalog YAML, identifies strata with `derivation_source: directly_tagged_*`,
applies their rules against the catalog-bound source manifest (TCGA-GDC clinical metadata or
DepMap-native classifier outputs), and emits a Parquet of (case_id, subgroup_id, derivation_value, ...)
along with a manifest.yaml validating against subgroup_assignment.schema.json.

Iter-1b scope: TCGA clinical metadata columns (msi_status, histology, lauren_class, ebv_status)
and DepMap-native subtype calls. Tempus is excluded (pre-aggregated upstream; no per-sample access).
"""

__version__ = "0.1.0"
