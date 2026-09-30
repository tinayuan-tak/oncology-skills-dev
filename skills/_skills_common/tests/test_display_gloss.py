"""display_gloss — the plain-language reading registry (interpretation-encoding Stage 1).

CONTRACT (coverage): every salience-promoted metric field (SALIENCE_SPECS effect/significance/omnibus/
n_field/extra_scalars) MUST have a METRIC_GLOSS entry, so no verdict-bearing card metric renders as a bare
snake_case field. Plus the primitives (direction phrase normalization, affix backstop, card description
interpolation) behave.

`n_field` joined that set on 2026-09-12. It had been omitted since the check was written, so the check was
VACUOUS for the whole denominator family — no fleet n_field was glossed and `n_lethal` rendered "n lethal",
`n_paired_models` rendered "n paired models" (paired on WHAT?). Same vacuity class as the gaugeability
invariant: ask what the check does NOT enumerate.
"""

from pathlib import Path

import pytest
from _skills_common import display_gloss as dg
from _skills_common.evidence_salience import SALIENCE_SPECS
from _skills_common.paths import TARGET_CONTRACTS_ROOT_DEFAULT


def _salience_metric_fields() -> set:
    fields = set()
    for s in SALIENCE_SPECS.values():
        for k in ("effect_field", "significance_field", "omnibus_field", "n_field"):
            if s.get(k):
                fields.add(s[k])
        for e in s.get("extra_scalars") or []:
            fields.add(e)
        # A reference_frame's value_field is the metric a GAUGE renders (_project_frame sets
        # gv["metric"] = value_field), so it needs a gloss for exactly the same reason an effect_field does
        # — and it was missing from this set, which is a DIRECTION gap, not an oversight about one field:
        # this guard only ever looked at the spec's scalar keys, so every ruler value_field that was not
        # also an effect_field could ship unglossed and render as the humanized field name with no units
        # ("median cd8 fraction"). Four did. distance_field/total_field are deliberately NOT included:
        # they surface as a distance number and an anchor label, not as the metric name.
        rf = s.get("reference_frame")
        for f in rf if isinstance(rf, list) else [rf]:
            if isinstance(f, dict) and f.get("value_field"):
                fields.add(f["value_field"])
    return fields


def test_every_salience_metric_has_a_gloss_entry():
    missing = sorted(f for f in _salience_metric_fields() if f not in dg.METRIC_GLOSS)
    assert not missing, f"salience metric fields missing a METRIC_GLOSS entry: {missing}"


def test_every_n_field_label_says_what_it_counts():
    """The coverage test above only demands an ENTRY; a denominator also has to earn it. The affix backstop
    already supplies 'count' for n_*, so an entry whose label is just the humanized field name adds nothing
    — the label must name the arm/cohort/pairing being counted."""
    bare = []
    for spec in SALIENCE_SPECS.values():
        f = spec.get("n_field")
        if not f:
            continue
        label, units = dg.gloss(f)
        if label.strip().lower() == f.replace("_", " "):
            bare.append(f)
        assert units == "count", f"{f}: a denominator's units must be 'count', got {units!r}"
    assert not bare, f"n_field gloss labels that only humanize the field name: {bare}"


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
    r1 = dg.metric_reading("amp_expr_effect_size", 0.62, "higher_is_stronger")  # affix-tail (un-spec'd)
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


# ── the affix backstop's two mislabel classes (2026-09-12) ──────────────────────────────────────────
def test_pli_units_need_a_pli_TOKEN_not_a_substring():
    """`pli` was a substring rule, so every am-PLI-fied / s-PLI-ce field claimed pLI units (20 real
    contract summary_fields, all 20 wrong). Both directions pinned: the token still resolves, the words
    that merely contain it do not."""
    assert dg.gloss("pli")[1] == "pLI"
    assert dg.gloss("gnomad_pli")[1] == "pLI"
    assert dg.gloss("pli_score")[1] == "pLI"
    # the 20 false positives — each now gets its own honest units (or none), never pLI
    assert dg.gloss("n_amplified")[1] == "count"
    assert dg.gloss("n_amplified_overexpressed")[1] == "count"
    assert dg.gloss("patient_amplified_fraction")[1] == "fraction"
    assert dg.gloss("cn_fraction_focal_amplification")[1] == "fraction"
    assert dg.gloss("n_splice_events")[1] == "count"
    assert dg.gloss("amplification_threshold_relative_cn")[1] is None
    assert dg.gloss("redirects_applied")[1] is None


