"""subgroup_assigner_classifier — Modality C (classifier-derived) subgroup assigner.

Applies signature-score classifiers (single-gene z-scores or multi-gene NAPY-style
argmax) to RNA expression data. Emits per-sample assignments.parquet + manifest.yaml
conforming to target-contracts/schemas/subgroup_assignment.schema.json.

iter-1 scope: SCLC NAPY subtypes (SCLC-A/N/P/Y from ASCL1/NEUROD1/POU2F3/YAP1
z-scores), DLL3-high SCLC (single-gene z-score threshold). Phase 2a.3 of iDAS
Subtype Pipeline. NEW method scaffold — no prior version.
"""

METHOD_VERSION = "0.1.0"
