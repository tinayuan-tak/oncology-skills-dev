"""pair_selectivity_gate — AND/OR/NOT bispecific antigen-pair tumor-selectivity scan.

A NET-NEW capability: the v2 framework has no two-antigen selectivity anywhere. Ports the biologics-
target-discovery bstrat.gates logic-gate math onto the framework's per-sample TPM long products.
Candidate-GENERATION (nominates pairs to confirm), NOT a per-target evaluation card — consumed by the
bispecific-pair-scan scan-hook skill, which sits outside the single-target run_plan verdict spine.

  gates — pure AND/OR/NOT per-sample gate math + reduction (unit-testable, no S3)
  read  — S3 boundary: per-gene per-sample TPM reads + scan_pair / scan_partner_set orchestration
"""
