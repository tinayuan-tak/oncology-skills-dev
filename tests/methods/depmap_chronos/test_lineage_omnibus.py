"""Axis-3 (dependency): across-lineage Kruskal-Wallis + epsilon-squared omnibus.

Locks the omnibus that compute_lineage_summary now emits ALONGSIDE enrichment_class.
Uses synthetic chronos_by_model + model_metadata (no S3). Pins the decision-relevant
invariant: the effect-size CLASS tracks ε² (variance explained), NOT the p-value —
a dependency that is UNIFORM across lineages reads negligible even if the omnibus p is
small, while a dependency cleanly SEPARATED by lineage reads large. Also pins that the
new fields are ADDITIVE (the descriptive stats + enrichment_class are unchanged).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
CLI = REPO / "methods" / "depmap_chronos" / "cli.py"


def _load():
    spec = importlib.util.spec_from_file_location("chr_omni_cli", CLI)
    m = importlib.util.module_from_spec(spec)
    sys.modules["chr_omni_cli"] = m
    spec.loader.exec_module(m)
    return m


cli = _load()


def _make_panel(lineage_to_scores: dict):
    """Build (chronos_by_model, model_metadata) from {lineage: [chronos, ...]}."""
    chronos_by_model, model_metadata = {}, {}
    i = 0
    for lineage, scores in lineage_to_scores.items():
        for s in scores:
            mid = f"ACH-{i:05d}"
            chronos_by_model[mid] = float(s)
            model_metadata[mid] = {"ModelID": mid, "OncotreeLineage": lineage}
            i += 1
    return chronos_by_model, model_metadata


def test_uniform_across_lineages_is_negligible_effect():
    """A dependency equally deep in every lineage → lineage explains ~no variance →
    negligible, regardless of significance (the 'class tracks effect not p' invariant)."""
    # three lineages, all centered near the same value (a pan-essential-like uniform depth)
    import random

    rng = random.Random(0)
    panel = {ln: [-1.5 + rng.uniform(-0.15, 0.15) for _ in range(30)] for ln in ("Bowel", "Lung", "Skin")}
    chr_by_model, meta = _make_panel(panel)
    s = cli.compute_lineage_summary(chr_by_model, meta, min_n_lineage=5)
    assert s["lineage_omnibus_effect_size_class"] == "negligible"
    assert s["lineage_variance_explained"] is not None
    assert (
        s["lineage_variance_explained"] < cli.__dict__.get("EPSILON_SQUARED_MODERATE", 0.06)
        or s["lineage_variance_explained"] < 0.06
    )


def test_cleanly_separated_lineages_is_large_effect():
    """A dependency confined to one lineage (deep) vs others (near-zero) → lineage explains
    most of the variance → large effect + which_lineages_separate names the extremes."""
    panel = {
        "Bowel": [-2.4, -2.5, -2.3, -2.6, -2.4, -2.5, -2.3, -2.5],  # strongly dependent
        "Lung": [-0.05, 0.0, 0.02, -0.03, 0.01, 0.0, -0.02, 0.03],  # non-dependent
        "Skin": [0.0, 0.05, -0.02, 0.01, 0.0, 0.02, -0.01, 0.0],  # non-dependent
    }
    chr_by_model, meta = _make_panel(panel)
    s = cli.compute_lineage_summary(chr_by_model, meta, min_n_lineage=5)
    assert s["lineage_omnibus_effect_size_class"] == "large"
    assert s["lineage_variance_explained"] >= 0.14
    wl = s["which_lineages_separate"]
    assert wl["lowest"] == "Bowel"  # most negative median = most dependent
    assert wl["highest"] in ("Lung", "Skin")


def test_omnibus_is_additive_enrichment_class_unchanged():
    """The omnibus fields are ADDITIVE — the pre-existing descriptive/enrichment fields
    must still be present and unchanged in shape."""
    panel = {"Bowel": [-2.4] * 8, "Lung": [0.0] * 8, "Skin": [0.0] * 8}
    chr_by_model, meta = _make_panel(panel)
    s = cli.compute_lineage_summary(chr_by_model, meta, min_n_lineage=5)
    # pre-existing fields intact
    for k in (
        "enrichment_class",
        "per_lineage_stats",
        "n_lineages_evaluated",
        "median_chronos_panel",
        "enriched_lineages",
    ):
        assert k in s
    # new omnibus fields present
    for k in (
        "lineage_omnibus_effect_size_class",
        "lineage_variance_explained",
        "lineage_omnibus_p",
        "lineage_omnibus_kruskal_h",
        "which_lineages_separate",
        "n_lineages_omnibus_tested",
    ):
        assert k in s


def test_too_few_lineages_degrades_data_unavailable():
    """Fewer than 2 evaluable lineages → omnibus data_unavailable, never a raise."""
    panel = {"Bowel": [-1.0] * 8}  # single lineage
    chr_by_model, meta = _make_panel(panel)
    s = cli.compute_lineage_summary(chr_by_model, meta, min_n_lineage=5)
    assert s["lineage_omnibus_effect_size_class"] == "data_unavailable"
    assert s["lineage_variance_explained"] is None
