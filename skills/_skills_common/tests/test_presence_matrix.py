"""Tests for the Presence × Context hero matrix renderer (skills/_skills_common/presence_matrix.py).

Pin the HONESTY DISCIPLINE the view must uphold (mirrors ordinal_view): presence tiers are
order-preserving; data_unavailable / missing cells are OFF-SCALE (never a tier); the normal-tissue
column is a status COMPARATOR, never on the presence ramp; and it is a one-way VIEW (no verdict).
Pure over decision['headline'] — no S3, no method reads.
"""

from __future__ import annotations

from _skills_common.presence_matrix import (  # noqa: E402
    _sc_detail,
    _short_verdict,
    _status_of,
    _tier_of,
    _wrap_two_lines,
    build_matrix_cells,
    emit_presence_matrix,
    render_presence_matrix_svg,
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
            "bulk_rna/cell_line": {
                "measurement": "bulk_rna",
                "sample_context": "cell_line",
                "verdict": "lineage_restricted",
                "driving_rule_id": "expression-lineage-restricted-supportive",
                "evidence_state": "measured",
            },
            "bulk_rna/tumor": {
                "measurement": "bulk_rna",
                "sample_context": "tumor",
                "verdict": "tumor_broadly_expressed",
                "driving_rule_id": "tumor-expression-broadly-high-supportive",
                "evidence_state": "measured",
            },
            "bulk_protein_ms/tumor": {
                "measurement": "bulk_protein_ms",
                "sample_context": "tumor",
                "verdict": "protein_modestly_upregulated",
                "driving_rule_id": "protein-modestly-up-neutral",
                "evidence_state": "measured",
            },
            "sc_rna/tumor": {
                "measurement": "sc_rna",
                "sample_context": "tumor",
                "verdict": "sc_malignant_detected",
                "driving_rule_id": "sc-expression-malignant-broadly-detected-supportive",
                "evidence_state": "measured",
            },
            "sc_rna/normal": {
                "measurement": "sc_rna",
                "sample_context": "normal",
                "verdict": "HIGH_LIABILITY",
                "driving_rule_id": None,
                "evidence_state": "comparator",
            },
            "protein_ihc/normal": {
                "measurement": "protein_ihc",
                "sample_context": "normal",
                "verdict": "broad_normal_expression",
                "driving_rule_id": None,
                "evidence_state": "comparator",
            },
        },
    }


def test_tier_is_order_preserving_and_unknown_is_none():
    # Real bucket verdicts, one per tier. `ihc_not_detected` (HPA antibody-IHC) is the sole reachable
    # tier-0 bucket verdict — CPTAC/bulk-MS cannot assert per-gene absence (protein_not_detected retired,
    # target-contracts #467). It replaces the never-emitted synthetic `protein_absent` this test used
    # before the exact-membership conversion.
    assert _tier_of("tumor_broadly_expressed") == 3
    assert _tier_of("protein_broadly_moderate") == 2
    assert _tier_of("lineage_restricted") == 1
    assert _tier_of("ihc_not_detected") == 0
    # order is preserved across the tiers
    assert (
        _tier_of("tumor_broadly_expressed")
        > _tier_of("protein_broadly_moderate")
        > _tier_of("lineage_restricted")
        > _tier_of("ihc_not_detected")
    )
    # unknown verdict → NO fabricated rank
    assert _tier_of("some_new_unmapped_verdict") is None
    assert _tier_of(None) is None


# ── Mutation teeth: the three substring failure modes the exact-membership conversion closes ──────────
# Each input below is mis-tiered by the pre-2026-09-27 substring code (`token in verdict`) and correctly
# handled by exact membership. Verified RED on the pre-fix `_TIER_SUBSTRINGS` code, GREEN after. The
# expected tier is RE-DERIVED by calling `_tier_of` (the function under test) — no fixtured derived value.
# These mirror the three MEASURED failures documented above presence_cardboard_figure._SIGNAL.


def test_matrix_tier_fall_through_is_conservative_never_a_spurious_high_tier():
    """Mode 1 — FALL-THROUGH. A token that is NOT a presence-level verdict must land on the conservative
    neutral (None), never borrow an alarming tier. `broadly_high_confidence` merely CONTAINS the old
    substring `broadly_high`, so the substring code returned tier 3 (the TOP presence tier) for a token
    that is not a presence level at all. Exact membership returns None (rendered neutral gray)."""
    assert _tier_of("broadly_high_confidence") is None


def test_matrix_tier_short_substring_does_not_invert_polarity():
    """Mode 2 — COLLISION (the `ns` ⊂ `tumor_intrinsic` analog). `tumor_present_not_absent` is a
    present-meaning token, but it CONTAINS the tier-0 substring `absent`, so the substring code inverted
    it to tier 0 (a fabricated measured-ABSENCE). Exact membership returns None — no borrowed polarity."""
    assert _tier_of("tumor_present_not_absent") is None


def test_matrix_tier_uppercase_variant_is_not_substring_matched():
    """Mode 3 — CASE. Exact membership is case-normalized once, so a legitimate token tiers identically
    regardless of case; but an uppercase token that merely CONTAINS a tier substring (which the substring
    code caught after its own .lower()) no longer borrows that tier."""
    # a real verdict tiers identically case-insensitively
    assert _tier_of("BROADLY_HIGH_EXPRESSION") == 3
    assert _tier_of("Lineage_Restricted") == 1
    # an uppercase non-verdict that only embeds a tier substring → None, not the borrowed tier
    assert _tier_of("BROADLY_HIGH_UNRELATED_FLAG") is None


