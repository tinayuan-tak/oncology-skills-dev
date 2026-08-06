"""compose-dashboard phase-2 live-mode DISPATCHER (thin shim).

Per the framework's layer-distinction discipline (plan § Dashboard, Interpretation,
Inference Layers), data extraction is *compute*, not *orchestration*. Extraction
logic lives in the methods repo:

  methods/dge_deseq2/read.py        — read_dge_gene_row()
  methods/depmap_chronos/read.py     — read_lineage_selectivity()
  methods/gdc_somatic_hotspot/read.py (iter-1b execution session)
  methods/tempus_rwd_aggregator/read.py (iter-1b execution session)

This module is a THIN DISPATCH LAYER: each card_id maps to a method-module function
call. No data-extraction logic lives here. If a future contributor is reading this
file to figure out 'how does the framework get data?' — the answer is in methods/,
not here.

Why this separation matters:
  - Methods are skill-runtime-agnostic. A Jupyter notebook, a SageMaker batch job,
    AgenticBoost, or Tina's dashboards can all import methods/* without depending
    on this skill's package layout.
  - Skills decide WHICH method to call FOR WHICH card; methods decide HOW to
    extract data. Same layer-distinction discipline as dashboard vs interpretation
    vs inference, just applied at the data-access boundary.
"""

from __future__ import annotations
import os

import sys
from pathlib import Path
from typing import Optional

METHODS_REPO = Path(os.environ.get("ANALYSIS_METHODS_ROOT", "/home/sagemaker-user/rnd-computational-biology-oncology-analysis-methods"))
DATA_CATALOG_LIBS = Path(os.environ.get("DATA_CATALOG_ROOT", "/home/sagemaker-user/rnd-computational-biology-oncology-data-catalog")) / "libs"
_TARGET_CONTRACTS_ROOT = Path(os.environ.get(
    "TARGET_CONTRACTS_ROOT", "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts"))


def _load_internalizing_antigens() -> frozenset:
    """B1 Rank-2: the curated internalizing-antigen gene set (target-contracts vocab
    internalizing_antigen_targets.yaml). Clinically-validated ADC-internalizing antigens
    (approved/late-clinical ADC precedent). Read-only, lru-cached, never raises — an unreadable
    vocab yields an EMPTY set (→ every target stays endocytosis 'unmeasured', the honest degrade).
    Positive-only: presence upgrades to a measured-internalizing signal; absence is unchanged."""
    import functools
    return _load_internalizing_antigens_cached(str(_TARGET_CONTRACTS_ROOT))


@__import__("functools").lru_cache(maxsize=4)
def _load_internalizing_antigens_cached(contracts_root: str) -> frozenset:
    path = Path(contracts_root) / "vocabularies" / "internalizing_antigen_targets.yaml"
    try:
        import yaml
        doc = yaml.safe_load(path.read_text())
        return frozenset((doc or {}).get("entries", {}).keys())
    except Exception:  # noqa: BLE001 — never break the dispatcher on a vocab read
        return frozenset()


def _import_method(method_name: str):
    """Import a method module from methods repo by name. Adds the methods repo
    to sys.path on first call (idempotent)."""
    if str(METHODS_REPO) not in sys.path:
        sys.path.insert(0, str(METHODS_REPO))
    return __import__(f"methods.{method_name}", fromlist=["*"])


def _import_data_catalog_lib(lib_name: str):
    """Import a library package from the data-catalog repo's libs/ directory.

    target_id_resolver was migrated from claude-oncology-skills/libs/ to
    data-catalog/libs/ (PR #55, 2026-06-29) — co-located with the source manifests
    and release pins it resolves. The resolver's release-pin file lookup uses
    `_THIS_DIR.parent.parent.parent / "resolver-releases"` which only resolves
    correctly when the package lives inside the data-catalog tree.
    """
    pkg_path = DATA_CATALOG_LIBS / lib_name
    if str(pkg_path) not in sys.path:
        sys.path.insert(0, str(pkg_path))
    return __import__(lib_name, fromlist=["*"])


