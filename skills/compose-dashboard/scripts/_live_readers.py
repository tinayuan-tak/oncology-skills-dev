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
    """Dispatcher: route pan-cancer-dependency-distribution card to
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
CARD_DISPATCHERS = {
    "target-identity-summary": _dispatch_target_identity_summary,
    "expression-tumor-vs-adjacent": _dispatch_expression_tumor_vs_adjacent,
    "dependency-lineage-selectivity": _dispatch_dependency_lineage_selectivity,
    "mutation-hotspot-frequency": _dispatch_mutation_hotspot_frequency,
    "pan-cancer-dependency-distribution": _dispatch_pan_cancer_dependency_distribution,
    "expression-dependency-correlation": _dispatch_expression_dependency_correlation,
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
