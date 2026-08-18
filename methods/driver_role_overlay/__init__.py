"""driver_role_overlay — the typed alteration_role primitive (genomic-alteration plan, step 1).

For a (target, indication): classify the target's ROLE as a cancer driver from LANDED, license-clean
driver-annotation sources — no new ingestion. Answers "is this alteration a direct GoF/LoF driver, a
predictive biomarker, or a passenger, and in what direction (activating / loss-of-function)?" — the
4-role primitive the genomic-alteration gate needs, which the existing frequency/CN cards can't emit.

Sources (both LANDED + verified readable):
  - IntOGen v2024-09-20 (`Compendium_Cancer_Genes.tsv` in IntOGen-Drivers-20240920.zip): per-(gene,
    cohort) driver calls with ROLE ∈ {Act, LoF, ambiguous}, CANCER_TYPE, QVALUE_COMBINATION,
    %_SAMPLES_COHORT, IS_DRIVER. The patient-scale mode-of-action tag, indication-mappable via CANCER_TYPE.
  - OncoKB gene-roles-public (`oncokb_cancer_gene_list.json`): gene-level geneType ∈ {ONCOGENE, TSG,
    ONCOGENE_AND_TSG, NEITHER, INSUFFICIENT}. The curated gene-role backbone (promotes the GoF/LoF
    logic from depmap_predictability_precompute/features.py:717-745 to a target-facing signal).

Scope: this covers the alteration_role card + this overlay method only. Panel-aware prevalence
denominators + the inline-verdict→resolver conversion are separate follow-ups. The patient↔model
same-event join is a distinct later capability (genomic_event_model_match).
"""