def _dispatch_expression_tumor_vs_adjacent(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: route tumor-rna-vs-adjacent card to methods/dge_deseq2/read.py.

    Coverage fix (2026-08-05): the card was silently COADREAD-only for 26 of 27
    indications. The catalog has `{ind}-dge-tumor-vs-normal-sensitivity-v1` products
    for all TCGA indications and the reader (read_tumor_vs_normal_sensitivity_gene_row)
    reads them fine — but this dispatcher short-circuited on a hardcoded
    {COADREAD: coadread-dge-df06320} map, never reaching the reader for other
    indications (returned only a _data_note → the card read n/a everywhere else).

    Resolution:
      - COADREAD keeps its legacy manifest (coadread-dge-df06320) → emitted value
        byte-identical (log2_fc=-0.72), no verdict-spine perturbation.
      - Every other indication falls through to the four-cell sensitivity product,
        projecting cell A (the TCGA tumor-vs-adjacent contrast) onto the card's
        two-group fields (log2_fc / q_value). Reader returns None honestly if a
        product is genuinely absent.
    """
    dge_module = _import_method("dge_deseq2")

    # COADREAD: preserve the byte-stable legacy path.
    if indication.upper() == "COADREAD":
        summary = dge_module.read_dge_gene_row(target=target, manifest_id="coadread-dge-df06320")
        if summary is None:
            return {
                "log2_fc": None, "q_value": None,
                "tumor_mean_tpm": None, "adjacent_mean_tpm": None,
                "n_tumor": None, "n_adjacent": None,
                "_data_note": f"target {target!r} not present in coadread-dge-df06320 DGE table",
            }
        return summary

    # All other indications: the four-cell sensitivity product, cell A = tumor-vs-adjacent.
    sen = dge_module.read_tumor_vs_normal_sensitivity_gene_row(target, indication)
    if sen is None:
        return {
            "log2_fc": None, "q_value": None,
            "tumor_mean_tpm": None, "adjacent_mean_tpm": None,
            "n_tumor": None, "n_adjacent": None,
            "_data_note": (f"no tumor-vs-adjacent product for {target!r} in "
                           f"{indication.lower()}-dge-tumor-vs-normal-sensitivity-v1"),
        }
    return {
        "log2_fc": sen.get("log2fc_cell_a"),      # cell A = TCGA tumor vs adjacent-normal
        "q_value": sen.get("q_value_cell_a"),
        "tumor_mean_tpm": None, "adjacent_mean_tpm": None,   # not carried by sensitivity product
        "n_tumor": None, "n_adjacent": None,
        "cells_ran": sen.get("cells_ran"),
        "dominant_direction": sen.get("dominant_direction"),
        "_data_source": sen.get("_data_source"),
    }


def _dispatch_tumor_vs_normal_selectivity(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: route tumor-vs-normal-selectivity card (v3 four-cell) to
    methods/dge_deseq2/read.py:read_tumor_vs_normal_selectivity.

    v3 primary path: reads `{indication}-dge-tumor-vs-normal-sensitivity-v1`
    (four-cell DESeq2 output — cells A/B TCGA-adjacent ±ComBat, C/D GTEx
    ±ComBat) and maps to the card v3 summary_fields shape with
    cells_supporting / dominant_direction / discordant / sig_all_cells.

    v2 fallback: if the sensitivity product isn't yet in S3 for this
    indication (batch expansion pending), the reader falls back to the legacy
    two-product path (tumor-vs-adjacent + tumor-vs-GTEx) reshaped into the
    v3 envelope with cells_ran=2. Renderer + rules see the v3 shape either way.

    Never returns None; missing everything → selectivity_class=data_unavailable.
    """
    dge_module = _import_method("dge_deseq2")
    return dge_module.read_tumor_vs_normal_selectivity(target=target, indication=indication)


def _dispatch_dependency_lineage_selectivity(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: route dependency-lineage-selectivity card to methods/depmap_chronos/read.py."""
    chronos_module = _import_method("depmap_chronos")
    return chronos_module.read_lineage_selectivity(target=target, indication=indication)


def _dispatch_mutation_hotspot_frequency(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: route mutation-hotspot-frequency card to methods/gdc_somatic_hotspot/read.py.

    The aggregate Parquet is produced by `methods.gdc_somatic_hotspot.cli` (run once per
    MC3 release per indication). The dispatcher doesn't know about MC3; the method does.
    """
    hotspot_module = _import_method("gdc_somatic_hotspot")
    return hotspot_module.read_hotspot_summary(target=target, indication=indication)


def _dispatch_alteration_role(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: route alteration-role card to methods/driver_role_overlay/cli.py::build_summary.

    Typed driver-role call (OncoKB geneType × IntOGen mode-of-action) → alteration_role +
    functional_direction. Indication-scoped (IntOGen mode-of-action is per cancer type)."""
    mod = _import_method("driver_role_overlay.cli")
    return mod.build_summary(target, indication)


def _dispatch_genomic_instability_state(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: route genomic-instability-state card to
    methods/tcga_aneuploidy_burden::aneuploidy_burden_for_indication.

    INDICATION-level, target-INDEPENDENT (aneuploidy is a genome-wide cohort phenotype) — the
    `target` arg is accepted for dispatcher-signature uniformity but IGNORED; the burden is a
    property of the indication cohort. DISPLAY facet, verdict-inert."""
    mod = _import_method("tcga_aneuploidy_burden")
    return mod.aneuploidy_burden_for_indication(indication)


def _dispatch_variant_level_interpretation(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: route variant-level-interpretation card to
    methods/civic_variant_interpretation::civic_interpretation_for_gene.

    Per-VARIANT oncogenicity + therapy-resistance from CIViC, aggregated to the gene. TARGET-grain,
    indication-INDEPENDENT (a variant's oncogenicity/resistance is a property of the gene's variants)
    — the `indication` arg is accepted for dispatcher-signature uniformity but IGNORED. DISPLAY
    facet, verdict-inert."""
    mod = _import_method("civic_variant_interpretation")
    return mod.civic_interpretation_for_gene(target)


def _dispatch_functional_gene_state(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: route functional-gene-state card (M6) to
    methods/functional_gene_state/cli.py::build_summary.

    Harmonized two-hit / biallelic-inactivation call: mutation + allele-specific CN → per-sample
    state {wt, monoallelic, biallelic-genetic, uncertain}, on both patient (TCGA) + model (DepMap)
    arms. Indication-scoped (the patient arm is per cancer type). Phase-1 genetic-only vocab."""
    mod = _import_method("functional_gene_state.cli")
    return mod.build_summary(target, indication)


def _dispatch_genomic_event_model_match(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: route genomic-event-model-match card (M11 — canonical P3 genomic join) to
    methods/genomic_event_model_match/cli.py::build_summary.

    Which DepMap models carry the SAME functional genomic event (M6 two-hit genotype) as the
    indication's tumors, and which genotype-matched models are dependent (Chronos)? The genomic
    sibling of recommended-models (expression-Q4). Indication-scoped."""
    mod = _import_method("genomic_event_model_match.cli")
    return mod.build_summary(target, indication)


def _dispatch_fusion_rearrangement_landscape(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: fusion-rearrangement-landscape card -> tcga_fusion_consensus.read_target_summary.

    Per-(target, indication) fusion recurrence over the tcga-fusion-consensus-v1 derived product
    (pan-TCGA 3-caller consensus: TumorFusions/Gao/cBioPortal SV). fusion_class in
    {recurrent_fusion_driver | sporadic_fusion | no_recurrent_fusion | data_unavailable}; graceful
    data_unavailable when product/target absent. Indication-scoped (TCGA tissue filter)."""
    mod = _import_method("tcga_fusion_consensus")
    return mod.read_target_summary(target, indication)


# ---- Subgroup-panorama dispatchers (descriptive; 2026-07-16) ------------------
# These route the two NEW live subgroup cards to the per-sample panorama BUILDERS
# (not the scalar readers above). They fire only when subgroups are in scope
# (subgroup_context carries resolved_strata_ids); the skill decides WHICH
# assignments shard, the method decides HOW to fan out + recompute per stratum.
# Cross-source reality: the mutation panorama reads the TCGA-side shard, the
# dependency panorama the DepMap-side shard — different sample universes for the
# "same" axis, surfaced honestly via each record's source_cohort field.

# indication → the assignments shard carrying the ENUMERATION AXIS for each panorama.
# Iter-1b ships COADREAD only; iter-2 extends as shards land.
#
# NB — shard choice is the axis-membership source, NOT the value substrate:
#   - mutation-FREQUENCY across MSI/MSS/sidedness enumerates the DIRECTLY-TAGGED
#     shard (which carries MSI_H, MSS, left/right_sided membership); the MAF values
#     come from the per-sample MAF the reader loads. The `tcga-maf-...` shard defines
#     mutation-STATUS strata (KRAS_mut, KRAS_G12C, BRAF_V600E) — the right shard only
#     when the axis IS a mutation stratum, not for the molecular MSI/sidedness axes.
#   - dependency uses the DepMap shard (cell-line ModelIDs carry MSI status directly).
_MUTATION_ASSIGNMENTS_MANIFEST = {
    "COADREAD": "tcga-subgroup-assignments-coadread-v1",   # directly-tagged: MSI_H/MSS/sidedness/CMS/CIMP
}
# Line-of-therapy strata live in a DIFFERENT sample universe (GENIE-BPC, not TCGA) and
# recompute frequency from the GENIE registry MAF, not MC3. The panorama dispatcher partitions
# requested strata by axis: molecular → the TCGA shard above + tcga_mc3; LOT → this GENIE-BPC
# shard + the genie_registry MAF. Rows from the two universes are never merged into one
# comparison (each carries its source_cohort); the card's caveats already mandate that.
_MUTATION_LOT_ASSIGNMENTS_MANIFEST = {
    "COADREAD": "genie-bpc-subgroup-assignments-coadread-v1",   # GENIE-BPC LOT_1L_only/LOT_2L/LOT_3Lplus (1,176)
    "NSCLC": "genie-bpc-subgroup-assignments-nsclc-v1",         # GENIE-BPC LOT_1L_only/LOT_2L/LOT_3Lplus (1,093)
}
# LOT strata are identified by id prefix (the catalog tags them applicable_data_sources:[genie_bpc]).
_LOT_STRATUM_PREFIX = "LOT_"
_DEPENDENCY_ASSIGNMENTS_MANIFEST = {
    "COADREAD": "depmap-subgroup-assignments-coadread-v1",
}


def _dispatch_subgroup_stratified_mutation_frequency(
    target: str, indication: str, subgroups: list, subgroup_assignments_manifest: str,
) -> Optional[dict]:
    """Route subgroup-stratified-mutation-frequency to the per-sample panorama builder,
    PARTITIONING requested strata by data-source axis.

    methods/gdc_somatic_hotspot/read.py::build_mutation_frequency_panorama fans
    read_stratified_mutation_frequency across `subgroups` and recomputes frequency
    WITHIN each stratum member-set (never an emit-time slice). Descriptive — no signal.

    Two sample universes cannot share one call:
      - MOLECULAR strata (MSI/MSS/sidedness/CMS/CIMP) → TCGA shard + tcga_mc3 MAF.
      - LINE-OF-THERAPY strata (LOT_*) → GENIE-BPC shard + genie_registry MAF (the GENIE
        registry MAF's full sample barcode joins the BPC LOT shard's cpt_genie_sample_id).
    We split `subgroups`, make one panorama call per populated axis, and MERGE the
    per_subgroup_metrics lists. Each row carries its own source_cohort (TCGA-MC3 vs
    GENIE-registry), so the cross-cohort merge is contract-valid (the card's caveats
    forbid merging rows from different cohorts into a single comparison, which this respects).
    """
    hotspot_module = _import_method("gdc_somatic_hotspot")

    lot_strata = [s for s in subgroups if str(s).startswith(_LOT_STRATUM_PREFIX)]
    molecular_strata = [s for s in subgroups if not str(s).startswith(_LOT_STRATUM_PREFIX)]

    panoramas: list[dict] = []
    # Molecular axis → the TCGA shard passed in by read_live_summary (tcga_mc3 default).
    if molecular_strata:
        panoramas.append(hotspot_module.build_mutation_frequency_panorama(
            target=target, indication=indication,
            subgroups=molecular_strata,
            subgroup_assignments_manifest=subgroup_assignments_manifest,
        ))
    # LOT axis → the GENIE-BPC shard + genie_registry MAF (different sample universe).
    if lot_strata:
        lot_manifest = _MUTATION_LOT_ASSIGNMENTS_MANIFEST.get(indication)
        if lot_manifest is None:
            panoramas.append({"per_subgroup_metrics": [], "_data_note":
                f"LOT strata requested but no GENIE-BPC LOT shard for indication={indication!r} "
                f"(iter-1 ships COADREAD only)"})
        else:
            panoramas.append(hotspot_module.build_mutation_frequency_panorama(
                target=target, indication=indication,
                subgroups=lot_strata,
                subgroup_assignments_manifest=lot_manifest,
                maf_source="genie_registry",
            ))

    if not panoramas:
        return {"per_subgroup_metrics": []}
    if len(panoramas) == 1:
        return panoramas[0]

    # MERGE: concatenate per_subgroup_metrics; carry a merged data-note if either arm set one.
    merged_metrics: list = []
    notes: list[str] = []
    for p in panoramas:
        merged_metrics.extend(p.get("per_subgroup_metrics") or [])
        if p.get("_data_note"):
            notes.append(p["_data_note"])
    out = {"per_subgroup_metrics": merged_metrics}
    if notes:
        out["_data_note"] = " | ".join(notes)
    return out


def _dispatch_subgroup_stratified_dependency(
    target: str, indication: str, subgroups: list, subgroup_assignments_manifest: str,
) -> Optional[dict]:
    """Route subgroup-stratified-dependency to the per-sample (per-ModelID) panorama builder.

    methods/depmap_chronos/read.py::build_dependency_panorama fans
    read_stratified_dependency across `subgroups` and recomputes median Chronos
    WITHIN each stratum's cell-line member-set. Descriptive — no signal.
    """
    chronos_module = _import_method("depmap_chronos")
    return chronos_module.build_dependency_panorama(
        target=target,
        indication=indication,
        subgroups=subgroups,
        subgroup_assignments_manifest=subgroup_assignments_manifest,
    )


def _dispatch_target_identity_summary(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: route target-identity-summary card to libs/target_id_resolver/.

    This is the foundational identity card — every other card's interpretation depends
    on a successfully resolved target. The library function `resolve()` returns a Target
    pydantic object with hgnc.id as the canonical "HGNC:6407" string; this dispatcher
    strips the prefix to the integer form expected by the evidence_package schema's
    context.target.hgnc_id (minimum: 1).

    Returns the summary-fields shape the target-identity-summary card declares (mirrors
    the stub fixture schema).
    """
    resolver_module = _import_data_catalog_lib("target_id_resolver")
    try:
        t = resolver_module.resolve(target)
    except resolver_module.NotFoundError as e:
        return {
            "input_value": target,
            "resolved_hgnc_symbol": None,
            "resolved_hgnc_id": None,
            "resolution_status": "no_match_in_source",
            "_live_read_error": "resolver_not_found",
            "detail": str(e),
        }
    except resolver_module.AmbiguousInputError as e:
        return {
            "input_value": target,
            "resolution_status": "ambiguous",
            "_live_read_error": "resolver_ambiguous",
            "detail": str(e),
        }
    except Exception as e:
        return {
            "input_value": target,
            "_live_read_error": "resolver_error",
            "detail": f"{type(e).__name__}: {e}",
        }

    hgnc_id_int = int(t.hgnc.id.split(":", 1)[1])
    return {
        "input_value": target,
        "resolved_hgnc_symbol": t.hgnc.primary_symbol,
        "resolved_hgnc_id": hgnc_id_int,
        "resolved_ensembl_id": t.ensembl.full or f"{t.ensembl.gene_id}.{t.ensembl.version}",
        "resolved_uniprot_canonical": t.uniprot.canonical_accession if t.uniprot else None,
        "resolution_status": "deprecated_remapped" if t.deprecation_warning else "resolved",
        "redirects_applied": [t.deprecation_warning.input_alias] if t.deprecation_warning else [],
        "resolver_release_pin": t.release_pins.resolver_release,
    }


def _dispatch_expression_dependency_correlation(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: route expression-dependency-correlation card (Card 4) to
    methods/depmap_expression_dependency/read.py.

    Card 4 asks whether a target's mRNA expression correlates with its own
    Chronos dependency across cell lines (biomarker hypothesis). Reuses Card 1+2's
    DepMap 26Q1 substrate + adds the TPMLogp1 matrix.
    """
    expr_module = _import_method("depmap_expression_dependency")
    return expr_module.read_expression_dependency(target=target, indication=indication)


def _dispatch_abundance_dependency(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: route abundance-dependency card (Q7, protein arm) to
    methods/abundance_dependency/cli.py::build_summary.

    Does target PROTEIN abundance (Gygi MS) predict its own Chronos dependency? The protein sibling
    of expression-dependency-correlation (RNA arm); reused Gygi + Chronos loaders. Indication carried
    for contract symmetry (the correlation is pan-lineage per-model)."""
    mod = _import_method("abundance_dependency.cli")
    return mod.build_summary(target, indication)


def _dispatch_expression_purity_confound(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: route expression-purity-confound card (Q9) to
    methods/expression_purity_confound/cli.py::build_summary.

    Is the target's tumor expression tumor-cell-intrinsic or microenvironment-driven? Correlates
    per-sample tumor expression vs ABSOLUTE purity. Indication-scoped (per-sample tumor cohort)."""
    mod = _import_method("expression_purity_confound.cli")
    return mod.build_summary(target, indication)


def _dispatch_expression_clinical_association(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: route expression-clinical-association card (Q11) to
    methods/expression_clinical_association/cli.py::build_summary.

    Does target expression stratify overall survival in the indication (median-split log-rank on
    TCGA-CDR OS)? A hypothesis-generating prognostic association. Indication-scoped."""
    mod = _import_method("expression_clinical_association.cli")
    return mod.build_summary(target, indication)


def _dispatch_phospho_pathway_activity(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: route phospho-pathway-activity card (Q8) to
    methods/phospho_pathway_activity/cli.py::build_summary.

    Is the target phosphorylated (pathway-activity proxy) in the indication's CPTAC tumors, beyond
    its total abundance? Reads the cptac package's harmonized phosphoproteomics [bcm]. Indication-scoped."""
    mod = _import_method("phospho_pathway_activity.cli")
    return mod.build_summary(target, indication)


def _dispatch_pan_cancer_dependency_distribution(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: route pan-cancer-crispr-dependency-distribution card to
    methods/depmap_chronos_distribution/read.py.

    Iter-2 Card 1: this card is pan-cancer by definition (NOT lineage-filtered).
    The indication parameter is accepted for dispatcher consistency but not consumed —
    lineage-filtering is the sister card `lineage-specific-dependency`'s job.
    """
    dist_module = _import_method("depmap_chronos_distribution")
    return dist_module.read_pan_cancer_distribution(target=target, indication=indication)


# Card-id → dispatcher registry. Each dispatcher is a thin wrapper that:
#   1. Resolves any framework-side context (manifest selection, indication-to-key mapping)
#   2. Calls the corresponding method module from methods/
#   3. Returns the method's summary dict unchanged
def _dispatch_pan_cancer_rnai_dependency_distribution(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: route pan-cancer-rnai-dependency-distribution card (Card E1b) to
    methods/depmap_demeter_distribution/read.py.

    RNAi sibling to the CRISPR Card E1a. Pan-cancer (NOT lineage-filtered); indication
    accepted for dispatcher consistency but not consumed by the compute path.
    """
    rnai_module = _import_method("depmap_demeter_distribution")
    return rnai_module.read_pan_cancer_rnai_distribution(target=target, indication=indication)


def _dispatch_expression_distribution(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: route cellline-rna-distribution card (E3.a) to
    methods/depmap_expression_distribution/read.py.

    Pan-cancer cell-line expression panel; indication accepted for dispatcher
    consistency but not consumed (this card is target-only).
    """
    expr_module = _import_method("depmap_expression_distribution")
    return expr_module.read_expression_distribution(target=target, indication=indication)


def _dispatch_tumor_expression_distribution(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: route tumor-rna-distribution card (Q1) to
    methods/tcga_gtex_expression_distribution/cli.py::build_summary.

    Per-SAMPLE tumor RNA distribution (percentiles, detectable/moderate/high fraction, CoV,
    distribution_pattern) + matched-normal fraction-above-p95 overlay, from the TCGA + GTEx long
    products. Indication-scoped (the tumor distribution is per-indication)."""
    mod = _import_method("tcga_gtex_expression_distribution.cli")
    return mod.build_summary(target, indication)


def _dispatch_tumor_expression_distribution_subtype(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: route tumor-rna-distribution-by-subtype card (target_subtype grain) to
    methods/tcga_gtex_expression_distribution/cli.py::build_subtype_panorama.

    Returns the FULL per-stratum landscape as `per_subgroup_metrics` + rollup scalars. Unlike the
    other PANORAMA dispatchers (which take pre-resolved strata), this method is COMPUTE-ALL — it
    fans out over EVERY stratum of the indication's landed shard internally (the plan-decided
    compute-all-spotlight-one), so it takes the scalar (target, indication) signature and lives in
    CARD_DISPATCHERS. No shard for the indication -> subtype_axis_available:false (honest)."""
    mod = _import_method("tcga_gtex_expression_distribution.cli")
    return mod.build_subtype_panorama(target, indication)


def _dispatch_sc_tumor_celltype_expression(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: route tumor-scrna-celltype-expression card (sc_rna/tumor bucket) to
    methods/sc_tumor_expression_celltype/cli.py::build_summary.

    Single-cell per-compartment tumor presence from the donor×compartment pseudobulk product:
    malignant-anchored sc_expression_class + per-compartment detection_fraction + microenvironment
    attribution. Indication-scoped (v1: COADREAD + NSCLC); other indications → data_unavailable."""
    mod = _import_method("sc_tumor_expression_celltype.cli")
    return mod.build_summary(target, indication)


def _dispatch_tumor_vs_normal_percentile_crossing(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: route tumor-vs-normal-percentile-crossing card (Q2, Gate B) to
    methods/tcga_gtex_expression_distribution/cli.py::build_selectivity_crossing_summary.

    Per-sample fraction-of-tumors-above-matched-normal-p95/p99 + distribution overlap. Indication-
    scoped (the tumor arm is per-indication; the normal arm is the matched GTEx tissue)."""
    mod = _import_method("tcga_gtex_expression_distribution.cli")
    return mod.build_selectivity_crossing_summary(target, indication)


def _dispatch_normal_tissue_liability_gtex(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: route normal-tissue-liability-gtex card (Q3, Safety + surface-modality-fit) to
    methods/tcga_gtex_expression_distribution/cli.py::build_normal_liability_summary.

    Target-grain GTEx normal-tissue atlas: highest tissue, critical-organ max, breadth. indication
    is accepted for the CARD_DISPATCHERS contract but NOT consumed (normal expression is a target
    property, indication-independent)."""
    mod = _import_method("tcga_gtex_expression_distribution.cli")
    return mod.build_normal_liability_summary(target, indication)


def _dispatch_recommended_models(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: route recommended-models card (Q4, patient↔model expression correspondence) to
    methods/patient_model_expression_correspondence/cli.py::build_summary.

    Ranks DepMap models by TARGET-expression fit to the patient tumor TARGET distribution + screen
    role from Chronos. Indication-scoped (patient distribution + lineage are per-indication)."""
    mod = _import_method("patient_model_expression_correspondence.cli")
    return mod.build_summary(target, indication)


def _dispatch_rna_protein_concordance(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: route cellline-rna-protein-concordance card (Q5) to
    methods/depmap_rna_protein_concordance/cli.py::build_summary.

    Per-ModelID DepMap RNA vs Gygi MS protein correlation → rna_as_biomarker. Target-grain
    (concordance is a per-ModelID target property); indication accepted for the contract, NOT consumed."""
    mod = _import_method("depmap_rna_protein_concordance.cli")
    return mod.build_summary(target, indication)


def _dispatch_rna_protein_concordance_tumor(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: route rna-protein-concordance-tumor card (Q5 tumor arm) to
    methods/depmap_rna_protein_concordance/cli.py::build_tumor_summary.

    Per-tumor CPTAC RNA vs protein correlation for the indication's CPTAC cohort → rna_as_biomarker
    (tumor). Indication-scoped (cohort-specific — the tumor-grain sibling of the cell-line card)."""
    mod = _import_method("depmap_rna_protein_concordance.cli")
    return mod.build_tumor_summary(target, indication)


def _dispatch_crispr_rnai_dependency_concordance(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: route crispr-rnai-dependency-concordance card (Card E1c, DERIVED) to
    methods/depmap_crispr_rnai_concordance/read.py.

    DERIVED CARD: this method composes the CRISPR + RNAi loaders. If either upstream
    load fails, the read function returns _live_read_error and the concordance_class
    is data_unavailable (preserves the framework's graceful-degradation contract).
    """
    concord_module = _import_method("depmap_crispr_rnai_concordance")
    return concord_module.read_crispr_rnai_concordance(target=target, indication=indication)


def _dispatch_mutation_type_counts(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: route mutation-type-counts card (E4) to
    methods/depmap_mutation_type_counts/read.py.

    Cell-line cohort, variant-class resolution. Pan-cancer (indication accepted but
    not consumed). Distinct from mutation-hotspot-frequency (TCGA-patient cohort).
    """
    mut_module = _import_method("depmap_mutation_type_counts")
    return mut_module.read_mutation_type_counts(target=target, indication=indication)


def _dispatch_cn_distribution(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: route copy-number-distribution card (E3.b) to
    methods/depmap_cn_distribution/read.py.

    WES-primary + WGS-fallback. Indication accepted but not consumed (pan-cancer card).
    """
    cn_module = _import_method("depmap_cn_distribution")
    return cn_module.read_cn_distribution(target=target, indication=indication)


def _dispatch_mutation_stratified_dependency(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: route mutation-stratified-dependency card (Card 3) to
    methods/depmap_mutation_dependency/read.py.

    Card 3 asks whether a target's dependency stratifies by ITS OWN mutation status
    across the DepMap panel (oncogene-addiction biomarker hypothesis). Target-only;
    indication accepted for back-compat but not consumed by the compute path.
    """
    mut_module = _import_method("depmap_mutation_dependency")
    return mut_module.read_mutation_stratified_dependency(target=target, indication=indication)


def _dispatch_cn_stratified_dependency(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: route copy-number-stratified-dependency card (Card E3.cn) to
    methods/depmap_cn_dependency/read.py.

    The copy-number analog of Card 3: does a target's dependency stratify by ITS OWN
    amplification status (relative CN > 1.5) across the DepMap panel — the amplification-
    addiction biomarker hypothesis (ERBB2/MYC-class)? Target-only; indication accepted for
    back-compat but not consumed by the compute path.
    """
    cn_module = _import_method("depmap_cn_dependency")
    return cn_module.read_cn_stratified_dependency(target=target, indication=indication)


def _dispatch_dependency_predictability(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: route dependency-predictability card (E5) to
    methods/depmap_predictability/read.py.

    E5 is a THIN LOOKUP card: reads one row out of the frozen derived parquet
    s3://onc-compbio/data-catalog/derived/depmap-predictability-26q1-v1/predictability_per_gene.parquet
    via pyarrow predicate pushdown. No sklearn at framework run-time.

    The expensive RandomForest training lives in the sibling
    methods/depmap_predictability_precompute/ — which runs as a batch job and
    writes the parquet that this card reads. Target-only (pan-cancer); indication
    accepted for the framework's dispatcher signature but NOT consumed.
    """
    pred_module = _import_method("depmap_predictability")
    return pred_module.read_predictability(target=target, indication=indication)


def _dispatch_prism_compound_activity(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: route prism-compound-activity card (E6) to
    methods/depmap_prism_activity/read.py.

    E6 is a THIN LOOKUP card off the shared v4 derived parquet
    s3://onc-compbio/data-catalog/derived/depmap-prism-activity-v4/prism_activity_per_gene.parquet
    (release_pin `prism-activity-v4`; parquet is shared with E7 crispr-concordance).
    Sister precompute (methods/depmap_prism_precompute/) merges PRISM OncologyReference
    25Q4 + Repurposing 24Q2 into a per-gene aggregate at batch time.
    """
    prism_module = _import_method("depmap_prism_activity")
    return prism_module.read_prism_activity(target=target, indication=indication)


def _dispatch_prism_crispr_concordance(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: route prism-crispr-concordance card (E7) to
    methods/depmap_prism_crispr_concordance/read.py.

    E7 is a THIN LOOKUP card sharing the v4 parquet with E6 but exposing the
    per_compound_concordance + crispr_prism_concordance_class + dual_responders
    fields for chemical-genetic-genetic triangulated engagement analysis.

    Target-only (pan-cancer, correlation across full DepMap panel). indication
    accepted for CARD_DISPATCHERS contract but NOT consumed.
    """
    concord_module = _import_method("depmap_prism_crispr_concordance")
    return concord_module.read_prism_crispr_concordance(target=target, indication=indication)


# -----------------------------------------------------------------------------
# RT1 fix-rollup 2026-07-09: dispatchers for the 11 new Phase D/E/F/G cards
# from the Layer 6 skill graduations. Each dispatcher delegates to a method's
# read.py::read_target_summary(). Hybrid cache-then-compute pattern lives in
# the method's read.py — dispatchers stay thin.
# -----------------------------------------------------------------------------

def _dispatch_signaling_network_mechanism(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: signaling-network-mechanism card → COMPOSED Phase-D output
    unioning SIGNOR + CollecTri + Reactome via methods/mechanism_composed/read.py.

    Sources composed (per PSP-replacement research 2026-07-10):
      - signor_mechanism_network (causal signaling edges)
      - collectri_tf_regulon (signed TF-target regulons)
      - reactome_pathway_context (pathway-membership annotations)

    Updated 2026-07-10 from single-source SIGNOR to composed 3-source output.
    """
    mod = _import_method("mechanism_composed")
    return mod.read_target_summary(target=target, indication=indication)


def _dispatch_co_mutation_and_mutual_exclusivity(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: co-mutation-and-mutual-exclusivity card → panel-intersect
    Fisher scan via methods/cooccurrence_fisher_pancohort/read.py.
    """
    mod = _import_method("cooccurrence_fisher_pancohort")
    return mod.read_target_summary(target=target, indication=indication)


def _dispatch_protein_domains_class(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: protein-domains-class card → UniProt curated domain architecture + protein class
    via methods/uniprot_protein_features/read.py. Target-intrinsic (indication ignored).
    """
    mod = _import_method("uniprot_protein_features")
    return mod.read_target_summary(target=target, indication=indication)


def _dispatch_ppi_interactome(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: ppi-interactome card → STRING functional-network degree + CORUM complex
    membership via methods/ppi_interactome/read.py. Target-intrinsic (indication ignored).
    """
    mod = _import_method("ppi_interactome")
    return mod.read_target_summary(target=target, indication=indication)


def _dispatch_reactome_pathway_membership(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: reactome-pathway-membership card → Reactome pathway/geneset membership
    via methods/reactome_pathway_context/read.py. Target-intrinsic (indication ignored); the
    reader resolves HGNC→UniProt-AC via the Reactome resolver sidecar. Distinct from the
    signaling-network-mechanism dispatcher (which uses reactome only as one enrichment input to
    the COMPOSED mechanism output) — this exposes pathway MEMBERSHIP as its own card.
    """
    mod = _import_method("reactome_pathway_context")
    return mod.read_target_summary(target=target, indication=indication)


def _dispatch_gene_ontology_annotation(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: gene-ontology-annotation card → per-target GO term membership (BP/MF/CC)
    via methods/gene_ontology_annotation/read.py. Target-intrinsic (indication ignored); HGNC→AC
    via the GOA resolver sidecar.
    """
    mod = _import_method("gene_ontology_annotation")
    return mod.read_target_summary(target=target, indication=indication)


def _dispatch_signaling_network_mechanism_composed(target: str, indication: str) -> Optional[dict]:
    """Alias for the ADC/TCE composed card's derived_from resolution.
    (Unused as a card-registered dispatcher; kept for symmetry.)"""
    return _dispatch_signaling_network_mechanism(target, indication)


def _dispatch_surface_topology_and_ptm(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: surface-topology-and-ptm card → TMbed topology + UniProt PTM
    + AlphaFold pLDDT + motif regex via methods/topology_predictions_tmbed/read.py.
    """
    mod = _import_method("topology_predictions_tmbed")
    return mod.read_target_summary(target=target, indication=indication)


def _dispatch_surfaceome_family_classification(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: surfaceome-family-classification card → SURFY + HPA + UniProt
    EC + IUPHAR fusion via methods/surfaceome_family_fusion/read.py.
    """
    mod = _import_method("surfaceome_family_fusion")
    return mod.read_target_summary(target=target, indication=indication)


def _dispatch_structure_features_static(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: structure-features-static card → PDB + AlphaFold scalar
    features via methods/structure_features_static/read.py.
    """
    mod = _import_method("structure_features_static")
    return mod.read_target_summary(target=target, indication=indication)


def _dispatch_protein_surface_evidence(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: protein-surface-evidence card → CSPA wet-lab surface confirmation via
    methods/cspa_surface_confirmation/read.py (the live-firing provider of the surface_confirmation
    measurement_type — resolves the CSPA orphan, DATA_TO_SKILL_CONTRACT).

    CSPA is the `measured` tier of surface_confirmation. Reads the derived per-UniProt-AC product +
    resolver sidecar (cspa-surface-confirmation-per-uniprot-v1); resolves target→UniProt AC via the
    sidecar. An absent target is an honest measured-negative (`not_surface`, measured_in_cspa=False),
    NOT data_unavailable — so the surface-presence + safety gates read a trusted negative, not a gap.
    """
    mod = _import_method("cspa_surface_confirmation")
    return mod.read_surface_confirmation(target=target, indication=indication)


def _dispatch_surface_abundance_density(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: surface-abundance-density card → CPTAC protein intensity +
    HPA IHC anchor → copies-per-cell estimate via
    methods/cptac_protein_deg/read.py::read_abundance_density_summary().
    """
    mod = _import_method("cptac_protein_deg")
    return mod.read_abundance_density_summary(target=target, indication=indication)


def _dispatch_adc_tce_modality_fit(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: adc-tce-modality-fit COMPOSED card. Reads the upstream
    cards (surface-topology-and-ptm + surfaceome-family-classification +
    structure-features-static) via their dispatchers, then applies the ADC/TCE
    modality rubric to compute fit_class + lens-conditional letter grades.
    """
    topology = _dispatch_surface_topology_and_ptm(target, indication) or {}
    family = _dispatch_surfaceome_family_classification(target, indication) or {}
    structure = _dispatch_structure_features_static(target, indication) or {}
    # NOTE (2026-08-04): the card's derived_from declares structure-features-static, and this
    # dispatcher fetches `structure` — but the fit_class rubric below keys ONLY on topology + family
    # (TM count / ECD length / endocytosis / ubiquitination), because structure-features-static is an
    # SM/degrader pocket-druggability signal (hotspot_pocket_adjacency / pLDDT / disorder), NOT an
    # extracellular-epitope-quality signal. The prior code fetched `structure` and then dropped it on
    # the floor — a wasted read AND an unhonored derived_from. Rather than force an unrelated SM signal
    # into the biologics fit_class (wrong biology) OR delete the fetch (contradicts the card contract),
    # we SURFACE it as an explicit `structure_epitope_context` passthrough so the composed card carries
    # the structure signal it declares, WITHOUT changing fit_class. Scoring an ECD-disorder epitope-
    # quality rule off pLDDT/disordered_fraction is a deliberate follow-on (verdict-affecting, needs a
    # rule + golden regen) — tracked in the surface build plan, not this verdict-neutral wiring fix.
    # Compose fit_class biology-agnostic categorical from the three biology
    # inputs. Letter grades are lens-conditional — emitted only if modality
    # lens is invoked at target-profile time; dispatcher only emits biology.
    is_surface = family.get("is_surface_protein", False)
    tm_count = topology.get("tm_pass_count", 0) or 0
    ec_length = topology.get("extracellular_residue_count", 0) or 0
    # Read endocytosis + ubiquitination RAW (not `or 0`) so we can distinguish UNMEASURED (None —
    # the topology product carries topology only; PTM/endocytosis-motif fields are hardcoded None,
    # `_ptm_coverage: data_unavailable`) from a MEASURED zero. Coalescing to 0 conflated the two and
    # let an unmeasured field VETO the ADC branch — a coverage gap acting as a measured-negative,
    # which violates the framework's measured-vs-data_unavailable doctrine.
    endo_raw = topology.get("endocytosis_motif_count_high_confidence")
    n_ubiq_raw = topology.get("n_ubiquitination_sites")
    endo_measured = endo_raw is not None
    ubiq_measured = n_ubiq_raw is not None
    endo_high_conf = endo_raw or 0
    n_ubiq = n_ubiq_raw or 0
    # B1 Rank-2: curated clinical-precedent internalization signal. A gene with an approved/
    # late-clinical ADC (internalizing_antigen_targets.yaml) is internalizing by regulatory/trial
    # fact — a MEASURED-POSITIVE that supersedes the topology-only 'unmeasured' abstention. Positive-
    # only: a gene NOT in the vocab is unchanged (stays 'unmeasured'), never marked non-internalizing.
    clinically_internalizing = target.upper().strip() in _load_internalizing_antigens()
    # endocytosis_confidence — the card-declared field. Precedence: measured-motif (if the product
    # ever carries it) > curated clinical precedent > unmeasured. `clinically_internalizing` is a
    # distinct, honestly-labeled tier (NOT conflated with a measured motif count).
    if endo_measured:
        endocytosis_confidence = ("high" if endo_high_conf >= 3
                                  else "moderate" if endo_high_conf >= 1 else "low")
    elif clinically_internalizing:
        endocytosis_confidence = "clinically_internalizing"
    else:
        endocytosis_confidence = "unmeasured"

    if not is_surface or tm_count == 0:
        fit_class = "neither_viable"
    else:
        # ADC topology: single-pass TM + large ectodomain for antibody engagement. Internalization
        # (endocytosis) is genuinely an ADC determinant — but it is NOT measured in the current
        # topology product, so it must NOT hard-gate the call (an unmeasured field cannot veto).
        # ADC-favorability rests on the two LIVE topology inputs; the endocytosis term is satisfied
        # by EITHER a MEASURED motif signal (>=3) OR curated clinical-ADC precedent (Rank-2), and
        # ABSTAINS (doesn't veto) only when endocytosis is genuinely unmeasured AND uncurated.
        adc_topology_ok = (tm_count == 1 and ec_length >= 200)
        # endo_ok satisfied by: curated clinical-ADC precedent (regulatory FACT of internalization —
        # outranks a motif-count heuristic), OR a measured motif signal (>=3), OR — when endocytosis
        # is genuinely unmeasured AND uncurated — abstention (don't veto on a coverage gap, Rank-1).
        # An approved-ADC antigen is not gated out by a low PREDICTED motif count; the measured count
        # still sets endocytosis_confidence, but clinical precedent is a hard positive for the gate.
        if clinically_internalizing:
            endo_ok = True
        elif endo_measured:
            endo_ok = endo_high_conf >= 3
        else:
            endo_ok = True                            # unmeasured + uncurated → abstain, don't veto (Rank-1)
        adc_favorable = adc_topology_ok and endo_ok
        # TCE: bridges T-cell to tumor surface — endocytosis irrelevant. Low ubiquitination preferred
        # (high ubiq → fast internalization → target lost before engagement). Same discipline: an
        # UNMEASURED ubiquitination count must not veto (abstain, don't fail).
        ubiq_ok = (n_ubiq <= 3) if ubiq_measured else True           # unmeasured → abstain, don't veto
        tce_favorable = (tm_count >= 1 and ec_length >= 100 and ubiq_ok)
        if adc_favorable and tce_favorable:
            fit_class = "both_viable"
        elif adc_favorable:
            fit_class = "ADC_preferred"
        elif tce_favorable:
            fit_class = "TCE_preferred"
        else:
            fit_class = "modality_ambiguous"

    # Isoform-selective A3 suppression check
    if topology.get("isoform_selective_warning"):
        fit_class = "isoform_dependent_undefined"

    return {
        "fit_class": fit_class,
        "fit_rationale": f"tm_count={tm_count}, ec_length={ec_length}, "
                         f"endo_motif_hc={endo_high_conf if endo_measured else 'unmeasured'}, "
                         f"n_ubiq={n_ubiq if ubiq_measured else 'unmeasured'}",
        # Card-declared field (adc-tce-modality-fit.card.yaml) — previously never emitted. Makes the
        # endocytosis coverage state explicit: `unmeasured` today (topology product carries no
        # endocytosis-motif data), so an ADC_preferred call rests on topology + is flagged as
        # internalization-unverified rather than internalization-confirmed.
        "endocytosis_confidence": endocytosis_confidence,
        "is_adc_topology_favorable": tm_count == 1 and ec_length >= 200,
        "is_tce_topology_favorable": tm_count >= 1 and ec_length >= 100,
        "surface_family_class": family.get("family_class"),
        "isoform_selective_suppressed": bool(topology.get("isoform_selective_warning")),
        # structure-features-static passthrough (honors the card's derived_from) — carried for
        # display + a future ECD-epitope-quality rule; does NOT feed fit_class today. Empty/None
        # when the structure product is unavailable (the reader returns 'no_structure').
        "structure_epitope_context": {
            "hotspot_pocket_adjacency_call": structure.get("hotspot_pocket_adjacency_call"),
            "alphafold_confidence_class": structure.get("alphafold_confidence_class"),
            "disordered_fraction": structure.get("disordered_fraction"),
        },
        "_data_source": "adc-tce-modality-fit (composed card; no direct S3 product)",
    }


def _dispatch_surfaceome_cohort_ranking(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: surfaceome-cohort-ranking card → per-indication whole-
    surfaceome ranking via methods/surfaceome_cohort_ranking/read.py.
    """
    mod = _import_method("surfaceome_cohort_ranking")
    return mod.read_target_summary(target=target, indication=indication)


def _dispatch_protein_presence_cptac(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: tumor-protein-abundance-cptac card → CPTAC protein tumor-vs-normal
    DEG via methods/cptac_protein_deg/read.py.
    """
    mod = _import_method("cptac_protein_deg")
    return mod.read_target_summary(target=target, indication=indication)


_BREADTH_ELEVATED_CLASSES = frozenset({"broadly_tumor_elevated", "multi_tumor_elevated",
                                       "single_tumor_elevated"})


def _breadth_layer_concordance(protein_class: Optional[str], rna_class: Optional[str]) -> str:
    """Derive breadth_layer_concordance from the two per-layer breadth classes.

    Mirrors the card's vocabulary (tumor-elevation-breadth.card.yaml):
      concordant             — BOTH layers ELEVATED (any of broadly/multi/single) — strongest call
      concordant_not_elevated— BOTH layers MEASURED and both not_tumor_elevated — they agree the
                               target is NOT elevated (a measured negative agreement, NOT the
                               `concordant` elevation call — kept distinct so a consumer never
                               reads a non-elevated target as the "strongest breadth call")
      protein_only           — protein elevated, RNA a coverage gap (data_unavailable)
      rna_only               — RNA elevated, protein a coverage gap (CPTAC's 10 vs RNA's 27)
      discordant             — one layer ELEVATED, the other a MEASURED not_tumor_elevated —
                               surface, do not average (this branch DOES return discordant)
      single_layer           — only one layer had data (the other data_unavailable) — UNTESTED

    surface_discordance discipline: the two classes are NEVER averaged; this only NAMES the
    relationship for the reader. A data_unavailable layer is a coverage gap, not a negative —
    so it yields single_layer / protein_only / rna_only, never a false negative claim."""
    p_elev = protein_class in _BREADTH_ELEVATED_CLASSES
    r_elev = rna_class in _BREADTH_ELEVATED_CLASSES
    p_measured_neg = protein_class == "not_tumor_elevated"
    r_measured_neg = rna_class == "not_tumor_elevated"
    p_gap = protein_class in (None, "data_unavailable")
    r_gap = rna_class in (None, "data_unavailable")

    if p_gap and r_gap:
        return "single_layer"        # neither layer had data — degenerate; concordance untested
    if p_elev and r_elev:
        return "concordant"
    if p_elev and r_measured_neg:
        return "discordant"
    if r_elev and p_measured_neg:
        return "discordant"
    if p_elev and r_gap:
        return "protein_only"        # protein elevated; RNA a coverage gap (not a negative)
    if r_elev and p_gap:
        return "rna_only"            # RNA elevated; protein a coverage gap (CPTAC's 10 vs RNA's 27)
    # remaining: at least one measured-negative, neither elevated → not an elevation call
    if p_gap != r_gap:
        return "single_layer"        # exactly one layer had data, and it was a measured negative
    # both measured, both not-elevated → they AGREE the target is NOT elevated. This is a MEASURED
    # negative agreement, NOT the `concordant` ELEVATION call (which the card reserves for "both
    # elevated — strongest breadth call"); labeling it `concordant` would read as elevation.
    return "concordant_not_elevated"


def _dispatch_tumor_elevation_breadth(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: route tumor-elevation-breadth card → the TWO-LAYER pan-cancer breadth roll-up.

    Fuses two independent target-grain breadth readers (surface_discordance — surfaced
    ALONGSIDE, never averaged):
      - PROTEIN: methods/cptac_protein_deg::read_tumor_elevation_breadth (CPTAC, 10 cohorts) —
        drives the PRIMARY tumor_elevation_breadth_class.
      - RNA: methods/dge_deseq2::read_rna_tumor_elevation_breadth (pan-cancer DESeq2, 27
        indications) — the PARALLEL rna_* block.
    Then computes breadth_layer_concordance {concordant|protein_only|rna_only|discordant|
    single_layer} so the two-layer relationship is legible without collapsing to one number.

    TARGET-GRAIN, target-only — indication accepted for the dispatcher contract but NOT
    consumed (breadth is pan-cancer by construction). The one tumor-context presence card
    that fires without an indication.

    The RNA read degrades gracefully (returns a data_unavailable envelope) if its stacked
    product is unreachable, so a protein-only environment still yields the protein breadth +
    single_layer/protein-side concordance — never an error."""
    protein = _import_method("cptac_protein_deg").read_tumor_elevation_breadth(target=target)
    protein = protein or {}
    try:
        rna = _import_method("dge_deseq2").read_rna_tumor_elevation_breadth(target=target) or {}
    except Exception as e:
        # RNA layer unreachable — surface an honest data_unavailable envelope, don't fail the card.
        rna = {"rna_tumor_elevation_breadth_class": "data_unavailable",
               "_rna_read_error": f"{type(e).__name__}: {e}"}

    # The RNA reader emits GENERIC field names (n_indications_tested, ...); the card contract
    # (tumor-elevation-breadth.card.yaml, Slice C-4) declares them rna_-PREFIXED so they never
    # collide with the protein layer's n_cohorts_* fields. Namespace them here so the card's
    # declared summary_fields resolve (the class field is already rna_-prefixed by the reader).
    _RNA_FIELD_MAP = {
        "n_indications_tested": "rna_n_indications_tested",
        "n_indications_elevated": "rna_n_indications_elevated",
        "fraction_elevated": "rna_fraction_elevated",
        "median_max_log2fc_across_elevated": "rna_median_max_log2fc_across_elevated",
        "most_elevated_indications": "rna_most_elevated_indications",
    }
    rna_ns = {_RNA_FIELD_MAP.get(k, k): v for k, v in rna.items()}

    merged = dict(protein)                       # protein fields (incl. the PRIMARY class) verbatim
    merged.update(rna_ns)                        # rna_-namespaced fields are disjoint — no clobber
    merged["breadth_layer_concordance"] = _breadth_layer_concordance(
        protein.get("tumor_elevation_breadth_class"),
        rna.get("rna_tumor_elevation_breadth_class"),
    )
    return merged


def _dispatch_paralog_buffering(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: paralog-buffering card → DepMap PARIS + Sanger paralog fusion
    via methods/depmap_paralog_aggregator/read.py.
    """
    mod = _import_method("depmap_paralog_aggregator")
    return mod.read_target_summary(target=target, indication=indication)


def _dispatch_gnomad_lof_constraint(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: gnomad-lof-constraint card → gnomAD constraint table lookup.
    The gnomAD constraint manifest is a simple per-gene TSV; a light method
    read.py handles the load + row filter.
    """
    mod = _import_method("gnomad_constraint")
    return mod.read_target_summary(target=target, indication=indication)


def _dispatch_clinvar_pathogenicity(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: clinvar-pathogenicity-safety card (P5 follow-on) -> methods/opentargets_clinvar/
    read.py::read_clinvar_pathogenic. ClinVar germline-pathogenic safety (somatic guardrailed out).
    A 4th corroborating germline leg. Per-target (indication not consumed)."""
    mod = _import_method("opentargets_clinvar.read")
    return mod.read_clinvar_pathogenic(target, indication)


def _dispatch_mouse_ko_phenotype(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: mouse-ko-phenotype card (P5 Slice 4) -> methods/opentargets_mouse_phenotype/read.py
    ::read_mouse_ko_phenotype. Mouse-KO normal-physiology safety (developmental-guardrailed): adult
    lethality = adult-essential signal; embryonic/preweaning = caveat. INFERRED (model). Per-target."""
    mod = _import_method("opentargets_mouse_phenotype.read")
    return mod.read_mouse_ko_phenotype(target, indication)


def _dispatch_clingen_dosage(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: clingen-dosage card (P5 Slice 3) -> methods/opentargets_clingen/read.py::
    read_clingen_dosage. ClinGen dosage sensitivity: is single-copy loss pathogenic (autosomal-
    dominant / haploinsufficiency) = a full-KO safety concern? Per-target (indication not consumed)."""
    mod = _import_method("opentargets_clingen.read")
    return mod.read_clingen_dosage(target, indication)


def _dispatch_gene_burden_safety(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: gene-burden-safety card (P5 Slice 2, first verdict-moving) →
    methods/opentargets_gene_burden/read.py::read_gene_burden.

    Population rare-variant burden LoF-tolerance: does losing this gene's function increase
    disease risk (a WT-loss full-KO safety signal) or protect (drug-positive)? Direction from
    directionOnTrait (directionOnTarget is uniformly LoF). Per-target (indication accepted, not
    consumed — burden is across many diseases; top_disease surfaces the driving trait)."""
    mod = _import_method("opentargets_gene_burden.read")
    return mod.read_gene_burden(target, indication)


def _dispatch_target_safety_prioritisation(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: target-safety-prioritisation card (P5 Slice 1) →
    methods/opentargets_target_prioritisation/read.py::read_target_prioritisation.

    A CONTEXT view of Open Targets 26.06 engineered target-prioritisation scores (safety-event,
    genetic-constraint, mouse-KO) — verdict-inert orientation for the safety skill, NOT a per-fact
    read. Per-target (indication accepted for the contract, not consumed — OT prioritisation is one
    row per gene). The authoritative per-fact reads are gnomad-lof-constraint + the P5 Slices 2-4
    measured cards."""
    mod = _import_method("opentargets_target_prioritisation.read")
    return mod.read_target_prioritisation(target, indication)


def _dispatch_synthetic_lethal_partners(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: synthetic-lethal-partners card → curated SynLethDB SL-partner
    annotation via methods/synleth_partner_lookup/read.py. Gate-C context-conditional
    dependency: an experimentally-supported curated SL partner suppresses the pooled
    non_dependent veto (SMARCA2←SMARCA4). Gene-level — indication accepted, not consumed.
    """
    mod = _import_method("synleth_partner_lookup")
    return mod.read_target_summary(target=target, indication=indication)


def _dispatch_normal_tissue_liability(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: normal-tissue-liability card → HPA IHC normal-tissue footprint via
    methods/hpa_normal_tissue_liability/read.py. The dominant biologics on-target-off-
    tumor safety signal (TROP2/HER2-class normal-tissue tox). Gene-level — indication
    accepted for contract, not consumed.
    """
    mod = _import_method("hpa_normal_tissue_liability")
    return mod.read_target_summary(target=target, indication=indication)


def _dispatch_protein_abundance_celline(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: cellline-protein-abundance card → DepMap 26Q1 proteomics Gygi TMT MS
    cell-line protein-abundance distribution via methods/depmap_protein_abundance/read.py.
    The bulk_protein_ms x cell_line presence axis (protein twin of cellline-rna-distribution).
    Protein-intrinsic — indication accepted for contract, not consumed.
    """
    mod = _import_method("depmap_protein_abundance")
    return mod.read_target_summary(target=target, indication=indication)


def _dispatch_shed_ectodomain_liability(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: shed-ectodomain-liability card → curated serum-marker crosswalk
    (target-contracts vocab) + HPA v25-1 secretome proxy via
    methods/shed_ectodomain_liability/read.py. Gate-F surface-window no-go:
    a shed circulating ectodomain is an antigen sink for antibody/ADC/TCE.
    Protein-intrinsic — indication accepted for contract, not consumed.
    """
    mod = _import_method("shed_ectodomain_liability")
    return mod.read_target_summary(target=target, indication=indication)


CARD_DISPATCHERS = {
    "target-identity-summary": _dispatch_target_identity_summary,
    "tumor-rna-vs-adjacent": _dispatch_expression_tumor_vs_adjacent,
    "dependency-lineage-selectivity": _dispatch_dependency_lineage_selectivity,
    "mutation-hotspot-frequency": _dispatch_mutation_hotspot_frequency,
    "alteration-role": _dispatch_alteration_role,
    "genomic-instability-state": _dispatch_genomic_instability_state,
    "variant-level-interpretation": _dispatch_variant_level_interpretation,
    "functional-gene-state": _dispatch_functional_gene_state,
    "genomic-event-model-match": _dispatch_genomic_event_model_match,
    "fusion-rearrangement-landscape": _dispatch_fusion_rearrangement_landscape,
    "pan-cancer-crispr-dependency-distribution": _dispatch_pan_cancer_dependency_distribution,
    "pan-cancer-rnai-dependency-distribution": _dispatch_pan_cancer_rnai_dependency_distribution,
    "crispr-rnai-dependency-concordance": _dispatch_crispr_rnai_dependency_concordance,
    "cellline-rna-distribution": _dispatch_expression_distribution,
    "tumor-rna-distribution": _dispatch_tumor_expression_distribution,
    "tumor-rna-distribution-by-subtype": _dispatch_tumor_expression_distribution_subtype,
    "tumor-scrna-celltype-expression": _dispatch_sc_tumor_celltype_expression,   # sc_rna/tumor bucket (single-cell per-compartment presence)
    "tumor-vs-normal-percentile-crossing": _dispatch_tumor_vs_normal_percentile_crossing,
    "normal-tissue-liability-gtex": _dispatch_normal_tissue_liability_gtex,
    "recommended-models": _dispatch_recommended_models,
    "cellline-rna-protein-concordance": _dispatch_rna_protein_concordance,
    "rna-protein-concordance-tumor": _dispatch_rna_protein_concordance_tumor,
    "expression-dependency-correlation": _dispatch_expression_dependency_correlation,
    "abundance-dependency": _dispatch_abundance_dependency,
    "expression-purity-confound": _dispatch_expression_purity_confound,
    "expression-clinical-association": _dispatch_expression_clinical_association,
    "phospho-pathway-activity": _dispatch_phospho_pathway_activity,
    "copy-number-distribution": _dispatch_cn_distribution,
    "mutation-type-counts": _dispatch_mutation_type_counts,
    "mutation-stratified-dependency": _dispatch_mutation_stratified_dependency,
    "copy-number-stratified-dependency": _dispatch_cn_stratified_dependency,
    "dependency-predictability": _dispatch_dependency_predictability,
    "prism-compound-activity": _dispatch_prism_compound_activity,
    "prism-crispr-concordance": _dispatch_prism_crispr_concordance,
    "tumor-vs-normal-selectivity": _dispatch_tumor_vs_normal_selectivity,
    # RT1 fix-rollup 2026-07-09: 11 Phase D/E/F/G card dispatchers
    "signaling-network-mechanism": _dispatch_signaling_network_mechanism,
    "reactome-pathway-membership": _dispatch_reactome_pathway_membership,  # target-intrinsic pathway/geneset membership
    "gene-ontology-annotation": _dispatch_gene_ontology_annotation,  # target-intrinsic GO BP/MF/CC membership
    "ppi-interactome": _dispatch_ppi_interactome,  # target-intrinsic STRING network + CORUM complexes
    "protein-domains-class": _dispatch_protein_domains_class,  # target-intrinsic domain architecture + protein class
    "co-mutation-and-mutual-exclusivity": _dispatch_co_mutation_and_mutual_exclusivity,
    "surface-topology-and-ptm": _dispatch_surface_topology_and_ptm,
    "surfaceome-family-classification": _dispatch_surfaceome_family_classification,
    "structure-features-static": _dispatch_structure_features_static,
    "protein-surface-evidence": _dispatch_protein_surface_evidence,
    "surface-abundance-density": _dispatch_surface_abundance_density,
    "adc-tce-modality-fit": _dispatch_adc_tce_modality_fit,
    "surfaceome-cohort-ranking": _dispatch_surfaceome_cohort_ranking,
    "tumor-protein-abundance-cptac": _dispatch_protein_presence_cptac,
    "tumor-elevation-breadth": _dispatch_tumor_elevation_breadth,
    "paralog-buffering": _dispatch_paralog_buffering,
    "gnomad-lof-constraint": _dispatch_gnomad_lof_constraint,
    "target-safety-prioritisation": _dispatch_target_safety_prioritisation,   # P5 Slice 1 (OT safety context)
    "gene-burden-safety": _dispatch_gene_burden_safety,                        # P5 Slice 2 (OT rare-variant burden, verdict-moving)
    "clingen-dosage": _dispatch_clingen_dosage,                                # P5 Slice 3 (ClinGen dosage sensitivity, verdict-moving)
    "mouse-ko-phenotype": _dispatch_mouse_ko_phenotype,                        # P5 Slice 4 (mouse-KO normal-physiology, developmental-guardrailed)
    "clinvar-pathogenicity-safety": _dispatch_clinvar_pathogenicity,           # P5 follow-on (ClinVar germline-pathogenic, verdict-moving)
    "shed-ectodomain-liability": _dispatch_shed_ectodomain_liability,
    "cellline-protein-abundance": _dispatch_protein_abundance_celline,
    "normal-tissue-liability": _dispatch_normal_tissue_liability,
    "synthetic-lethal-partners": _dispatch_synthetic_lethal_partners,
    # Iter-1b execution session adds (each as a dispatcher to a methods/<method>/read.py):
    #   "tumor-vs-normal-selectivity": _dispatch_tumor_vs_normal_selectivity,
    #       → methods/dge_deseq2/read.py + (future) methods/gtex_normal_tissue/read.py
    #   "antigen-prevalence": _dispatch_antigen_prevalence,
    #       → methods/dge_deseq2/read.py (per-sample expression matrix)
    #   "rwd-stratified-expression": _dispatch_rwd_stratified_expression,
    #       → methods/tempus_rwd_aggregator/read.py
    #   "subgroup-stratified-expression": _dispatch_subgroup_stratified_expression,
    #       → BLOCKED (2026-07-16): dge-deseq2 is an emit-time aggregate; no per-sample
    #         reader. Card tagged blocked_needs_per_sample_reader in target-contracts.
}

# Subgroup-panorama dispatchers (2026-07-16). Kept SEPARATE from CARD_DISPATCHERS
# because they take a different signature — they need the resolved strata +
# assignments-shard id from subgroup_context. read_live_summary routes here when a
# card_id is present AND subgroups are in scope. Value = (dispatcher, indication→manifest map).
PANORAMA_DISPATCHERS = {
    "subgroup-stratified-mutation-frequency": (
        _dispatch_subgroup_stratified_mutation_frequency, _MUTATION_ASSIGNMENTS_MANIFEST),
    "subgroup-stratified-dependency": (
        _dispatch_subgroup_stratified_dependency, _DEPENDENCY_ASSIGNMENTS_MANIFEST),
}


def read_live_summary(card_id: str, target: str, indication: str,
                       subgroup_context: Optional[dict] = None) -> Optional[dict]:
    """Dispatch a live-read for the named card to its corresponding method module.

    Two dispatch paths:
      - PANORAMA (subgroup-aware): if the card is in PANORAMA_DISPATCHERS AND
        subgroup_context carries resolved_strata_ids, route to the per-sample
        panorama builder with the resolved strata + assignments-shard id. This is
        the descriptive subgroup panorama — it returns per_subgroup_metrics.
      - SCALAR (default): route to CARD_DISPATCHERS with (target, indication).

    subgroup_context (the run_plan's subgroup_resolution) shape:
      {subgroup_catalog_ref, catalog_status, resolved_strata_ids, applicable_data_sources}.
    Accepting the kwarg (rather than the legacy scalar-only signature) is what lets
    _execution._call_live_reader pass it through without hitting the TypeError shim.

    Returns None if no dispatcher exists yet (caller falls back to stub or marks failed).
    """
    ctx = subgroup_context or {}
    subgroups = ctx.get("resolved_strata_ids") or []

    # Panorama path: only when the card is panorama-capable AND strata are in scope.
    panorama = PANORAMA_DISPATCHERS.get(card_id)
    if panorama is not None:
        if not subgroups:
            # Panorama card invoked without a resolved subgroup scope — nothing to
            # enumerate. Return a data-note rather than erroring (the card is only
            # admitted when subgroup_spec != null, but guard defensively).
            return {"_data_note": f"{card_id} requires resolved subgroups; none in scope"}
        dispatcher, manifest_map = panorama
        manifest_id = manifest_map.get(indication)
        if manifest_id is None:
            return {"_data_note": f"no subgroup-assignments shard for indication={indication!r} "
                                  f"(iter-1b ships COADREAD only)"}
        try:
            return dispatcher(target=target, indication=indication,
                              subgroups=subgroups, subgroup_assignments_manifest=manifest_id)
        except Exception as e:
            return {"_live_read_error": str(e)}

    dispatcher = CARD_DISPATCHERS.get(card_id)
    if dispatcher is None:
        return None
    try:
        return dispatcher(target=target, indication=indication)
    except Exception as e:
        return {"_live_read_error": str(e)}