def test_categorical_suffixes_get_no_units_but_their_numeric_siblings_keep_theirs():
    """A class/label value with units reads as nonsense ('splice_exon_skip_class = exon_skip (pLI)'). The
    guard must be surgical: the numeric sibling of each categorical name keeps its units, and a count that
    happens to end in a plural noun is untouched."""
    for f in (
        "allgene_percentile_class",
        "selectivity_allgene_percentile_context",
        "subtype_effect_size_class",
        "lineage_omnibus_effect_size_class",
        "pan_essential_fraction_call",
        "til_fraction_class",
        "modality_implication_basis",
        "wgd_context",
    ):
        assert dg.gloss(f)[1] is None, f
    # falsifier — the same rules still label the NUMERIC forms
    assert dg.gloss("allgene_percentile")[1] == "%ile"
    assert dg.gloss("subtype_effect_size")[1] == "effect size"
    assert dg.gloss("til_fraction")[1] == "fraction"
    assert dg.gloss("n_enriched_lineages")[1] == "count"  # a real count, not a category


def test_no_vocabulary_declared_contract_field_gets_units():
    """Contract-grounded sweep, not a hand list: any field a card declares in `summary_fields_vocabulary`
    has an ENUMERATED value set, so units on it are always wrong. 10 such fields were mislabelled before
    the guard (%ile / effect size / fraction / pLI)."""
    import os

    import yaml

    root = os.environ.get("TARGET_CONTRACTS_ROOT", TARGET_CONTRACTS_ROOT_DEFAULT)
    cards = Path(root) / "cards"
    if not cards.is_dir():
        pytest.skip("target-contracts checkout absent")

    vocab_fields: set = set()

    def _walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k == "summary_fields_vocabulary" and isinstance(v, dict):
                    vocab_fields.update(v.keys())
                else:
                    _walk(v)
        elif isinstance(node, list):
            for v in node:
                _walk(v)

    for p in sorted(cards.glob("*.card.yaml")):
        _walk(yaml.safe_load(p.read_text()) or {})
    assert len(vocab_fields) > 100, f"vocabulary harvest looks broken: {len(vocab_fields)} fields"

    with_units = sorted(f for f in vocab_fields if dg.gloss(f)[1])
    assert not with_units, f"categorical (vocabulary-declared) fields carrying units: {with_units}"


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
    gv = {
        "metric": "median_chronos_hotspot_mutant",
        "value": -1.729,
        "scale": "chronos",
        "direction": "lower_is_stronger",
        "distance_to_cut": -1.142,
        "frame": {
            "kind": "comparator_delta",
            "anchors": [
                {"role": "comparator", "label": "hotspot_wildtype", "value": -0.5864},
                {"role": "cut", "label": "strong_effect_delta", "value": -0.5},
            ],
        },
    }
    s = dg.gauge_string(gv)
    assert "hotspot-mutant lines -1.729" in s
    assert "vs hotspot wildtype -0.5864" in s
    assert "Δ-1.142" in s and "past the -0.5 cut" in s


