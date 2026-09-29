"""subgroup_assigner_cptac_mmr — CPTAC MSI (dMMR/pMMR) subgroup-assignment shard.

Derives an MSI_H / MSS molecular-subtype assignment for CPTAC tumor aliquots from the
per-study clinical CRF's MMR-IHC protein-loss calls (MLH1 / MSH2 / PMS2 / MSH6), keyed to
the protein per-sample product's `aliquot_submitter_id` via the verified
aliquot -> case_submitter_id (== CPTAC Patient_ID) bridge.

WHY THIS EXISTS: CPTAC ships NO CMS/CIMP/explicit-MSI column in its clinical CRF, but it DOES
ship MMR-IHC calls — a validated MSI surrogate (dMMR = loss of >=1 MMR protein = MSI-H). This is
the only molecular-subtype axis buildable from CURRENTLY-LANDED CPTAC data; CMS/CIMP need a
separate ingestion. Coverage is PARTIAL (~57% of COAD tumor aliquots have an informative IHC call);
the rest are emitted with is_member=null (tri-value: source-value-missing, NOT a true negative).

The classification + assignment-assembly logic is PURE (testable with synthetic DataFrames); the
XLSX / PDC-bridge / parquet I/O lives in cli.py's thin loaders + main().
"""
