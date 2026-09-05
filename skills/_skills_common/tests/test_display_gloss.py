"""display_gloss — the plain-language reading registry (interpretation-encoding Stage 1).

CONTRACT (coverage): every salience-promoted metric field (SALIENCE_SPECS effect/significance/omnibus/
extra_scalars) MUST have a METRIC_GLOSS entry, so no verdict-bearing card metric renders as a bare
snake_case field. Plus the primitives (direction phrase normalization, affix backstop, card description
interpolation) behave.
"""
import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common import display_gloss as dg
from _skills_common.evidence_salience import SALIENCE_SPECS


def _salience_metric_fields() -> set:
    fields = set()
    for s in SALIENCE_SPECS.values():
        for k in ("effect_field", "significance_field", "omnibus_field"):
            if s.get(k):
                fields.add(s[k])
        for e in (s.get("extra_scalars") or []):
            fields.add(e)
    return fields


def test_every_salience_metric_has_a_gloss_entry():
    missing = sorted(f for f in _salience_metric_fields() if f not in dg.METRIC_GLOSS)
    assert not missing, f"salience metric fields missing a METRIC_GLOSS entry: {missing}"


def test_gloss_entries_are_well_formed():
    for field, entry in dg.METRIC_GLOSS.items():
        assert isinstance(entry, tuple) and len(entry) == 2, f"{field}: entry must be (label, units)"
        label, units = entry
        assert isinstance(label, str) and label, f"{field}: label must be a non-empty str"
        assert units is None or isinstance(units, str), f"{field}: units must be str|None"


def test_direction_phrase_three_values_and_alias_normalization():
    assert dg.direction_phrase("lower_is_stronger") == "lower = stronger"
    assert dg.direction_phrase("higher_is_stronger") == "higher = stronger"
    assert "liability" in dg.direction_phrase("higher_is_worse")
    # token-variance normalization (a prior direction-inversion bug traces to un-normalized tokens)
    assert dg.direction_phrase("higher_worse") == dg.direction_phrase("higher_is_worse")
    assert dg.direction_phrase("HIGHER_IS_WORSE") == dg.direction_phrase("higher_is_worse")
    assert dg.direction_phrase(None) is None
    assert dg.direction_phrase("some_unknown_token") is None


def test_metric_reading_places_the_two_prompt_exemplars():
    # the prompt's two canonical bare numbers must now read as gauged plain language
    r1 = dg.metric_reading("amp_expr_effect_size", 0.62, "higher_is_stronger")   # affix-tail (un-spec'd)
    assert "0.62" in r1 and "effect size" in r1 and "higher = stronger" in r1
    r2 = dg.metric_reading("median_chronos_hotspot_mutant", -1.73, "lower_is_stronger")
    assert "-1.73" in r2 and "CHRONOS" in r2 and "lower = stronger" in r2 and "hotspot-mutant" in r2


def test_affix_backstop_and_fallback():
    # un-spec'd tail fields still get a units hint from the affix table
    assert dg.gloss("driver_recurrence_percentile")[1] == "%ile"
    assert dg.gloss("some_tumor_log2fc")[1] == "log2FC"
    assert dg.gloss("hotspot_mannwhitney_q")[1] == "q"
    # pure fallback: no affix match -> humanized label, no units
    label, units = dg.gloss("totally_novel_thing")
    assert label == "totally novel thing" and units is None


def test_significance_fields_share_the_q_p_convention():
    for f in ("q_value", "bh_q_value", "protein_bh_q_value", "intogen_min_qvalue", "q_value_cell_a"):
        assert dg.METRIC_GLOSS[f][1] == "q", f
    assert dg.METRIC_GLOSS["gi_ttest_pvalue"][1] == "p"


def test_card_description_interpolates_placeholders():
    # a real card carries a `question:` with {target.symbol} — must be filled, never left raw
    d = dg.card_description("mutation-stratified-dependency", target="KRAS", indication="COADREAD")
    if d is not None:  # fail-soft when the contracts checkout is absent (isolated CI)
        assert "KRAS" in d
        assert "{target" not in d and "{indication" not in d


def test_card_description_failsoft_for_unknown_card():
    assert dg.card_description("this-card-does-not-exist", "KRAS", "COADREAD") is None


def test_humanize():
    assert dg.humanize("HIGH_LIABILITY") == "High liability"
    assert dg.humanize("between_controls") == "Between controls"
    assert dg.humanize(None) == ""


def test_gauge_string_comparator_delta():
    gv = {"metric": "median_chronos_hotspot_mutant", "value": -1.729, "scale": "chronos",
          "direction": "lower_is_stronger", "distance_to_cut": -1.142,
          "frame": {"kind": "comparator_delta", "anchors": [
              {"role": "comparator", "label": "hotspot_wildtype", "value": -0.5864},
              {"role": "cut", "label": "strong_effect_delta", "value": -0.5}]}}
    s = dg.gauge_string(gv)
    assert "hotspot-mutant lines -1.729" in s
    assert "vs hotspot wildtype -0.5864" in s
    assert "Δ-1.142" in s and "past the -0.5 cut" in s


def test_gauge_string_floor_cut_ceiling_oriented_and_positioned():
    gv = {"metric": "median_chronos_panel", "value": -0.4574, "scale": "chronos",
          "direction": "lower_is_stronger", "position": "between_controls",
          "frame": {"kind": "floor_cut_ceiling", "anchors": [
              {"role": "floor", "label": "non_essential_floor", "value": -0.038},
              {"role": "ceiling", "label": "pan_essential_ceiling", "value": -1.499},
              {"role": "cut", "label": "dependency_cut", "value": -0.5}]}}
    s = dg.gauge_string(gv)
    assert s.startswith("between controls — ")
    assert "between non essential floor -0.038 and pan essential ceiling -1.499" in s
    # -0.4574 is WEAKER than the -0.5 dependency cut (lower_is_stronger) -> "short of"
    assert "short of the -0.5 cut" in s


def test_gauge_string_empty_and_no_frame():
    assert dg.gauge_string({}) == ""
    assert dg.gauge_string({"value": None}) == ""
    # no frame -> falls back to the glossed metric reading
    s = dg.gauge_string({"metric": "median_chronos", "value": -1.2, "scale": "chronos",
                         "direction": "lower_is_stronger", "frame": {"kind": None, "anchors": []}})
    assert "median CRISPR gene-effect (CHRONOS)" in s and "-1.2" in s
