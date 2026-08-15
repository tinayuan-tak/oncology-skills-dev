"""Regression: gastric (GC/STAD) must resolve to a DepMap lineage that EXISTS in Model.csv.

DepMap 26Q1 Model.csv has NO "Stomach" lineage — the real value is "Esophagus/Stomach". Six maps
across the framework had forked "GC"/"STAD" -> "Stomach", so gastric within-lineage scoping silently
matched zero models. The two VERDICT-relevant readers now import the single-source canonical map from
depmap_chronos.read; the display maps are corrected in place. An optional live leg confirms the value
is a real Model.csv lineage."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.depmap_chronos.read import INDICATION_TO_DEPMAP_LINEAGE  # noqa: E402


def test_canonical_map_gastric_is_esophagus_stomach():
    assert INDICATION_TO_DEPMAP_LINEAGE["GC"] == "Esophagus/Stomach"
    assert INDICATION_TO_DEPMAP_LINEAGE["STAD"] == "Esophagus/Stomach"
    # the nonexistent lineage must appear nowhere in the canonical map
    assert "Stomach" not in set(INDICATION_TO_DEPMAP_LINEAGE.values())


def test_verdict_readers_use_single_source_map():
    # both verdict-relevant readers import (not fork) the canonical map — literally the same object
    from methods.genomic_event_model_match import read as gemm
    from methods.patient_model_expression_correspondence import read as pmec
    assert gemm.INDICATION_TO_DEPMAP_LINEAGE is INDICATION_TO_DEPMAP_LINEAGE
    assert pmec.INDICATION_TO_DEPMAP_LINEAGE is INDICATION_TO_DEPMAP_LINEAGE


def test_display_maps_gastric_corrected():
    from methods.depmap_chronos.cli import INDICATION_LINEAGE as chronos_disp
    from methods.depmap_expression_distribution.cli import INDICATION_LINEAGE as expr_dist_disp
    from methods.depmap_protein_abundance.cli import INDICATION_LINEAGE as prot_disp
    assert chronos_disp["GC"] == "Esophagus/Stomach"
    assert expr_dist_disp["GC"] == "Esophagus/Stomach"
    assert expr_dist_disp["STAD"] == "Esophagus/Stomach"
    assert prot_disp["STAD"] == "Esophagus/Stomach"
    for m in (chronos_disp, expr_dist_disp, prot_disp):
        assert "Stomach" not in set(m.values())


def test_gastric_lineage_present_in_model_csv_live():
    # Optional live leg: the mapped lineage must be a real Model.csv OncotreeLineage.
    from methods.depmap_protein_abundance import cli as pa
    try:
        lin_by_model = pa.load_model_lineage()
    except Exception:  # noqa: BLE001 — no S3 / creds → skip (this leg is opportunistic)
        pytest.skip("Model.csv unreachable (no S3)")
    lineages = set(lin_by_model.values())
    if not lineages:
        pytest.skip("Model.csv unreachable (no S3)")
    assert INDICATION_TO_DEPMAP_LINEAGE["GC"] in lineages
    assert "Stomach" not in lineages   # confirms the old value was genuinely bogus
