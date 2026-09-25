"""dge_deseq2.config — single source of truth for indication rosters (S1, #693).

Loads ``config/indications.yaml`` and PROJECTS it into the structures each consumer
previously hard-coded independently:

  * :func:`published_indications`     -> derive_pancan_stack._PUBLISHED_INDICATIONS
  * :func:`composite_indications`     -> derive_pancan_stack._COMPOSITE_INDICATIONS
  * :func:`indication_to_tcga_studies`-> read.INDICATION_TO_TCGA_STUDIES
  * :func:`indication_to_gtex_tissue` -> read.INDICATION_TO_GTEX_TISSUE
  * :func:`pan_tissue_indications`    -> emit_pan_tissue.PAN_TISSUE_INDICATIONS

Pure no-op consolidation: every projection is verdict-identical to the pre-S1 literals,
pinned byte-for-byte by ``tests/test_indication_config_rosters.py``. These are DIFFERENT
sets (a 27-product universe, a 19-row render subset, a 21-key substrate lookup), so each
projection filters the universe on its own membership flag rather than sharing one list.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

_CONFIG_PATH = Path(__file__).with_name("indications.yaml")


@lru_cache(maxsize=1)
def _load() -> dict:
    with open(_CONFIG_PATH, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    inds = data["indications"]
    render = data["pan_tissue_render"]
    # Fail loud on drift rather than silently mis-projecting: the render roster must be a
    # subset of the published universe (an unknown or unpublished render row is a bug).
    missing = [c for c in render if c not in inds]
    assert not missing, f"pan_tissue_render references unknown indications: {missing}"
    unpublished = [c for c in render if not inds[c].get("published")]
    assert not unpublished, f"pan_tissue_render includes non-published indications: {unpublished}"
    return data


def _indications() -> dict:
    return _load()["indications"]


def published_indications() -> list:
    """The 27 published indications (derive_pancan_stack roster), sorted.

    This is the ``{indication}-dge-tumor-vs-normal-sensitivity-v1`` product universe. Was
    ``cell_b_semantics_map`` (a name -> cell-B vintage dict) until analysis-methods#727 removed
    the ComBat cell B; the vintage payload is gone, only the roster of published names remains.
    """
    return sorted(name for name, attrs in _indications().items() if attrs.get("published"))


def composite_indications() -> dict:
    """Composite OncoTree parent -> set of finer sibling cohorts it is the union of."""
    return {
        name: set(attrs["composite_children"])
        for name, attrs in _indications().items()
        if attrs.get("composite_children")
    }


def indication_to_tcga_studies() -> dict:
    """Indication -> recount3 TCGA study codes (read-map entries only)."""
    return {name: list(attrs["tcga_studies"]) for name, attrs in _indications().items() if attrs.get("in_read_map")}


def indication_to_gtex_tissue() -> dict:
    """Indication -> matched recount3 GTEx tissue (read-map entries with a clean match)."""
    return {
        name: attrs["gtex_tissue"]
        for name, attrs in _indications().items()
        if attrs.get("in_read_map") and attrs.get("gtex_tissue") is not None
    }


def pan_tissue_indications() -> list:
    """Ordered pan-indication figure render roster (emit_pan_tissue)."""
    return list(_load()["pan_tissue_render"])


def run_ledger_intent() -> dict:
    """Declared run-ledger product roster per (family, substrate) — S5, #698.

    The recount3 sensitivity roster is the ``published: true`` universe PLUS any
    ``sensitivity_recount3_extra`` (06-driver products that ship without a
    standalone published flag, e.g. the NSCLC composite). Everything else is a
    literal per-family / singleton roster. ``build_run_ledger`` turns this into
    the expected ``{catalog_id -> attrs}`` map and reconciles it bidirectionally
    against the catalog manifests + S3 prefixes; it is NOT the iteration driver.
    """
    intent = _load()["run_ledger_intent"]
    published = published_indications()  # the 27 published indications (sorted)
    return {
        "sensitivity": {
            "recount3": published + list(intent.get("sensitivity_recount3_extra", [])),
            "xena_toil": list(intent.get("sensitivity_xena_toil", [])),
        },
        "adj_vs_gtex": {
            "recount3": list(intent.get("adj_vs_gtex_recount3", [])),
            "xena_toil": list(intent.get("adj_vs_gtex_xena_toil", [])),
        },
        "subgroup": {
            "recount3": list(intent.get("subgroup_recount3", [])),
        },
        "singletons": [dict(s) for s in intent.get("singletons", [])],
    }
