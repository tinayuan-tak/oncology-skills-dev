"""Tests for the Presence × Context hero matrix renderer (skills/_skills_common/presence_matrix.py).

Pin the HONESTY DISCIPLINE the view must uphold (mirrors ordinal_view): presence tiers are
order-preserving; data_unavailable / missing cells are OFF-SCALE (never a tier); the normal-tissue
column is a status COMPARATOR, never on the presence ramp; and it is a one-way VIEW (no verdict).
Pure over decision['headline'] — no S3, no method reads.
"""
from __future__ import annotations

import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]        # skills/
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common.presence_matrix import (  # noqa: E402
    build_matrix_cells, render_presence_matrix_svg, emit_presence_matrix, _tier_of, _status_of,
)


def _headline():
    """A CEACAM5-shaped headline: tumor RNA high, cell-line RNA restricted (discordant),
    protein moderate, sc malignant detected, and BOTH normal comparators a liability."""
    return {
        "presence_verdict": "tumor_broadly_expressed",
        "driving_rule_id": "tumor-expression-broadly-high-supportive",
        "headline_lens": "bulk_rna/tumor",
        "cell_line_vs_tumor_discordant": True,
        "presence_interpretation_note": "one-word verdict understates tumor presence",
        "presence_verdict_by_modality": {
            "bulk_rna/cell_line": {"measurement": "bulk_rna", "sample_context": "cell_line",
                                   "verdict": "lineage_restricted",
                                   "driving_rule_id": "expression-lineage-restricted-supportive",
                                   "evidence_state": "measured"},
            "bulk_rna/tumor": {"measurement": "bulk_rna", "sample_context": "tumor",
                               "verdict": "tumor_broadly_expressed",
                               "driving_rule_id": "tumor-expression-broadly-high-supportive",
                               "evidence_state": "measured"},
            "bulk_protein_ms/tumor": {"measurement": "bulk_protein_ms", "sample_context": "tumor",
                                      "verdict": "protein_modestly_upregulated",
                                      "driving_rule_id": "protein-modestly-up-neutral",
                                      "evidence_state": "measured"},
            "sc_rna/tumor": {"measurement": "sc_rna", "sample_context": "tumor",
                             "verdict": "sc_malignant_detected",
                             "driving_rule_id": "sc-expression-malignant-broadly-detected-supportive",
                             "evidence_state": "measured"},
            "sc_rna/normal": {"measurement": "sc_rna", "sample_context": "normal",
                              "verdict": "HIGH_LIABILITY", "driving_rule_id": None,
                              "evidence_state": "comparator"},
            "protein_ihc/normal": {"measurement": "protein_ihc", "sample_context": "normal",
                                   "verdict": "broad_normal_expression", "driving_rule_id": None,
                                   "evidence_state": "comparator"},
        },
    }


def test_tier_is_order_preserving_and_unknown_is_none():
    assert _tier_of("tumor_broadly_expressed") == 3
    assert _tier_of("protein_broadly_moderate") == 2
    assert _tier_of("lineage_restricted") == 1
    assert _tier_of("protein_absent") == 0
    # order is preserved across the tiers
    assert _tier_of("tumor_broadly_expressed") > _tier_of("protein_broadly_moderate") > \
        _tier_of("lineage_restricted") > _tier_of("protein_absent")
    # unknown verdict → NO fabricated rank
    assert _tier_of("some_new_unmapped_verdict") is None
    assert _tier_of(None) is None


def test_measured_cells_get_a_tier_missing_cells_are_off_scale():
    view = build_matrix_cells(_headline())
    cells = view["cells"]
    # measured presence cells are on-scale
    assert cells["bulk_rna/tumor"]["tier"] == 3
    assert cells["bulk_rna/cell_line"]["tier"] == 1
    # a bucket the skill did not report (no bulk_rna/normal, no protein_ihc/tumor) is OFF-SCALE:
    # present=False, tier None, status None — it must never acquire a presence tier.
    for missing in ("bulk_rna/normal", "protein_ihc/tumor", "sc_rna/cell_line"):
        assert cells[missing]["present"] is False
        assert cells[missing]["tier"] is None
        assert cells[missing]["status"] is None


def test_normal_column_is_a_status_comparator_not_a_presence_tier():
    view = build_matrix_cells(_headline())
    cells = view["cells"]
    # both normal comparators map to a STATUS (window), never a presence tier
    assert cells["sc_rna/normal"]["tier"] is None
    assert cells["sc_rna/normal"]["status"] == "critical"
    assert cells["protein_ihc/normal"]["status"] == "critical"
    assert _status_of("broad_normal_expression") == "critical"
    assert _status_of("absent") == "good"


def test_headline_lens_is_flagged_on_the_driving_bucket_only():
    view = build_matrix_cells(_headline())
    cells = view["cells"]
    assert cells["bulk_rna/tumor"]["is_headline_lens"] is True
    assert cells["bulk_rna/cell_line"]["is_headline_lens"] is False
    assert view["cell_line_vs_tumor_discordant"] is True
    # the view carries the anti-false-precision disclaimer
    assert "not a verdict input" in view["_disclaimer"].lower()


def test_render_svg_is_wellformed_and_shows_labels_not_color_alone():
    svg = render_presence_matrix_svg(_headline(), "CEACAM5", "COADREAD")
    assert svg.startswith("<svg") and svg.rstrip().endswith("</svg>")
    assert "CEACAM5" in svg and "COADREAD" in svg
    # tier is never color-alone — the verdict label text is present (may be truncated to fit)
    assert "broadly" in svg
    # normal comparator carries an icon + word, not hue alone
    assert "liability" in svg
    # off-scale cells are hatched (pattern) not ramped
    assert 'url(#na)' in svg


def test_emit_writes_svg_and_json(tmp_path):
    decision = {"target": "CEACAM5", "indication": "COADREAD", "headline": _headline()}
    paths = emit_presence_matrix(decision, tmp_path)
    names = {p.name for p in paths}
    assert names == {"figure_presence_context_matrix.svg", "presence_context_matrix.json"}
    assert all(p.exists() and p.stat().st_size > 0 for p in paths)


def test_emit_is_noop_without_a_matrix():
    # no presence_verdict_by_modality → nothing to render (honest no-op, never raises)
    assert emit_presence_matrix({"target": "X", "headline": {}}, "/tmp/should_not_be_written") == []
