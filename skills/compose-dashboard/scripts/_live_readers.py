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

import sys
from pathlib import Path
from typing import Optional

METHODS_REPO = Path("/home/sagemaker-user/rnd-computational-biology-oncology-analysis-methods")
DATA_CATALOG_LIBS = Path("/home/sagemaker-user/rnd-computational-biology-oncology-data-catalog/libs")


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
    """Dispatcher: route expression-tumor-vs-adjacent card to methods/dge_deseq2/read.py.

    For iter-1b, indication=COADREAD maps to manifest coadread-dge-df06320.
    Iter-2 expands the mapping to other indications as DGE products land.
    """
    indication_to_dge_manifest = {
        "COADREAD": "coadread-dge-df06320",
        # Iter-2: PDAC, NSCLC, SCLC, GC DGE products land as derived manifests
    }
    manifest_id = indication_to_dge_manifest.get(indication)
    if manifest_id is None:
        return {
            "_data_note": f"no DGE derived manifest for indication={indication!r} (iter-1b ships COADREAD only)",
        }
    dge_module = _import_method("dge_deseq2")
    summary = dge_module.read_dge_gene_row(target=target, manifest_id=manifest_id)
    if summary is None:
        return {
            "log2_fc": None, "q_value": None,
            "tumor_mean_tpm": None, "adjacent_mean_tpm": None,
            "n_tumor": None, "n_adjacent": None,
            "_data_note": f"target {target!r} not present in {manifest_id} DGE table",
        }
    return summary


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
    """Dispatcher: route expression-distribution card (E3.a) to
    methods/depmap_expression_distribution/read.py.

    Pan-cancer cell-line expression panel; indication accepted for dispatcher
    consistency but not consumed (this card is target-only).
    """
    expr_module = _import_method("depmap_expression_distribution")
    return expr_module.read_expression_distribution(target=target, indication=indication)


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

    E6 is a THIN LOOKUP card off an OFF-SUBSTRATE derived parquet
    s3://onc-compbio/data-catalog/derived/depmap-prism-activity-v1/prism_activity_per_gene.parquet
    (release_pin `prism-activity-v1`, distinct from the 26q1 CRISPR pin).
    Sister precompute (methods/depmap_prism_precompute/) merges PRISM OncologyReference
    25Q4 + Repurposing 24Q2 into a per-gene aggregate at batch time.

    Target-only (pan-cancer). indication accepted for the CARD_DISPATCHERS
    contract but NOT consumed by v1 — lineage-specific PRISM activity is v2 scope.
    """
    prism_module = _import_method("depmap_prism_activity")
    return prism_module.read_prism_activity(target=target, indication=indication)


CARD_DISPATCHERS = {
    "target-identity-summary": _dispatch_target_identity_summary,
    "expression-tumor-vs-adjacent": _dispatch_expression_tumor_vs_adjacent,
    "dependency-lineage-selectivity": _dispatch_dependency_lineage_selectivity,
    "mutation-hotspot-frequency": _dispatch_mutation_hotspot_frequency,
    "pan-cancer-crispr-dependency-distribution": _dispatch_pan_cancer_dependency_distribution,
    "pan-cancer-rnai-dependency-distribution": _dispatch_pan_cancer_rnai_dependency_distribution,
    "crispr-rnai-dependency-concordance": _dispatch_crispr_rnai_dependency_concordance,
    "expression-distribution": _dispatch_expression_distribution,
    "expression-dependency-correlation": _dispatch_expression_dependency_correlation,
    "copy-number-distribution": _dispatch_cn_distribution,
    "mutation-type-counts": _dispatch_mutation_type_counts,
    "mutation-stratified-dependency": _dispatch_mutation_stratified_dependency,
    "dependency-predictability": _dispatch_dependency_predictability,
    "prism-compound-activity": _dispatch_prism_compound_activity,
    # Iter-1b execution session adds (each as a dispatcher to a methods/<method>/read.py):
    #   "tumor-vs-normal-selectivity": _dispatch_tumor_vs_normal_selectivity,
    #       → methods/dge_deseq2/read.py + (future) methods/gtex_normal_tissue/read.py
    #   "antigen-prevalence": _dispatch_antigen_prevalence,
    #       → methods/dge_deseq2/read.py (per-sample expression matrix)
    #   "rwd-stratified-expression": _dispatch_rwd_stratified_expression,
    #       → methods/tempus_rwd_aggregator/read.py
    #   "subgroup-stratified-expression": _dispatch_subgroup_stratified_expression,
    #       → methods/dge_deseq2/read.py + methods/subgroup_assigner_*/read.py
}


def read_live_summary(card_id: str, target: str, indication: str) -> Optional[dict]:
    """Dispatch a live-read for the named card to its corresponding method module.
    Returns None if no dispatcher exists yet (caller falls back to stub or marks failed)."""
    dispatcher = CARD_DISPATCHERS.get(card_id)
    if dispatcher is None:
        return None
    try:
        return dispatcher(target=target, indication=indication)
    except Exception as e:
        return {"_live_read_error": str(e)}
