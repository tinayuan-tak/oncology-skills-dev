"""dge_deseq2.config — single source of truth for indication rosters (S1, #693).

Loads ``config/indications.yaml`` and PROJECTS it into the structures each consumer
previously hard-coded independently:

  * :func:`cell_b_semantics_map`      -> derive_pancan_stack._INDICATION_CELL_B_SEMANTICS
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


def default_cell_b_semantics() -> str:
    """Default cell-B vintage for an indication absent from the published map.

    The pre-S1 code used the module literal ``_COMBAT_TSS`` as the ``.get`` fallback in
    ``build_stack``; that literal now lives here as ``defaults.cell_b_semantics``.
    """
    return _load()["defaults"]["cell_b_semantics"]


def cell_b_semantics_map() -> dict:
    """The 27 published indications -> cell-B vintage (derive_pancan_stack roster)."""
    default = default_cell_b_semantics()
    return {
        name: attrs.get("cell_b_semantics", default) for name, attrs in _indications().items() if attrs.get("published")
    }


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
