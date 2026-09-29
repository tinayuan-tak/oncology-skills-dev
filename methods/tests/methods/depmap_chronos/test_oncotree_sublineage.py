"""Phase 3b: the ADDITIVE per-OncotreeCode sublineage table on compute_lineage_summary.

Disambiguates SHARED coarse lineages (Esophagus/Stomach → STAD/ESCA/ESCC; Lung → LUAD/SCLC/…) so a
consumer-side indication reduction can separate STAD from ESCA (both map to the same coarse lineage).
Synthetic panel (no S3). Pins: (a) per-code splitting, (b) the min_n floor, (c) ADDITIVITY — the
verdict-driving outputs (per_lineage_stats / enriched_lineages / enrichment_class) are unchanged whether
or not OncotreeCode is present in the metadata."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
CLI = REPO / "methods" / "depmap_chronos" / "cli.py"


def _load():
    spec = importlib.util.spec_from_file_location("chr_sub_cli", CLI)
    m = importlib.util.module_from_spec(spec)
    sys.modules["chr_sub_cli"] = m
    spec.loader.exec_module(m)
    return m


cli = _load()


def _panel(code_rows: dict):
    """{ (lineage, code): [scores] } → (chronos_by_model, model_metadata w/ OncotreeCode)."""
    chronos, meta, i = {}, {}, 0
    for (lineage, code), scores in code_rows.items():
        for s in scores:
            mid = f"ACH-{i:05d}"
            chronos[mid] = float(s)
            meta[mid] = {"ModelID": mid, "OncotreeLineage": lineage, "OncotreeCode": code}
            i += 1
    return chronos, meta


def test_shared_lineage_split_by_oncotree_code():
    # Esophagus/Stomach coarse lineage merges STAD (dependent) + ESCA (not) — the confound Phase 3
    # tags with a caveat. Per-code stats separate them.
    chronos, meta = _panel(
        {
            ("Esophagus/Stomach", "STAD"): [-1.2] * 8,
            ("Esophagus/Stomach", "ESCA"): [-0.1] * 8,
        }
    )
    out = cli.compute_lineage_summary(chronos, meta, min_n_lineage=5)
    codes = {r["oncotree_code"]: r for r in out["per_oncotree_code_stats"]}
    assert set(codes) == {"STAD", "ESCA"}
    assert codes["STAD"]["median_chronos"] < -1.0 and codes["ESCA"]["median_chronos"] > -0.5
    # parent coarse lineage recorded on each code row
    assert codes["STAD"]["oncotree_lineage"] == "Esophagus/Stomach"
    # the COARSE per_lineage_stats still has the single merged row (additive — not replaced)
    assert any(r["lineage"] == "Esophagus/Stomach" for r in out["per_lineage_stats"])
    assert out["n_oncotree_codes_evaluated"] == 2


def test_below_floor_codes_dropped():
    chronos, meta = _panel(
        {
            ("Lung", "LUAD"): [-0.8] * 10,
            ("Lung", "SCLC"): [-0.9] * 3,  # below the min_n_lineage=5 floor → dropped
        }
    )
    out = cli.compute_lineage_summary(chronos, meta, min_n_lineage=5)
    codes = {r["oncotree_code"] for r in out["per_oncotree_code_stats"]}
    assert codes == {"LUAD"}


def test_additive_when_no_oncotree_code_in_metadata():
    # metadata without OncotreeCode (older callers) → empty sublineage table, verdict outputs unchanged
    chronos, meta = {}, {}
    for i, s in enumerate([-1.0] * 6 + [-0.1] * 6):
        mid = f"ACH-{i:05d}"
        chronos[mid] = s
        meta[mid] = {"ModelID": mid, "OncotreeLineage": "Bowel" if i < 6 else "Skin"}  # no OncotreeCode
    out = cli.compute_lineage_summary(chronos, meta, min_n_lineage=5)
    assert out["per_oncotree_code_stats"] == [] and out["n_oncotree_codes_evaluated"] == 0
    # verdict-driving outputs still present + correct
    assert out["n_lineages_evaluated"] == 2 and "enrichment_class" in out
