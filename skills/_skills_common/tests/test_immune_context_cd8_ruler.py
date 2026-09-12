"""immune_context gets a card-data ruler — the last of the five open items from the immune-context
production review (the other four landed as #1331/#1332/#1335 + target-contracts #753).

The axis carried classes and an effect_field but NO reference_frame, so it shipped an ungauged number.
The ruler is a graded_band on `median_cd8_fraction` against the card's own two declared thresholds
(cd8_fraction_cold_max 0.084 / cd8_fraction_hot_min 0.113).

TWO things here are load-bearing and easy to "simplify" away:

  1. The gauge is on median_cd8_fraction, NOT on the spec's effect_field cd8_high_minus_low — that is a
     DELTA and fraction cuts do not gauge a delta. This scale mismatch is why the 09-10 batch meter
     rollout deliberately skipped this axis.
  2. `atlas_numeric: False`. This card's primary call is target-INDEPENDENT, so median_cd8_fraction is
     identical for every target in an indication; minting an atlas numeric from it would cluster known
     targets by indication and phrase an indication property as a target property.

DISPLAY-ONLY / verdict-INERT.
"""

import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common.display_gloss import METRIC_GLOSS, gauge_string, gloss  # noqa: E402
from _skills_common.evidence_salience import SALIENCE_SPECS, build_interpretation  # noqa: E402
from _skills_common.feature_vectoriser import numeric_feature_specs  # noqa: E402

_SPEC = SALIENCE_SPECS["immune_context"]


def _frames():
    rf = _SPEC.get("reference_frame")
    return rf if isinstance(rf, list) else [rf]


def _primary():
    return _frames()[0]


# live-shaped BLCA summary (the values a real run emits; the fraction is the quantity the cuts band)
def _summary(cd8=0.1103, klass="immune_intermediate", **over):
    s = {
        "immune_context_class": klass,
        "median_cd8_fraction": cd8,
        "median_total_t_cell_fraction": 0.3222,
        "n_samples": 433,
        "cd8_high_minus_low": 0.0121,
        "n_patients_joined": 402,
    }
    s.update(over)
    return s


def _gauge(**kw):
    gvs = build_interpretation({}, _summary(**kw), _SPEC, "immune-context")
    return next(g for g in gvs if g["frame"]["kind"] == "graded_band")


def test_the_axis_is_gauged_at_all():
    """Non-vacuity FIRST: every assertion below is worthless if the frame never projects."""
    gvs = build_interpretation({}, _summary(), _SPEC, "immune-context")
    assert gvs, "immune_context projected NO gauged value — the ruler is not reaching the renderer"


def test_the_gauge_is_the_fraction_not_the_antigen_conditioned_delta():
    """The delta is on a different scale from the fraction cuts; gauging it would compare 0.012 to 0.113."""
    assert _primary()["value_field"] == "median_cd8_fraction"
    assert _primary()["kind"] == "graded_band"
    assert all(f.get("value_field") != "cd8_high_minus_low" for f in _frames() if isinstance(f, dict)), (
        "cd8_high_minus_low is a DELTA — it must not be gauged against this card's fraction cuts"
    )
    # the delta stays the spec's effect_field (unchanged); only the RULER differs
    assert _SPEC["effect_field"] == "cd8_high_minus_low"


def test_both_cuts_resolve_to_the_cards_own_declared_thresholds():
    anchors = {a["label"]: a["value"] for a in _gauge()["frame"]["anchors"] if a["role"] == "cut"}
    assert len(anchors) == 2, f"expected the cold/hot ladder, got {anchors}"
    assert sorted(anchors.values()) == [0.084, 0.113], (
        f"cuts must single-source cd8_fraction_cold_max/hot_min from the contract, got {anchors}"
    )


def test_the_band_separates_cold_intermediate_and_hot_on_live_values():
    """A graded_band that reports the same thing either side of both cuts is not a gauge. Distinctness
    asserted BEFORE any per-string claim."""
    cold = gauge_string(_gauge(cd8=0.0712, klass="immune_cold"))
    mid = gauge_string(_gauge(cd8=0.1103, klass="immune_intermediate"))
    hot = gauge_string(_gauge(cd8=0.1312, klass="immune_hot"))
    assert len({cold, mid, hot}) == 3, f"band does not discriminate: {cold!r} / {mid!r} / {hot!r}"
    # position is READ VERBATIM from the card's own class, never recomputed skills-side
    assert _gauge(cd8=0.1312, klass="immune_hot")["position"] == "immune_hot"
    assert _gauge(cd8=0.1312, klass="immune_hot")["position_source"] == "immune_context_class"


def test_the_value_carries_a_scale_and_a_direction():
    gv = _gauge()
    assert gv["scale"] == "fraction" and gv["direction"] == "higher_is_stronger"
    assert gv["value"] == 0.1103  # no bare number, and not re-rounded away


def test_the_gloss_says_RANK_not_density():
    """THE LOAD-BEARING HALF. 0.084/0.113 are the Q1/Q3 of the CD8 share across the 33 TCGA studies, so
    `immune_hot` means top-quartile AMONG INDICATIONS — not 'heavily infiltrated', and not an ICI-response
    read (ICI-refractory PRAD at 0.1312 lands hot; ICI-approved BLCA/LUAD/LUSC land intermediate). Without
    that framing a bare 0.11 beside a 'hot' label reads as an absolute density."""
    assert "median_cd8_fraction" in METRIC_GLOSS, "the ruler's metric must not render as a humanized field name"
    label, units = gloss("median_cd8_fraction")
    assert "rank" in label.lower(), f"the gloss must say the band is rank-derived, got {label!r}"
    assert label.strip().lower() != "median cd8 fraction", "that is the bare affix fallback, not a gloss"
    assert units == "fraction"  # the NUMBER is a fraction; the BAND around it is what is rank-derived


def test_the_frame_omits_when_the_fraction_is_unmeasured():
    """Drops rather than gates — an unmeasured axis must carry no gauge, not a null-filled or 0-valued one."""
    gvs = build_interpretation({}, _summary(cd8=None), _SPEC, "immune-context")
    assert not [g for g in gvs if g["frame"]["kind"] == "graded_band"]
    assert all(g.get("value") is not None for g in gvs), "a projected frame must never null-fill its value"


def test_immune_context_mints_NO_atlas_numeric_feature():
    """`atlas_numeric: False` is the guard against an INDICATION-level constant entering the known-target
    atlas geometry. The ruler registry and the atlas numeric registry are the same registry, so without the
    flag this display ruler would silently become an atlas feature — and 'stronger than X% of known
    targets' would be phrasing an indication property as a target property."""
    assert _primary().get("atlas_numeric") is False
    assert "immune_context" not in numeric_feature_specs(), (
        "immune_context leaked into the atlas numeric registry — median_cd8_fraction is target-INDEPENDENT"
    )
    # and the fleet cohort_percentile companion must be suppressed too (it reads that same atlas column)
    assert all(f.get("kind") != "cohort_percentile" for f in _frames() if isinstance(f, dict))