# Byte-stability spec: every verdict that can populate the six presence-tier buckets, with the tier the
# pre-conversion substring code produced. Sourced from tumor-presence/scripts/run.py — the three ladders
# (_EXPRESSION_RANK / _PROTEIN_RANK / _SC_RNA_RANK) + _MEASURED_UNRULED_PRESENT. `None` = neutral gray
# (fall-through under substrings, preserved by omission from the exact map). This pins that the
# substring→exact conversion is corpus byte-stable: change a tier here only for a deliberate reason.
_BUCKET_VERDICT_TIERS = {
    # bulk_rna (_EXPRESSION_RANK)
    "broadly_high_expression": 3,
    "strongly_upregulated_in_tumor": 3,
    "tumor_broadly_expressed": 3,
    "tumor_subset_high_expression": None,
    "modestly_upregulated_in_tumor": 2,
    "tumor_moderately_expressed": 2,
    "lineage_restricted": 1,
    "broadly_moderate_expression": 2,
    "tumor_sparsely_expressed": 1,
    "modestly_downregulated_in_tumor": None,
    "strongly_downregulated_in_tumor": None,
    "broadly_low_expression": 1,
    "not_informative": None,
    # bulk_protein_ms (_PROTEIN_RANK + _MEASURED_UNRULED_PRESENT)
    "protein_strongly_upregulated": 3,
    "protein_broadly_high": 3,
    "protein_lineage_restricted": 1,
    "protein_modestly_upregulated": 2,
    "broadly_tumor_elevated": None,
    "multi_tumor_elevated": None,
    "protein_broadly_moderate": 2,
    "single_tumor_elevated": None,
    "not_tumor_elevated": None,
    "protein_modestly_downregulated": None,
    "protein_strongly_downregulated": None,
    "protein_broadly_low": 1,
    "protein_present_not_elevated": 1,
    # sc_rna/tumor (_SC_RNA_RANK)
    "sc_malignant_detected": 2,
    "sc_microenvironment_dominant": None,
    "sc_broadly_low": 1,
    # protein_ihc/tumor (_MEASURED_UNRULED_PRESENT)
    "ihc_detected_high": None,
    "ihc_detected_moderate": None,
    "ihc_detected_low": None,
    "ihc_not_detected": 0,
    # data_unavailable never reaches _tier_of (evidence_state gates it) but must be inert here too
    "data_unavailable": None,
}


def test_every_bucket_verdict_tiers_byte_stable():
    """The full enumeration of presence-bucket verdicts tiers exactly as before the exact-membership
    conversion (no corpus value moved). A tier change here is a deliberate decision, not a silent drift."""
    for token, expected in _BUCKET_VERDICT_TIERS.items():
        assert _tier_of(token) == expected, (token, _tier_of(token), expected)


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
    assert "url(#na)" in svg


def test_emit_writes_svg_and_json(tmp_path):
    decision = {"target": "CEACAM5", "indication": "COADREAD", "headline": _headline()}
    paths = emit_presence_matrix(decision, tmp_path)
    names = {p.name for p in paths}
    assert names == {"figure_presence_context_matrix.svg", "presence_context_matrix.json"}
    assert all(p.exists() and p.stat().st_size > 0 for p in paths)


def test_emit_is_noop_without_a_matrix():
    # no presence_verdict_by_modality → nothing to render (honest no-op, never raises)
    assert emit_presence_matrix({"target": "X", "headline": {}}, "/tmp/should_not_be_written") == []


def test_cell_labels_wrap_not_truncate():
    """Readability: long verdict labels wrap to two lines rather than ellipsis-truncating. The three
    longest presence verdicts must render with NO ellipsis in the SVG."""
    svg = render_presence_matrix_svg(_headline(), "CEACAM5", "COADREAD")
    assert "…" not in svg, "a verdict label was ellipsis-truncated — it should wrap to two lines"
    # the label the row already names ('expression') is dropped so the word fits
    assert _short_verdict("broadly_moderate_expression") == "broadly moderate"
    assert _short_verdict("tumor_broadly_expressed") == "broadly expressed"


def test_wrap_two_lines_never_exceeds_two_lines_or_width():
    for label, mx in [
        ("broadly moderate", 15),
        ("present not elevated", 12),
        ("lineage restricted", 11),
        ("superlongunbreakabletoken", 10),
    ]:
        lines = _wrap_two_lines(label, mx)
        assert 1 <= len(lines) <= 2
        assert all(len(ln) <= mx for ln in lines), (label, lines)


def test_sc_detail_projection_and_strip_render():
    """The single-cell detail block is projected from the headline sc_* fields and shows on the SVG when
    measured; honest 'not measured' otherwise."""
    h = dict(_headline())
    h.update(
        {
            "sc_expression_class": "malignant_broadly_detected",
            "sc_malignant_detection_fraction": 0.8886,
            "sc_tce_homogeneity_class": "homogeneous",
            "sc_caf_vs_malignant_class": "caf_low",
            "sc_n_donor_groups": 453,
            "sc_n_datasets": 45,
        }
    )
    d = _sc_detail(h)
    assert d["measured"] is True and d["tce_homogeneity_class"] == "homogeneous"
    svg = render_presence_matrix_svg(h, "EPCAM", "COADREAD")
    assert "Single-cell (tumor)" in svg and "malignant cells" in svg and "CAF-low" in svg
    # unmeasured sc → honest label, no CAF/homogeneity clutter
    h2 = dict(_headline())
    h2["sc_expression_class"] = "data_unavailable"
    assert _sc_detail(h2)["measured"] is False
    assert "not measured for this indication" in render_presence_matrix_svg(h2, "X", "Y")
