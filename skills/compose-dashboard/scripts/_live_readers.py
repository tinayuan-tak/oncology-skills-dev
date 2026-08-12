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
    # 2026-08-11 REVIEW FIX (N2): emit expression_call_class on the non-COADREAD path too.
    # The COADREAD branch (read_dge_gene_row) emits expression_call_class via
    # _classify_expression_call; this branch previously returned only log2_fc/q_value, so the 6
    # tumor-rna-vs-adjacent interpretation rules (all keyed on field: expression_call_class) could
    # NEVER fire for 26 of 27 indications — silently changing the presence driving_rule_id, dropping
    # the tumor-vs-adjacent contribution to the bulk_rna bucket, and disabling the degrader-killer
    # rules (strong-downregulation / not-informative) everywhere except COADREAD. Reuse the SAME
    # classifier over the SAME two fields the COADREAD path uses (cell A = tumor vs adjacent-normal),
    # so the two indication paths become emit-consistent.
    log2_fc = sen.get("log2fc_cell_a")            # cell A = TCGA tumor vs adjacent-normal
    q_value = sen.get("q_value_cell_a")
    # _classify_expression_call lives in the method's `read` submodule and is NOT re-exported at the
    # package level (__all__), so reach it via .read — the same module read_dge_gene_row comes from.
    _classify = dge_module.read._classify_expression_call
    return {
        "log2_fc": log2_fc,
        "q_value": q_value,
        "expression_call_class": _classify(log2_fc, q_value),
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
    """Dispatcher: route genomic-instability-state card to methods/tcga_aneuploidy_burden.

    INDICATION-level, target-INDEPENDENT (aneuploidy + WGD + MSI are genome-wide cohort phenotypes) —
    the `target` arg is accepted for dispatcher-signature uniformity but IGNORED. MERGES three axes
    from the same method module (the multi-function-merge pattern the fusion dispatcher uses for
    GENIE-SV):
      - aneuploidy_burden_for_indication() — per-sample frac_altered CIN burden (seg_based_scores)
      - wgd_summary_for_indication()       — whole-genome-doubling prevalence + ploidy (ABSOLUTE)
      - msi_summary_for_indication()       — PATIENT MSI prevalence (marker-paper; CRC+STAD only)
      - model_msi_summary_for_indication() — MODEL (DepMap) MSI prevalence (all lineages; fills the gap)
      - model_signature_summary_for_indication() — MODEL SBS signatures (MMR cross-validates MSI; weak SBS3-HRD)
    Each degrades to data_unavailable independently. DISPLAY facet, verdict-inert."""
    mod = _import_method("tcga_aneuploidy_burden")
    out = dict(mod.aneuploidy_burden_for_indication(indication))

    def _merge_axis(fn_name, keys, class_key):
        """Merge an additive axis's fields into `out`; never break the burden read."""
        try:
            axis = getattr(mod, fn_name)(indication)
            for k in keys:
                out[k] = axis.get(k)
        except Exception:  # noqa: BLE001 — additive axis; a failure degrades, never breaks
            for k in keys:
                out.setdefault(k, None)
            out[class_key] = "data_unavailable"

    _merge_axis("wgd_summary_for_indication",
                ("wgd_class", "wgd_fraction", "n_wgd_samples", "median_ploidy",
                 "median_purity", "wgd_context"), "wgd_class")
    _merge_axis("msi_summary_for_indication",
                ("msi_class", "msi_high_fraction", "n_msi_high", "msi_context"), "msi_class")
    # MODEL-side MSI (DepMap MSIsensor) — all-lineage complement; covers NSCLC/PAAD that patient labels miss.
    _merge_axis("model_msi_summary_for_indication",
                ("model_msi_class", "model_msi_high_fraction", "n_model_msi_high",
                 "model_msi_context"), "model_msi_class")
    # MODEL mutational-signature (DepMap SBS): MMR-sig cross-validates MSI + weak SBS3-HRD proxy.
    _merge_axis("model_signature_summary_for_indication",
                ("model_mmr_signature_class", "model_mmr_signature_high_fraction",
                 "model_hrd_signature_present_fraction", "model_signature_context"),
                "model_mmr_signature_class")
    return out


def _dispatch_ddr_deficiency_context(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: route ddr-deficiency-context card to methods/pancanatlas_ddr_context.

    INDICATION-level, target-INDEPENDENT (HRD/DDR deficiency is a cohort phenotype) — the `target`
    arg is accepted for dispatcher-signature uniformity but IGNORED. Reads the materialized
    per-indication DDR/HRD rollup (PanCanAtlas DDR footprint, Knijnenburg 2018) → ddr_context_class.
    DISPLAY facet, verdict-inert (no resolver rung); the cohort HRD prior that frames the PARP1/HRD
    blind axis. Sibling of _dispatch_genomic_instability_state."""
    mod = _import_method("pancanatlas_ddr_context")
    return mod.read_ddr_deficiency_context(target=target, indication=indication)


def _dispatch_mutational_signature_context(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: route mutational-signature-context card to methods/tcga_mc3_signatures.

    INDICATION-level, target-INDEPENDENT (the mutagenic-process profile is a cohort phenotype) — the
    `target` arg is accepted for dispatcher-signature uniformity but IGNORED. Reads the materialized
    per-indication rollup (TCGA MC3 → SigProfilerAssignment COSMIC v3.3) → dominant_process +
    per-process classes. DISPLAY facet, verdict-inert (no resolver rung); the PATIENT/tumour arm of
    mutagenic-process context — sibling of _dispatch_ddr_deficiency_context (HRD footprint) and the
    model-side MMR/HRD arm of _dispatch_genomic_instability_state."""
    mod = _import_method("tcga_mc3_signatures")
    return mod.read_mutational_signature_context(target=target, indication=indication)


def _dispatch_oncogenic_pathway_alteration(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: route oncogenic-pathway-alteration card to methods/oncogenic_pathway_alteration.

    INDICATION-level, target-INDEPENDENT (pathway alteration is a cohort phenotype). Reads the
    per-(pathway x indication) alteration-frequency rollup (Sanchez-Vega 2018) + the target's own
    pathway membership. DISPLAY facet, verdict-inert (sibling of pathway-activity-context)."""
    mod = _import_method("oncogenic_pathway_alteration")
    return mod.read_oncogenic_pathway_alteration(target=target, indication=indication)
def _dispatch_stemness_context(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: route stemness-context card to methods/stemness_index.

    INDICATION-level, target-INDEPENDENT (tumor stemness is a cohort phenotype). Reads the per-indication
    mRNAsi rollup (Malta 2018 signature, reimplemented on recount3) → cohort stemness class. DISPLAY
    facet, verdict-inert (dedifferentiation/aggressiveness prognostic prior)."""
    mod = _import_method("stemness_index")
    return mod.read_stemness_index(target=target, indication=indication)
def _dispatch_target_development_level(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: route target-development-level card to methods/pharos_tdl.

    TARGET-INTRINSIC (indication-independent). O(1) HGNC lookup on the Pharos/IDG TDL snapshot →
    tdl_class (Tclin/Tchem/Tbio/Tdark) + family + novelty. DISPLAY facet, verdict-inert."""
    mod = _import_method("pharos_tdl")
    return mod.read_pharos_tdl(target=target, indication=indication)


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
        if subgroup_assignments_manifest is None:
            # No molecular/TCGA shard for this indication (e.g. NSCLC ships only a GENIE-BPC LOT
            # shard) — emit an honest per-axis data-note instead of calling the builder with a
            # null manifest; the LOT arm below still serves the LOT_* strata.
            panoramas.append({"per_subgroup_metrics": [], "_data_note":
                f"molecular strata {molecular_strata} requested but no molecular subgroup-"
                f"assignments shard for indication={indication!r}"})
        else:
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


def _dispatch_precog_prognostic(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: route precog-prognostic-association card to methods/precog_prognostic.

    Across 166 datasets (~18k patients), does target expression track overall survival (PRECOG
    pan-cancer META-ANALYTIC meta-Z; Gentles 2015 + 2026 NAR)? POSITIVE meta-Z = high expr → worse OS.
    TARGET-dependent (the meta-Z is gene-specific). The better-powered pan-cancer CORROBORATION of the
    single-cohort expression-clinical-association card. DISPLAY facet — verdict-inert (no resolver rung)."""
    mod = _import_method("precog_prognostic")
    return mod.read_precog_prognostic(target=target, indication=indication)


def _dispatch_phospho_pathway_activity(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: route phospho-pathway-activity card (Q8) to
    methods/phospho_pathway_activity/cli.py::build_summary.

    Is the target phosphorylated (pathway-activity proxy) in the indication's CPTAC tumors, beyond
    its total abundance? Reads the cptac package's harmonized phosphoproteomics [bcm]. Indication-scoped."""
    mod = _import_method("phospho_pathway_activity.cli")
    return mod.build_summary(target, indication)



def _dispatch_pathway_activity_context(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: route pathway-activity-context card to methods/progeny_pathway_activity.

    INDICATION-level, target-INDEPENDENT (PROGENy pathway activity is a cohort phenotype). Reads the
    materialized per-(pathway x indication) PROGENy activity rollup (Schubert 2018) and returns the
    cohort's relatively-active/low pathways + the target's own pathway membership. DISPLAY facet,
    verdict-inert (sibling of phospho-pathway-activity in the Mechanism space)."""
    mod = _import_method("progeny_pathway_activity")
    return mod.read_progeny_pathway_activity(target=target, indication=indication)


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

    MERGES an additive isoform-EXPRESSION facet (roadmap #2 model arm) from a SEPARATE method
    module (depmap_isoform_expression -> depmap-isoform-expression-per-gene-v1): how dominated
    the gene's expression is by a single transcript across the panel. ORTHOGONAL to the
    expression-LEVEL fields (how MUCH vs WHICH transcript). Verdict-inert; degrades to
    data_unavailable on any failure without breaking the primary expression read. The method's
    `n_models` is remapped to the card field `isoform_n_models` to avoid colliding with the
    expression panel's own cell-line count."""
    expr_module = _import_method("depmap_expression_distribution")
    out = dict(expr_module.read_expression_distribution(target=target, indication=indication))
    try:
        iso_mod = _import_method("depmap_isoform_expression")
        iso = iso_mod.isoform_summary_for_gene(target)
        out["isoform_expression_class"] = iso.get("isoform_expression_class")
        out["dominant_isoform_fraction"] = iso.get("dominant_isoform_fraction")
        out["n_expressed_isoforms"] = iso.get("n_expressed_isoforms")
        out["dominant_isoform"] = iso.get("dominant_isoform")
        out["isoform_n_models"] = iso.get("n_models")
        out["isoform_context"] = iso.get("isoform_context")
    except Exception:  # noqa: BLE001 — additive facet; a failure degrades, never breaks the read
        out.setdefault("isoform_expression_class", "data_unavailable")
        for k in ("dominant_isoform_fraction", "n_expressed_isoforms", "dominant_isoform",
                  "isoform_n_models", "isoform_context"):
            out.setdefault(k, None)
    return out


def _dispatch_tumor_expression_distribution(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: route tumor-rna-distribution card (Q1) to
    methods/tcga_gtex_expression_distribution/cli.py::build_summary.

    Per-SAMPLE tumor RNA distribution (percentiles, detectable/moderate/high fraction, CoV,
    distribution_pattern) + matched-normal fraction-above-p95 overlay, from the TCGA + GTEx long
    products. Indication-scoped (the tumor distribution is per-indication).

    MERGES an additive patient-SPLICING facet (roadmap #2 patient arm) from a SEPARATE method
    module (tcga_spliceseq_psi -> tcga-spliceseq-psi-per-gene-v1): whether the gene's SPLICING is
    dysregulated in patient tumours (TCGA SpliceSeq PSI variability + tumour-vs-normal shift).
    ORTHOGONAL to the expression-LEVEL fields (how MUCH vs which SPLICE EVENTS shift); the patient
    complement to the model-arm isoform facet on cellline-rna-distribution. Verdict-inert; degrades
    to data_unavailable on any failure without breaking the primary distribution read."""
    mod = _import_method("tcga_gtex_expression_distribution.cli")
    out = dict(mod.build_summary(target, indication))
    try:
        ss_mod = _import_method("tcga_spliceseq_psi")
        ss = ss_mod.spliceseq_summary_for_gene(target, indication)
        for k in ("splicing_dysregulation_class", "n_splice_events", "max_event_psi_std",
                  "median_event_psi_std", "n_variable_events", "n_tumor_shifted_events",
                  "dominant_event_splice_type", "splicing_context"):
            out[k] = ss.get(k)
    except Exception:  # noqa: BLE001 — additive facet; a failure degrades, never breaks the read
        out.setdefault("splicing_dysregulation_class", "data_unavailable")
        for k in ("n_splice_events", "max_event_psi_std", "median_event_psi_std",
                  "n_variable_events", "n_tumor_shifted_events", "dominant_event_splice_type",
                  "splicing_context"):
            out.setdefault(k, None)
    return out


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


def _dispatch_sc_normal_celltype_expression(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: route sc-normal-celltype-expression card (sc_rna/normal SAFETY COMPARATOR
    bucket) to methods/sc_normal_expression/cli.py::build_summary.

    scRNA cell-type-resolved NORMAL-tissue presence from the CELLxGENE Census normal pseudobulk
    product (per-cell-type detection_fraction → sc_normal_expression_class). NOT a tumor-presence
    signal — a normal-tissue comparator consumed by tumor-presence (framing) + surface-modality-fit
    (safety). Indication-scoped (v1 shards: colon→COADREAD, lung→NSCLC); other indications →
    data_unavailable. Was in both skills' CARDS since #267 but had no dispatcher here → read_live
    returned None → run_health degraded on every run; this closes that gap."""
    mod = _import_method("sc_normal_expression.cli")
    return mod.build_summary(target, indication)


def _dispatch_known_drug_tractability(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: route known-drug-tractability card (DGIdb pharmacology leg of small-molecule
    tractability) to methods/dgidb_drug_gene/read.py::known_drug_tractability_for_gene.

    Target-grain (DGIdb drug-gene interactions + druggable-genome categories are a target property);
    indication accepted for the CARD_DISPATCHERS contract but NOT consumed. Wired into
    tractability-small-molecule CARDS (#272) but had no dispatcher here → degraded runs; this closes it."""
    mod = _import_method("dgidb_drug_gene")
    return mod.known_drug_tractability_for_gene(target)


def _dispatch_measured_potency_tractability(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: route measured-potency-tractability card (ChEMBL + BindingDB MEASURED binding
    potency — the measured-potency leg of small-molecule tractability, T3.1) to
    methods/measured_potency_tractability/read.py::measured_potency_for_gene.

    Target-grain (measured potency is a property of the gene's chemical matter); indication accepted
    for the CARD_DISPATCHERS contract but NOT consumed."""
    mod = _import_method("measured_potency_tractability")
    return mod.measured_potency_for_gene(target)


def _dispatch_mutation_stratified_surface(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: route mutation-stratified-surface card (is a surface antigen elevated in a
    driver's MUTANT tumor subset?) to methods/mutation_stratified_surface/read.py::
    read_mutation_stratified_surface.

    Indication-scoped; driver defaults inside the method (v1 covers KRAS/NSCLC only → not_in_product
    elsewhere, an honest coverage gap). Wired into surface-modality-fit CARDS (#276) but had no
    dispatcher here → degraded runs; this closes it."""
    mod = _import_method("mutation_stratified_surface")
    return mod.read_mutation_stratified_surface(target, indication=indication)


def _dispatch_pathway_stratified_surface(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: route pathway-stratified-surface card (is a surface antigen elevated in a
    tumor-STATE-HIGH subset?) to methods/pathway_stratified_surface/read.py::
    read_pathway_stratified_surface.

    Indication-scoped; signature defaults inside the method (v1 covers HALLMARK_HYPOXIA/NSCLC only →
    not_in_product elsewhere, an honest coverage gap). Wired into surface-modality-fit CARDS (#280)
    but had no dispatcher here → degraded runs; this closes it."""
    mod = _import_method("pathway_stratified_surface")
    return mod.read_pathway_stratified_surface(target, indication=indication)


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


def _dispatch_sc_surface_concordance(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: route sc-surface-rna-protein-concordance card to
    methods/sc_surface_concordance/cli.py::build_summary.

    Single-cell RNA vs SURFACE protein (CITE-seq ADT) concordance across cell types → rna_as_biomarker
    (surface arm). Target-grain (concordance is a per-target property); indication accepted for the
    contract, NOT consumed. The single-cell surface sibling of the cell-line + tumor concordance cards."""
    mod = _import_method("sc_surface_concordance.cli")
    return mod.build_summary(target, indication)


def _dispatch_surface_colocalization_avidity(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: route surface-colocalization-avidity card to
    methods/pair_selectivity_gate/cli.py::build_summary.

    Target-centric same-cell avidity: scans the indication's same-cell coexpr cube for every pair
    involving the target → best-partner samecell_avidity_class (bispecific AND-gate co-localization).
    Indication-scoped (the cube is per-indication)."""
    mod = _import_method("pair_selectivity_gate.cli")
    return mod.build_summary(target, indication)


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
    """Dispatcher: route copy-number-distribution card (E3.b) to methods/depmap_cn_distribution.

    WES-primary + WGS-fallback for the CELL-LINE arm (copy_number_class — verdict-driving, pan-cancer;
    indication not consumed by that path). MERGES a PATIENT-tumour CN cross-check (tcga_patient_cn,
    TCGA GISTIC, INDICATION-specific) — the two-function-merge pattern the genome-state + fusion cards
    use. Of the merged patient_* fields the two have DIFFERENT verdict status: the ANY-gain
    patient_copy_number_class is ADDITIVE/display-only (fires no rule), but patient_focal_cn_class
    (high-level +2 / homdel -2) IS VERDICT-BEARING — it fires the CN-consensus rung
    (cn-patient-focal-amplified/deleted-supportive), so the CN verdict rests on the cell-line
    copy_number_class OR patient focal CN (see the REQUIRED note below). Each arm degrades independently.
    """
    cn_module = _import_method("depmap_cn_distribution")
    out = dict(cn_module.read_cn_distribution(target=target, indication=indication))
    # patient_focal_cn_class is REQUIRED: it's the field the CN-consensus verdict rules
    # (cn-patient-focal-amplified/deleted-supportive) fire on — without it the rescue can't trigger.
    _PCN_KEYS = ("patient_copy_number_class", "patient_focal_cn_class",
                 "patient_amplified_fraction", "patient_high_amp_fraction",
                 "patient_deleted_fraction", "patient_homdel_fraction", "patient_cn_context")
    try:
        pcn = _import_method("tcga_patient_cn").patient_cn_summary_for_gene(target, indication)
        for k in _PCN_KEYS:
            out[k] = pcn.get(k)
    except Exception:  # noqa: BLE001 — patient CN is additive; never break the cell-line read
        for k in _PCN_KEYS:
            out.setdefault(k, None)
        out["patient_copy_number_class"] = "data_unavailable"
        out["patient_focal_cn_class"] = "data_unavailable"
    return out


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


def _dispatch_partner_conditional_dependency(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: route partner-conditional-dependency card (Card C.pc) to
    methods/depmap_partner_conditional_dependency/read.py.

    The PARTNER-feature analog of Card 3 / Card E3.cn: does a target's dependency stratify by a
    PARTNER gene's DEFICIENCY status (MSI-high signature OR partner LoF) across the DepMap panel —
    the synthetic-lethality biomarker hypothesis (WRN×MSI-class)? Target-only; indication accepted
    for back-compat but not consumed. Returns no_partner_mapped (abstains) for unmapped targets.
    """
    pc_module = _import_method("depmap_partner_conditional_dependency")
    return pc_module.read_partner_conditional_dependency(target=target, indication=indication)



def _dispatch_cross_consortium_dependency(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: route cross-consortium-dependency card to methods/cross_consortium_dependency.

    Gate-C CORROBORATION: does Sanger Project Score agree with Broad Achilles on the dependency call?
    Reads the landed DepMap Broad (CRISPRGeneEffect) + Sanger-inclusive (ScreenGeneEffect) Chronos.
    tier: target; verdict-inert (raises C-confidence, never a killer)."""
    mod = _import_method("cross_consortium_dependency")
    return mod.read_cross_consortium_dependency(target=target, indication=indication)


def _dispatch_fusion_stratified_dependency(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: route fusion-stratified-dependency card (Card E3.fus) to
    methods/depmap_fusion_dependency/read.py.

    The gene-fusion analog of Card 3 / Card E3.cn: does a target's dependency stratify by
    whether the line carries a fusion INVOLVING the target (either partner) across the DepMap
    panel — the fusion-addiction biomarker hypothesis (EWSR1-FLI1/BCR-ABL1-class, invisible to
    the mutation + CN paths)? Target-only; indication accepted for back-compat but not consumed.
    """
    fus_module = _import_method("depmap_fusion_dependency")
    return fus_module.read_fusion_stratified_dependency(target=target, indication=indication)


def _dispatch_amp_expr_stratified_dependency(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: route amp-expr-stratified-dependency card (Card E3.ae) to
    methods/depmap_amp_expr_dependency/read.py.

    The conjoint (amplification+overexpression) three-way analog of Card E3.cn: does a target's
    dependency stratify by whether the line is BOTH amplified (relative CN > 1.5) AND high-expression
    (top-tertile log2TPM) for the target — the amplification-DRIVEN overexpression-addiction hypothesis
    (ERBB2/MYC/KRAS-amp, the amp→overexpression→dependency chain the CN-only path under-weights)?
    Target-only; indication accepted for back-compat but not consumed.
    """
    ae_module = _import_method("depmap_amp_expr_dependency")
    return ae_module.read_amp_expr_dependency(target=target, indication=indication)


def _dispatch_mutation_drug_response(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: route mutation-drug-response card (Card E3.drug) to
    methods/depmap_mutation_drug_response/read.py.

    The PHARMACOLOGICAL sibling of mutation-stratified-dependency: are cell lines carrying an
    alteration in the target more SENSITIVE to a DRUG that targets it (PRISM Log2AUC), vs the
    CRISPR-KO dependency the mutation-stratified card measures? Selects on-target PRISM compounds
    (GeneSymbolOfTargets == target) and stratifies best-responder Log2AUC by mutation status.
    Target-only; indication accepted for back-compat but not consumed (cell-panel drug response is
    indication-independent, like the sibling stratified cards).
    """
    dr_module = _import_method("depmap_mutation_drug_response")
    return dr_module.read_mutation_drug_response(target=target, indication=indication)


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


def _dispatch_domain_modality_relevance(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: domain-modality-relevance card → the INTERPRETIVE domain→modality layer via
    methods/domain_modality_relevance/read.py (roadmap #3). Turns protein_class + domain
    architecture (+ a curated scaffolding vocab) into modality_implication_class — does the
    target's domain function favor a catalytic-site inhibitor or REMOVAL (degrader/glue), the
    RIPK1 scaffolding case. Target-intrinsic (indication ignored). Verdict-inert."""
    mod = _import_method("domain_modality_relevance")
    return mod.domain_modality_for_gene(target)


def _dispatch_degradation_feasibility(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: degradation-feasibility card → the degrader-lens E3 slice via
    methods/degradation_feasibility/read.py. Is the target a tractable degradation substrate
    (PROTAC / molecular glue)? Fuses natural E3-substrate evidence (UbiBrowser) + curated PROTAC
    precedent + a surfaceome LOCATION gate. The location gate is supplied by composing the
    surfaceome-family dispatcher (surface/secreted → cytoplasmic-E3-unreachable → unfavorable_location).
    Target-intrinsic (indication ignored). Feeds the degrader lens; verdict-inert for SM."""
    family = _dispatch_surfaceome_family_classification(target, indication) or {}
    surface_family_class = family.get("family_class")
    # 2026-08-09 bugfix: pass the surfaceome BOOLEAN so the location gate works (the old
    # family_class-string gate was dead — those strings are never emitted). is_surface_protein is
    # the robust, vocab-independent signal; surface_family_class stays as a fallback + for context.
    is_surface_protein = family.get("is_surface_protein")
    mod = _import_method("degradation_feasibility")
    return mod.degradation_feasibility_for_gene(
        target, surface_family_class=surface_family_class, is_surface_protein=is_surface_protein)


# _dispatch_ppi_interactome REMOVED (T11, 2026-08-11): the ppi-interactome card now declares
# module: ppi_interactome + entrypoint: read_target_summary in its card_spec, so the GENERIC
# dispatcher (read_live_summary → _generic_dispatch) invokes it directly. No bespoke passthrough
# function needed. This is the god-file-collapse pattern: pure passthroughs become card_spec data.


def _dispatch_reactome_pathway_membership(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: reactome-pathway-membership card → Reactome pathway/geneset membership
    via methods/reactome_pathway_context/read.py. Target-intrinsic (indication ignored); the
    reader resolves HGNC→UniProt-AC via the Reactome resolver sidecar. Distinct from the
    signaling-network-mechanism dispatcher (which uses reactome only as one enrichment input to
    the COMPOSED mechanism output) — this exposes pathway MEMBERSHIP as its own card.
    """
    mod = _import_method("reactome_pathway_context")
    return mod.read_target_summary(target=target, indication=indication)


# _dispatch_gene_ontology_annotation REMOVED (T11, 2026-08-11): the gene-ontology-annotation card
# now declares module: gene_ontology_annotation + entrypoint: read_target_summary, so the GENERIC
# dispatcher invokes it directly. See _generic_dispatch.


def _dispatch_signaling_network_mechanism_composed(target: str, indication: str) -> Optional[dict]:
    """Alias for the ADC/TCE composed card's derived_from resolution.
    (Unused as a card-registered dispatcher; kept for symmetry.)"""
    return _dispatch_signaling_network_mechanism(target, indication)


def _dispatch_surface_topology_and_ptm(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: surface-topology-and-ptm card → TMbed topology + UniProt PTM
    + AlphaFold pLDDT + motif regex via methods/topology_predictions_tmbed/read.py.

    ISOFORM OVERLAY (2026-08-07): the TMbed product carries topology only and hardcodes
    isoform_selective_warning=False (the card comment says "the composed card / skill applies the
    isoform vocab overlay" — but nothing did, so isoform_dependent_undefined was structurally
    unreachable on live data). Apply the curated isoform-selective vocabulary here so the topology
    RULE (isoform-selective-warning-modality-suppression) AND the composed fit_class both see it. Uses
    the shared vocab consumer (target-contracts/vocabularies/isoform_selective_targets.yaml).
    """
    mod = _import_method("topology_predictions_tmbed")
    out = dict(mod.read_target_summary(target=target, indication=indication) or {})
    try:
        from _skills_common.isoform_selective_targets import check_target
        warning = check_target(target.upper().strip())
        if warning is not None:
            out["isoform_selective_warning"] = True
            out["isoform_selective_dominant_isoform"] = warning.dominant_isoform
            out["vocabulary_version_isoform"] = warning.vocabulary_version
    except Exception:  # noqa: BLE001 — vocab unreadable → leave the product's default (no false warning)
        pass
    return out


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
    """Dispatcher: surface-abundance-density card. TWO tiers, distinct slots (INC-4, 2026-08-08):

    Tier-2 (grade-D estimate, the base summary) — methods/cptac_protein_deg/read.py::
      read_abundance_density_summary(): HPA-IHC ordinal × CPTAC log2FC order-of-magnitude copies/cell.
      Broad coverage, wide uncertainty. This is the existing card payload (surface_density_class,
      is_tce_viable, is_adc_high_payload_viable) — an ANNOTATION, never a veto (housekeeping-FP guard).

    Tier-1 (calibrated ABSOLUTE anchor) — methods/surface_antigen_density_ladder/read.py::
      read_absolute_density(): grade A/B bead-calibrated copies/cell from the governed curated corpus
      (native patient/cell-line partitions). Narrow coverage (~11 antigens today), HIGH precision, DOI-
      cited. Merged in under `absolute_*` keys so the card exposes the real absolute value + its floor
      standing WITHOUT overwriting the broad Tier-2 estimate. `unmeasured` (grade E) for un-anchored
      targets — never fabricated. This is what the tumor-selectivity density facet reads (verdict-inert).
    """
    # Tier-2 grade-D estimate. Isolated so a Tier-2 read failure (e.g. a transient CPTAC/HPA read or
    # sys.path issue) does NOT lose the independent Tier-1 absolute anchor below.
    try:
        mod = _import_method("cptac_protein_deg")
        summary = mod.read_abundance_density_summary(target=target, indication=indication) or {}
    except Exception as e:  # noqa: BLE001 — Tier-2 is the broad ESTIMATE; degrade it, keep Tier-1
        summary = {"surface_density_class": "unmeasured",
                   "_tier2_estimate_error": f"{type(e).__name__}: {e}"}

    # Tier-1 absolute anchor (namespaced; independent of Tier-2 — computed in its own try so a Tier-2
    # failure never suppresses the calibrated value). Does not disturb the Tier-2 grade-D fields.
    ladder = _import_method("surface_antigen_density_ladder")
    abs_ = ladder.read_absolute_density(target=target, indication=indication) or {}
    value = abs_.get("value_best")
    grade = abs_.get("density_evidence_level")
    # density_floor_verdict — ONLY from a MEASURED Tier-1 absolute value (grade A/B). Floors are the
    # framework's cited constants (Slaga 2018 soluble-TCE 1,000/cell; ADC high-payload 10,000/cell).
    # unmeasured (grade E / no value) → the facet abstains (absence != low density). NB: below_floor is
    # a MODALITY caveat (soluble-TCE geometry), NOT a target killer — CD19 is 110/cell yet a validated
    # CAR-T/TCE antigen (high-avidity binders work below the soluble-TCE floor), so this NEVER clamps
    # the selectivity verdict; it only informs the modality-viability flags + a caveat.
    if value is None or grade in (None, "E"):
        floor_verdict = "unmeasured"
    elif value >= 10000.0:
        floor_verdict = "above_adc_high_payload_floor"
    elif value >= 1000.0:
        floor_verdict = "above_tce_floor_below_adc"
    else:
        floor_verdict = "below_tce_floor"
    summary.update({
        "absolute_density_class": abs_.get("absolute_density_class"),
        "absolute_copies_per_cell": value,
        "absolute_density_grade": grade,
        "absolute_measurement_semantics": abs_.get("measurement_semantics_best"),
        "absolute_n_measurements": abs_.get("n_admissible_measurements"),
        "density_floor_verdict": floor_verdict,
    })
    return summary


def _dispatch_pmhc_presentation(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: pmhc-presentation card -> peptide-centric HLA presentation (benign immunopeptidome,
    HLA Ligand Atlas) via methods/pmhc_presentation/read.py. The peptide-centric TCE axis — reaches
    intracellular targets via the peptide-MHC complex. Presentation is a protein property; indication
    accepted for the dispatcher contract, not consumed. An absent target is a WEAK-negative
    (not_observed), never data_unavailable (MS asymmetry).
    """
    _import_method("pmhc_presentation")  # ensures the analysis-methods repo is on sys.path
    from methods.pmhc_presentation import read_pmhc_presentation
    return read_pmhc_presentation(target=target, indication=indication)


def _dispatch_modality_therapeutic_window(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: modality-therapeutic-window card → tumor / max-essential-normal TPM window
    (modality-tiered, strict/TCE default) via methods/tcga_gtex_tpm_quantiles/window.py. Reads the
    tcga-gtex-tpm-tissue-quantiles-v1 product; the CEACAM5-paradox signal (huge window yet strict-TCE
    liability). WIRED 2026-08-07 — the card+method+rules shipped in the window arc but this dispatcher
    was never added, so the 3 window rules never fired and window_class was null in every headline.
    """
    _import_method("tcga_gtex_tpm_quantiles")  # ensures the analysis-methods repo is on sys.path
    from methods.tcga_gtex_tpm_quantiles import window as _window
    return _window.read_modality_window(target=target, indication=indication)


def _dispatch_exon_window(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: modality-exon-window card (E5) → per-exon tumor-vs-normal window + within-gene
    exon heterogeneity via methods/exon_window/read.py. Reads tcga-gtex-exon-tpm-quantiles-v1. HONEST
    SCOPE: a hypothesis-generating flag (exon_heterogeneity_flag = worth junction-level follow-up), NOT
    an isoform-identity call — per-exon coverage can't resolve CLDN18.2 from CLDN18.1. WIRED 2026-08-07
    with the card+method+rules; without this dispatcher exon_window_class would be null in the headline.
    """
    _import_method("exon_window")  # ensures the analysis-methods repo is on sys.path
    from methods.exon_window import read as _exon
    return _exon.read_exon_window(target=target, indication=indication)


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
    # GPI-ANCHOR RESCUE (2026-08-09, modality-fit review M1). TMbed 1D topology STRUCTURALLY cannot
    # see a GPI anchor (no membrane-spanning segment) → a GPI-anchored antigen reads tm_count==0 and
    # would fall to `neither_viable` below, despite being displayed on the outer leaflet with a real
    # ECD. FOLR1 (Elahere — approved ADC), MSLN, CD59 are exactly this false-negative (live: tm=0,
    # ecd=234/587/104, is_surface=True). The curated UniProt LIPID GPI fact (uniprot-gpi-anchored-v1,
    # reviewed-human complete) supplies what TMbed cannot. A GPI antigen is surface-accessible for
    # biologics; it has NO cytoplasmic tail (no internalization machinery / low turnover) so it is
    # inherently TCE/antibody-favorable, and ADC-viable when the ECD is large + internalization is
    # clinically precedented (FOLR1). is_gpi_anchored=None (product unavailable) is NOT a rescue.
    _gpi = _import_method("uniprot_gpi_anchor").read_gpi_anchor(target, indication=indication) or {}
    is_gpi_anchored = bool(_gpi.get("is_gpi_anchored"))
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

    # E2b (2026-08-07): distinguish a genuine COVERAGE GAP (topology/family product unavailable) from a
    # MEASURED non-surface. When family/topology came back data_unavailable, the composed call is a gap
    # (data_unavailable), NOT a measured neither_viable killer — otherwise a target with no topology/family
    # product reads as a hard biologics no-go rather than "unknown" (measured-vs-data_unavailable doctrine).
    family_unavailable = family.get("family_class") == "data_unavailable"
    topology_unavailable = topology.get("topology_class") == "data_unavailable"
    # A GPI-anchored antigen is surface-accessible even at tm_count==0 (TMbed can't see the anchor).
    # It rescues the no_transmembrane false-negative ONLY when there is also a real bindable ECD.
    gpi_surface_accessible = is_gpi_anchored and is_surface and tm_count == 0 and ec_length >= 100
    # E2b hardening (2026-08-12, adc-tce-modality-fit audit): EITHER required input missing is a coverage
    # gap, not a measured no-go — was `and` (both). fit_class fundamentally needs BOTH the surfaceome-family
    # call (is_surface) and the topology product (tm_count/ec_length) to distinguish ADC vs TCE vs neither.
    # When topology is data_unavailable, tm_count/ec_length coalesce to 0 (lines above), which would trip
    # the `tm_count == 0` neither_viable branch below — a coverage gap masquerading as a measured
    # no-transmembrane, the exact measured-vs-data_unavailable conflation the endocytosis/ubiquitination
    # raw-reads guard against. The GPI rescue also depends on topology's ec_length (>=100), so it cannot
    # fire when topology is unavailable; the data_unavailable check correctly precedes it.
    if family_unavailable or topology_unavailable:
        fit_class = "data_unavailable"
    elif gpi_surface_accessible:
        # GPI branch: no cytoplasmic tail → endocytosis/turnover machinery absent. TCE + naked-antibody
        # favorable (stable surface display); ADC-viable when the ECD is large AND internalization is
        # clinically precedented (FOLR1/Elahere) — a GPI antigen is NOT auto-ADC (no default internalization).
        adc_favorable = (ec_length >= 200 and clinically_internalizing)
        tce_favorable = (ec_length >= 100)
        if adc_favorable and tce_favorable:
            fit_class = "both_viable"
        elif adc_favorable:
            fit_class = "ADC_preferred"
        else:
            fit_class = "TCE_preferred"
    elif not is_surface or tm_count == 0:
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
                         f"n_ubiq={n_ubiq if ubiq_measured else 'unmeasured'}"
                         + (", GPI-anchored (TMbed-invisible surface antigen rescued)" if gpi_surface_accessible else ""),
        # GPI-anchor rescue provenance (M1 fix): surfaced so a GPI-driven surface call is auditable
        # (the topology_class stays no_transmembrane — TMbed can't see the anchor — but fit_class is
        # computed on the ECD as a surface antigen). is_gpi_anchored is the curated UniProt LIPID fact.
        "is_gpi_anchored": is_gpi_anchored,
        "gpi_surface_rescued": gpi_surface_accessible,
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


def _dispatch_combo_crispr_screen(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: combo-crispr-screen card → methods/combo_drug_anchor/read.py
    ::combination_opportunities_for_gene. Drug-anchored CRISPR combination opportunities
    ("when target X is inhibited, which co-targets become more essential") from
    depmap-drug-anchor-combination-per-target-v1. Per-target (indication not consumed)."""
    mod = _import_method("combo_drug_anchor.read")
    return mod.combination_opportunities_for_gene(target)


def _dispatch_resistance_emergence_signature(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: resistance-emergence-signature card → methods/resistance_emergence/read.py
    ::resistance_mediators_for_gene. Drug-anchored CRISPR RESISTANCE mediators ("when target X is
    inhibited, which gene knockouts RESCUE the cell") from the sign-mirror product
    depmap-drug-anchor-resistance-per-target-v1 (+ verdict-inert Tahoe transcriptional-adaptation
    sub-signal). Per-target (indication not consumed)."""
    mod = _import_method("resistance_emergence.read")
    return mod.resistance_mediators_for_gene(target)


def _dispatch_tahoe_drug_perturbation(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: tahoe-drug-perturbation card → methods/tahoe_drug_perturbation/read.py
    ::read_tahoe_drug_perturbation. Single-cell drug-perturbation MoA facet ("which drugs move the
    target's expression, in which cancer lines") from tahoe-drug-perturbation-per-gene-v1. Per-target
    (indication not consumed — gene-keyed / pan-cancer). VERDICT-INERT display facet."""
    mod = _import_method("tahoe_drug_perturbation.read")
    return mod.read_tahoe_drug_perturbation(target, indication)


def _dispatch_combinatorial_dependency(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: combinatorial-dependency card → methods/paralog_genetic_interaction/read.py
    ::combinatorial_dependency_for_gene. Symmetric paralog dual-KO genetic-interaction
    (GI = dual - sum-of-singles) from depmap-paralog-genetic-interaction-per-pair-v1. Per-target
    (target_pair grain; indication not consumed — the GI is a cell-line panel property)."""
    mod = _import_method("paralog_genetic_interaction.read")
    return mod.combinatorial_dependency_for_gene(target)


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


def _dispatch_cd_antigen_backbone(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: cd-antigen-backbone card (E6-CD) → CD/immuno-oncology antigen-BACKBONE
    clinical-precedent prior via methods/cd_antigen_backbone/read.py. Reads the landed
    hgnc-gene-group-471 CD-molecule roster (CC0). A class-level tractability-precedent signal
    (is the target on the antigen class that delivered approved biologics?), supportive-only.
    Protein-intrinsic — indication accepted for the CARD_DISPATCHERS contract, not consumed.
    """
    mod = _import_method("cd_antigen_backbone")
    return mod.read_cd_antigen_backbone(target=target, indication=indication)


def _dispatch_immune_context(target: str, indication: str) -> Optional[dict]:
    """Dispatcher: immune-context card -> tumor T-cell infiltration (EFFECTOR arm) via
    methods/immune_context. Merges the per-indication class (read_immune_context - v1, target-
    independent) with the antigen-CONDITIONED facet (read_antigen_conditioned - v2, T-cells among
    ANTIGEN-HIGH patients; barcode<->UUID join guarded by a coverage floor). The primary
    immune_context_class is the per-indication call; the antigen_conditioned_* fields are an additive
    per-target facet (data_unavailable when the join is too thin or the target has no per-sample TPM).
    A TCE needs BOTH a surface antigen AND an effector pool - this is the effector half.
    """
    mod = _import_method("immune_context")
    out = dict(mod.read_immune_context(indication=indication))
    try:
        from methods.immune_context.antigen_conditioned import read_antigen_conditioned
        ac = read_antigen_conditioned(target, indication)
        for k in ("antigen_conditioned_call", "cd8_fraction_antigen_high", "cd8_fraction_antigen_low",
                  "cd8_high_minus_low", "antigen_high_immune_context_class", "join_fraction",
                  "n_patients_joined"):
            if k in ac:
                out[k] = ac[k]
    except Exception as e:  # noqa: BLE001 - v1 class stands even if the v2 join is unavailable
        out["antigen_conditioned_call"] = "data_unavailable"
        out["_antigen_conditioned_note"] = f"{type(e).__name__}: {e}"
    return out


CARD_DISPATCHERS = {
    "target-identity-summary": _dispatch_target_identity_summary,
    "tumor-rna-vs-adjacent": _dispatch_expression_tumor_vs_adjacent,
    "dependency-lineage-selectivity": _dispatch_dependency_lineage_selectivity,
    "mutation-hotspot-frequency": _dispatch_mutation_hotspot_frequency,
    "alteration-role": _dispatch_alteration_role,
    "genomic-instability-state": _dispatch_genomic_instability_state,
    "ddr-deficiency-context": _dispatch_ddr_deficiency_context,
    "mutational-signature-context": _dispatch_mutational_signature_context,
    "oncogenic-pathway-alteration": _dispatch_oncogenic_pathway_alteration,
    "stemness-context": _dispatch_stemness_context,
    "target-development-level": _dispatch_target_development_level,
    "variant-level-interpretation": _dispatch_variant_level_interpretation,
    "functional-gene-state": _dispatch_functional_gene_state,
    "genomic-event-model-match": _dispatch_genomic_event_model_match,
    "fusion-rearrangement-landscape": _dispatch_fusion_rearrangement_landscape,
    "pan-cancer-crispr-dependency-distribution": _dispatch_pan_cancer_dependency_distribution,
    "pan-cancer-rnai-dependency-distribution": _dispatch_pan_cancer_rnai_dependency_distribution,
    "crispr-rnai-dependency-concordance": _dispatch_crispr_rnai_dependency_concordance,
    "cross-consortium-dependency": _dispatch_cross_consortium_dependency,
    "cellline-rna-distribution": _dispatch_expression_distribution,
    "tumor-rna-distribution": _dispatch_tumor_expression_distribution,
    "tumor-rna-distribution-by-subtype": _dispatch_tumor_expression_distribution_subtype,
    "tumor-scrna-celltype-expression": _dispatch_sc_tumor_celltype_expression,   # sc_rna/tumor bucket (single-cell per-compartment presence)
    "sc-normal-celltype-expression": _dispatch_sc_normal_celltype_expression,    # sc_rna/normal SAFETY COMPARATOR bucket (#267 added to CARDS, dispatcher was missing)
    "known-drug-tractability": _dispatch_known_drug_tractability,                 # DGIdb pharmacology leg (#272 added to CARDS, dispatcher was missing)
    "measured-potency-tractability": _dispatch_measured_potency_tractability,     # ChEMBL/BindingDB MEASURED potency leg (T3.1)
    "mutation-stratified-surface": _dispatch_mutation_stratified_surface,         # mutant-subset surface window (#276 added to CARDS, dispatcher was missing)
    "pathway-stratified-surface": _dispatch_pathway_stratified_surface,           # tumor-state-high surface window (#280 added to CARDS, dispatcher was missing)
    "tumor-vs-normal-percentile-crossing": _dispatch_tumor_vs_normal_percentile_crossing,
    "normal-tissue-liability-gtex": _dispatch_normal_tissue_liability_gtex,
    "recommended-models": _dispatch_recommended_models,
    "cellline-rna-protein-concordance": _dispatch_rna_protein_concordance,
    "rna-protein-concordance-tumor": _dispatch_rna_protein_concordance_tumor,
    "sc-surface-rna-protein-concordance": _dispatch_sc_surface_concordance,
    "surface-colocalization-avidity": _dispatch_surface_colocalization_avidity,
    "expression-dependency-correlation": _dispatch_expression_dependency_correlation,
    "abundance-dependency": _dispatch_abundance_dependency,
    "expression-purity-confound": _dispatch_expression_purity_confound,
    "expression-clinical-association": _dispatch_expression_clinical_association,
    "precog-prognostic-association": _dispatch_precog_prognostic,   # PRECOG pan-cancer meta-Z corroboration of the single-cohort survival card
    "phospho-pathway-activity": _dispatch_phospho_pathway_activity,
    "pathway-activity-context": _dispatch_pathway_activity_context,
    "copy-number-distribution": _dispatch_cn_distribution,
    "mutation-type-counts": _dispatch_mutation_type_counts,
    "mutation-stratified-dependency": _dispatch_mutation_stratified_dependency,
    "copy-number-stratified-dependency": _dispatch_cn_stratified_dependency,
    "partner-conditional-dependency": _dispatch_partner_conditional_dependency,
    "fusion-stratified-dependency": _dispatch_fusion_stratified_dependency,
    "amp-expr-stratified-dependency": _dispatch_amp_expr_stratified_dependency,
    "mutation-drug-response": _dispatch_mutation_drug_response,
    "dependency-predictability": _dispatch_dependency_predictability,
    "prism-compound-activity": _dispatch_prism_compound_activity,
    "prism-crispr-concordance": _dispatch_prism_crispr_concordance,
    "tumor-vs-normal-selectivity": _dispatch_tumor_vs_normal_selectivity,
    # RT1 fix-rollup 2026-07-09: 11 Phase D/E/F/G card dispatchers
    "signaling-network-mechanism": _dispatch_signaling_network_mechanism,
    "tahoe-drug-perturbation": _dispatch_tahoe_drug_perturbation,
    "reactome-pathway-membership": _dispatch_reactome_pathway_membership,  # target-intrinsic pathway/geneset membership
    # gene-ontology-annotation + ppi-interactome REMOVED from CARD_DISPATCHERS (T11, 2026-08-11):
    # both now route through the GENERIC dispatcher via card_spec module/entrypoint declarations.
    "protein-domains-class": _dispatch_protein_domains_class,  # target-intrinsic domain architecture + protein class
    "domain-modality-relevance": _dispatch_domain_modality_relevance,  # interpretive domain→modality (roadmap #3)
    "degradation-feasibility": _dispatch_degradation_feasibility,  # degrader-lens E3 slice 3 (UbiBrowser + precedent + location gate)
    "co-mutation-and-mutual-exclusivity": _dispatch_co_mutation_and_mutual_exclusivity,
    "surface-topology-and-ptm": _dispatch_surface_topology_and_ptm,
    "surfaceome-family-classification": _dispatch_surfaceome_family_classification,
    "structure-features-static": _dispatch_structure_features_static,
    "protein-surface-evidence": _dispatch_protein_surface_evidence,
    "surface-abundance-density": _dispatch_surface_abundance_density,
    "modality-therapeutic-window": _dispatch_modality_therapeutic_window,
    "modality-exon-window": _dispatch_exon_window,
    "pmhc-presentation": _dispatch_pmhc_presentation,
    "adc-tce-modality-fit": _dispatch_adc_tce_modality_fit,
    "surfaceome-cohort-ranking": _dispatch_surfaceome_cohort_ranking,
    "tumor-protein-abundance-cptac": _dispatch_protein_presence_cptac,
    "tumor-elevation-breadth": _dispatch_tumor_elevation_breadth,
    "paralog-buffering": _dispatch_paralog_buffering,
    "combinatorial-dependency": _dispatch_combinatorial_dependency,
    "combo-crispr-screen": _dispatch_combo_crispr_screen,
    "resistance-emergence-signature": _dispatch_resistance_emergence_signature,
    "gnomad-lof-constraint": _dispatch_gnomad_lof_constraint,
    "target-safety-prioritisation": _dispatch_target_safety_prioritisation,   # P5 Slice 1 (OT safety context)
    "gene-burden-safety": _dispatch_gene_burden_safety,                        # P5 Slice 2 (OT rare-variant burden, verdict-moving)
    "clingen-dosage": _dispatch_clingen_dosage,                                # P5 Slice 3 (ClinGen dosage sensitivity, verdict-moving)
    "mouse-ko-phenotype": _dispatch_mouse_ko_phenotype,                        # P5 Slice 4 (mouse-KO normal-physiology, developmental-guardrailed)
    "clinvar-pathogenicity-safety": _dispatch_clinvar_pathogenicity,           # P5 follow-on (ClinVar germline-pathogenic, verdict-moving)
    "shed-ectodomain-liability": _dispatch_shed_ectodomain_liability,
    "cd-antigen-backbone": _dispatch_cd_antigen_backbone,
    "immune-context": _dispatch_immune_context,
    "cellline-protein-abundance": _dispatch_protein_abundance_celline,
    "normal-tissue-liability": _dispatch_normal_tissue_liability,
    "synthetic-lethal-partners": _dispatch_synthetic_lethal_partners,
    # NOTE: a pure-passthrough card needs NO entry here since T11 (#341) — read_live_summary falls
    # back to the generic dispatcher driven by the card_spec's `module`/`entrypoint`. Add a bespoke
    # _dispatch_* only for multi-method merges or non-standard readers. (Removed a stale Iter-1b
    # dispatcher-roadmap comment here: tumor-vs-normal-selectivity is now a live entry above, and
    # subgroup-stratified-expression's blocked-on-per-sample-reader status lives on its card.)
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
                       subgroup_context: Optional[dict] = None,
                       data_context: Optional[dict] = None) -> Optional[dict]:
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

    T4 (2026-08-11): data_context {data_mode, release_pin} is accepted (and forwarded to any
    dispatcher whose signature declares it) so a release-aware method can pick the right manifest
    version via catalog_query.resolve_release. Single-release dispatchers ignore it. Accepting the
    kwarg here is what lets _call_live_reader's signature-introspection pass it through cleanly.

    Returns None if no dispatcher exists yet (caller falls back to stub or marks failed).
    """
    ctx = subgroup_context or {}
    _dctx = data_context or {}  # T4: {data_mode, release_pin}; forwarded to release-aware dispatchers
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
        # The mutation-frequency panorama can ALSO serve line-of-therapy (LOT_*) strata from a
        # separate GENIE-BPC shard even when no molecular/TCGA shard exists for the indication
        # (e.g. NSCLC ships only the GENIE-BPC LOT shard). Only bail when there is NO shard of
        # EITHER kind — otherwise call the dispatcher, which partitions strata by axis and emits
        # its own per-axis data-notes for whichever arm lacks a shard.
        _has_lot_shard = (card_id == "subgroup-stratified-mutation-frequency"
                          and _MUTATION_LOT_ASSIGNMENTS_MANIFEST.get(indication) is not None)
        if manifest_id is None and not _has_lot_shard:
            return {"_data_note": f"no subgroup-assignments shard for indication={indication!r} "
                                  f"(iter-1b ships COADREAD only)"}
        try:
            return dispatcher(target=target, indication=indication,
                              subgroups=subgroups, subgroup_assignments_manifest=manifest_id)
        except Exception as e:
            return {"_live_read_error": str(e)}

    dispatcher = CARD_DISPATCHERS.get(card_id)
    if dispatcher is None:
        # T11 (2026-08-11 engineering review): no BESPOKE dispatcher registered — try the GENERIC
        # data-driven path. If the card_spec's method declares a `module` + `entrypoint`, invoke it
        # directly, so a new pure-passthrough card needs NO hand-written _dispatch_* function. Returns
        # None only when the card has no generic wiring either (genuinely unwired → caller stubs/fails).
        return _generic_dispatch(card_id, target, indication)
    try:
        # T4: forward data_context ONLY to dispatchers whose signature declares it (release-aware
        # readers); single-release dispatchers keep the (target, indication) signature untouched.
        kwargs = {"target": target, "indication": indication}
        import inspect
        try:
            params = inspect.signature(dispatcher).parameters
            if _dctx and ("data_context" in params
                          or any(p.kind == p.VAR_KEYWORD for p in params.values())):
                kwargs["data_context"] = _dctx
        except (ValueError, TypeError):
            pass
        return dispatcher(**kwargs)
    except Exception as e:
        return {"_live_read_error": str(e)}


def _generic_dispatch(card_id: str, target: str, indication: str) -> Optional[dict]:
    """Data-driven dispatch (T11): resolve (module, entrypoint) from the card_spec's first method
    and call it as fn(target=, indication=). This collapses the ~30 pure-passthrough dispatchers
    (mod = _import_method(X); return mod.read_Y(target=, indication=)) into card_spec data, so a new
    card that follows that pattern needs no bespoke _dispatch_* function.

    Only used as a FALLBACK when no bespoke CARD_DISPATCHERS entry exists — every hand-written
    dispatcher (multi-method merges, positional-arg readers, .cli quirks) is unaffected. Returns
    None when the card has no method with an `entrypoint` declared (genuinely unwired)."""
    import yaml
    card_path = _TARGET_CONTRACTS_ROOT / "cards" / f"{card_id}.card.yaml"
    if not card_path.exists():
        return None
    try:
        spec = yaml.safe_load(card_path.read_text()) or {}
    except Exception:  # noqa: BLE001 — malformed card_spec → treat as unwired
        return None
    methods = spec.get("methods") or []
    method = next((m for m in methods if isinstance(m, dict) and m.get("entrypoint")), None)
    if method is None:
        return None   # no generic wiring for this card → genuinely unwired
    # module defaults to the `call` slug with hyphens→underscores when not explicitly declared.
    module_path = method.get("module") or (method.get("call", "").replace("-", "_"))
    entrypoint = method["entrypoint"]
    if not module_path:
        return None
    try:
        mod = _import_method(module_path)
        fn = getattr(mod, entrypoint)
        return fn(target=target, indication=indication)
    except Exception as e:  # noqa: BLE001 — surface as the structured error sentinel, like bespoke path
        return {"_live_read_error": str(e)}