def test_gauge_string_floor_cut_ceiling_oriented_and_positioned():
    gv = {
        "metric": "median_chronos_panel",
        "value": -0.4574,
        "scale": "chronos",
        "direction": "lower_is_stronger",
        "position": "between_controls",
        "frame": {
            "kind": "floor_cut_ceiling",
            "anchors": [
                {"role": "floor", "label": "non_essential_floor", "value": -0.038},
                {"role": "ceiling", "label": "pan_essential_ceiling", "value": -1.499},
                {"role": "cut", "label": "dependency_cut", "value": -0.5},
            ],
        },
    }
    s = dg.gauge_string(gv)
    assert s.startswith("between controls — ")
    assert "between non essential floor -0.038 and pan essential ceiling -1.499" in s
    # -0.4574 is WEAKER than the -0.5 dependency cut (lower_is_stronger) -> "short of"
    assert "short of the -0.5 cut" in s


def test_gauge_string_empty_and_no_frame():
    assert dg.gauge_string({}) == ""
    assert dg.gauge_string({"value": None}) == ""
    # no frame -> falls back to the glossed metric reading
    s = dg.gauge_string(
        {
            "metric": "median_chronos",
            "value": -1.2,
            "scale": "chronos",
            "direction": "lower_is_stronger",
            "frame": {"kind": None, "anchors": []},
        }
    )
    assert "median CRISPR gene-effect (CHRONOS)" in s and "-1.2" in s


# ── #1944: predictability class → prose + r² interpretation band ─────────────────────────────────────
# Display-only gloss for the residual predictability surfaces #1943's headline does not reach.
# Every enum value the dependency-predictability card declares maps to a phrase; the r² band reuses the
# producer's own cuts (R2_HIGH_CI_LO=0.35, R2_DEPMAP_HIGH_CONF=0.16) — no new thresholds invented.


def test_predictability_class_phrase_covers_every_enum_value():
    expected = {
        "own_omics_driven": "own-omics predictable",
        "context_or_driver_dependent": "context/driver predictable",
        "weakly_predictable": "weakly predictable",
        "unpredictable": "not omics-predictable",
        "data_unavailable": "not computed",
    }
    for token, phrase in expected.items():
        assert dg.predictability_class_phrase(token) == phrase
    # unknown / empty tokens yield None so the raw token renders unchanged
    assert dg.predictability_class_phrase("some_future_class") is None
    assert dg.predictability_class_phrase("") is None
    assert dg.predictability_class_phrase(None) is None


def test_r2_interpretation_matches_producer_cuts_at_boundaries():
    # cuts mirror precompute cli.py: R2_HIGH_CI_LO=0.35, R2_DEPMAP_HIGH_CONF=0.16
    assert dg.R2_HIGH_CI_LO == 0.35
    assert dg.R2_DEPMAP_HIGH_CONF == 0.16
    # boundaries are inclusive at the cut value
    assert dg.r2_interpretation(0.35) == "well predicted"
    assert dg.r2_interpretation(0.62) == "well predicted"
    assert dg.r2_interpretation(0.3499) == "weak"
    assert dg.r2_interpretation(0.16) == "weak"
    assert dg.r2_interpretation(0.1599) == "not predictable"
    assert dg.r2_interpretation(0.0) == "not predictable"
    # non-numeric / bool → None
    assert dg.r2_interpretation(None) is None
    assert dg.r2_interpretation("0.4") is None
    assert dg.r2_interpretation(True) is None


def test_metric_reading_appends_r2_band_and_keeps_raw_number():
    s = dg.metric_reading("pearson_r_squared_rf", 0.62, direction="higher_is_stronger")
    assert "0.62" in s and "well predicted" in s
    s2 = dg.metric_reading("r2", 0.1, direction="higher_is_stronger")
    assert "0.1" in s2 and "not predictable" in s2


def test_gauge_string_position_uses_class_gloss():
    s = dg.gauge_string(
        {
            "metric": "pearson_r_squared_rf",
            "value": 0.62,
            "scale": "r2",
            "direction": "higher_is_stronger",
            "position": "own_omics_driven",
            "frame": {"kind": "distance_to_cut", "anchors": [{"role": "cut", "value": 0.16}]},
        }
    )
    assert s.startswith("own-omics predictable — ")
