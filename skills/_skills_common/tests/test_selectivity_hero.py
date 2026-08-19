"""Tests for the selectivity evidence-strip hero (skills/_skills_common/selectivity_hero.py).

Pin the HONESTY DISCIPLINE (mirrors presence_matrix / ordinal_view): each axis carries a
support-status derived ONLY from decision['headline']; the normal-tissue WINDOW axis DISPLAYS the
veto outcome (closed when selectivity_class == selective_but_broadly_normal); unmeasured axes are
OFF-SCALE ('na'), NEVER scored 'opposes' (absence of an axis is not counter-evidence); and it is a
one-way VIEW (never a verdict input). Pure over headline — no S3, no method reads.
"""
from __future__ import annotations

import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]        # skills/
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common.selectivity_hero import (  # noqa: E402
    build_selectivity_axes, render_selectivity_hero_svg, emit_selectivity_hero,
)


def _clean_headline():
    """A CEACAM5-shaped clean-selective headline: axis-A field-effect, window OPEN, malignant-intrinsic."""
    return {
        "selectivity_class": "field_effect_tumor_selective",
        "axis_a_selectivity_class": "field_effect_tumor_selective",
        "driving_rule_id": "tvn-field-effect-selective-supportive",
        "cells_supporting": 1.0, "cells_ran": 3.0, "discordant": True,
        "dominant_direction": "up", "max_abs_log2fc": 2.94,
        "percentile_crossing_class": "strongly_tumor_enriched",
        "fraction_tumor_above_normal_p95": 0.76,
        "selectivity_allgene_percentile": 26.7, "selectivity_allgene_percentile_class": "mid",
        "sc_tumor_expression_class": "malignant_broadly_detected",
        "sc_malignant_detection_fraction": 0.76, "sc_caf_vs_malignant_class": "caf_low",
        "spatial_rna_class": "tumour_enriched_rna",
        "spatial_normal_epithelium_adjacency_fraction": 0.0006,
        "absolute_surface_density_class": "high", "absolute_copies_per_cell": 76000.0,
    }


def _vetoed_headline():
    """A TACSTD2/TROP2-shaped headline: strong axis-A but the normal-breadth veto CLOSED the window."""
    h = _clean_headline()
    h.update({
        "selectivity_class": "selective_but_broadly_normal",
        "axis_a_selectivity_class": "strong_tumor_selective",
        "driving_rule_id": "tvn-no-therapeutic-window-veto",
        "cells_supporting": 3.0, "discordant": False, "max_abs_log2fc": 5.0,
        "selectivity_allgene_percentile_class": "top_decile",
    })
    return h


def _liability_headline():
    """A FOLR1/DLL3/ERBB2-shaped headline: strong axis-A with a REAL window, but a NON-origin
    critical-organ liability → the sc-normal SPLIT class selective_with_normal_liability."""
    h = _clean_headline()
    h.update({
        "selectivity_class": "selective_with_normal_liability",
        "axis_a_selectivity_class": "strong_tumor_selective",
        "driving_rule_id": "tvn-sc-normal-critical-organ-veto",
        "sc_normal_safety_essential_class": "critical_organ_liability",
        "sc_normal_max_detection_cell_type": "kidney loop of Henle epithelial cell",
        "cells_supporting": 1.0, "discordant": False, "max_abs_log2fc": 9.9,
    })
    return h


def test_normal_liability_preserves_selectivity_window_open_amber():
    """The split: a critical-organ liability is NOT the housekeeping window-closed KILL — the window
    axis stays OPEN (amber, named organ), the banner reads amber, and vetoed is False."""
    v = build_selectivity_axes(_liability_headline())
    assert v["verdict_status"] == "warn"        # amber, not red
    assert v["vetoed"] is False and v["liability"] is True
    axes = {a["key"]: a for a in v["axes"]}
    assert axes["window"]["status"] == "warn"
    assert "liability" in axes["window"]["value"]
    assert "loop of Henle" in axes["window"]["note"]


def test_eight_axes_and_verdict_banner():
    v = build_selectivity_axes(_clean_headline())
    assert len(v["axes"]) == 8
    assert v["verdict_status"] == "good" and v["vetoed"] is False
    keys = {a["key"] for a in v["axes"]}
    assert {"comparators", "fold_change", "crossing", "rank", "window",
            "malignant_intrinsic", "spatial", "density"} <= keys


def test_clean_window_axis_is_open():
    axes = {a["key"]: a for a in build_selectivity_axes(_clean_headline())["axes"]}
    assert axes["window"]["status"] == "good"           # window OPEN
    assert axes["malignant_intrinsic"]["status"] == "good"  # caf_low + malignant broadly detected


def test_veto_closes_the_window_axis_and_banner():
    v = build_selectivity_axes(_vetoed_headline())
    assert v["vetoed"] is True and v["verdict_status"] == "bad"
    axes = {a["key"]: a for a in v["axes"]}
    assert axes["window"]["status"] == "bad"            # window CLOSED
    assert "CLOSED" in axes["window"]["value"]
    # the banner surfaces the axis-A → veto transition
    assert v["axis_a_selectivity_class"] == "strong_tumor_selective"


def test_unmeasured_axes_are_offscale_not_opposing():
    """The CD19/abstain discipline: a missing axis is 'na' (off-scale), NEVER 'bad' — absence of an
    axis (no spatial/sc coverage) is not evidence AGAINST selectivity."""
    h = {"selectivity_class": "modest_tumor_selective",
         "axis_a_selectivity_class": "modest_tumor_selective", "dominant_direction": "up",
         "max_abs_log2fc": 1.5}   # sc/spatial/density/crossing/rank all absent
    axes = {a["key"]: a for a in build_selectivity_axes(h)["axes"]}
    for k in ("malignant_intrinsic", "spatial", "density", "crossing", "rank"):
        assert axes[k]["status"] == "na", f"{k} should be off-scale (na), got {axes[k]['status']}"


def test_svg_is_wellformed_and_deterministic():
    h = _clean_headline()
    svg1 = render_selectivity_hero_svg(h, "CEACAM5", "COADREAD")
    svg2 = render_selectivity_hero_svg(h, "CEACAM5", "COADREAD")
    assert svg1 == svg2                                  # deterministic
    assert svg1.startswith("<svg") and svg1.rstrip().endswith("</svg>")
    assert "CEACAM5" in svg1 and "COADREAD" in svg1


def test_emit_writes_svg_and_json(tmp_path):
    decision = {"target": "CEACAM5", "indication": "COADREAD", "headline": _clean_headline()}
    paths = emit_selectivity_hero(decision, tmp_path)
    assert len(paths) == 2
    assert (tmp_path / "figure_selectivity_evidence_strip.svg").exists()
    assert (tmp_path / "selectivity_evidence_strip.json").exists()


def test_emit_noop_without_verdict(tmp_path):
    """No selectivity_class → nothing emitted (best-effort, never fabricates a hero)."""
    assert emit_selectivity_hero({"target": "X", "headline": {}}, tmp_path) == []
