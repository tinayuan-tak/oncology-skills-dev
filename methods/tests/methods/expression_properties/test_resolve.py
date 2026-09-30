"""Resolver: Card-1 (cellline-rna-distribution) measurements → shared L2 expression properties.

P2 of the evidence-property architecture (epic claude-oncology-skills#1507; audit #1506; vocabulary
P1 = target-contracts expression_property.enum.yaml, #865). The resolver rescues the buried
distribution_pattern signal (EPCAM bimodal → heterogeneity=high + prevalence=subset) that the flat
expression_class drops — WITHOUT touching expression_class (verdict-inert).

DISCIPLINE (from the SK#1507 prototype, load-bearing):
  * Store RAW INPUT measurements and RE-DERIVE properties in-test. A fixture of derived values can
    never fail — so every panel below is a raw log2(TPM+1) score list fed through the real
    compute_summary_stats, and the properties are resolved from THAT.
  * ALL-SUPPLY mutation (M3): decision-relevant properties are MULTIPLY-supported, so a single-input
    mutation only degrades — it does not flip. To test a property's REACH, defeat EVERY input that
    supplies it and assert whether it is genuinely over-determined (M4 single-supply control) or
    lossy. Confabulation would survive an all-supply mutation.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")


cli = __import__("onc_methods.depmap_expression_distribution.cli", fromlist=["cli"])
resolve_mod = __import__("onc_methods.expression_properties.resolve", fromlist=["resolve"])
resolve_expression_properties = resolve_mod.resolve_expression_properties
VALID_VALUES = resolve_mod.VALID_VALUES


# --------------------------------------------------------------------------------------------------
# Helpers — RAW panels (log2(TPM+1) per cell line); properties are RE-DERIVED, never fixtured.
# --------------------------------------------------------------------------------------------------
def _summary_from_scores(scores, lineage="Bowel"):
    """Feed a raw per-cell-line score list through the real compute_summary_stats (which computes
    distribution_pattern / CoV / fractions / expression_class), so nothing here is a derived fixture."""
    tpm_by_model = {f"ACH-{i}": float(v) for i, v in enumerate(scores)}
    meta = {m: {"OncotreeLineage": lineage} for m in tpm_by_model}
    return cli.compute_summary_stats(tpm_by_model, meta)


# EPCAM-like: bimodal, frac_off ≈ 0.37, frac_high ≈ 0.44 (issue anchor: 0.435). 37 off + 19 mid + 44 high.
_EPCAM_SCORES = [0.1] * 37 + [3.0] * 19 + [7.0] * 44


def _epcam_summary():
    return _summary_from_scores(_EPCAM_SCORES)


# --------------------------------------------------------------------------------------------------
# The buried-signal rescue — the whole point of P2.
# --------------------------------------------------------------------------------------------------
def test_epcam_bimodal_rescued_while_class_collapses():
    """EPCAM: expression_class COLLAPSES the bimodality to `broadly_moderate`, but the resolver
    recovers heterogeneity=high + prevalence=subset + presence=supported from the SAME measurements
    (the issue's acceptance values)."""
    s = _epcam_summary()
    # the lossy token the flat class emits (the signal is buried here) …
    assert s["expression_class"] == "broadly_moderate"
    assert s["distribution_pattern"] == "bimodal"
    # … and the rescued properties.
    props = resolve_expression_properties(s)
    assert props["heterogeneity"] == "high"
    assert props["prevalence"] == "subset"
    assert props["presence"] == "supported"


def test_resolver_never_mutates_summary_or_class():
    """Verdict-inert at the composition level: resolving does not touch expression_class or any other
    field of the summary read.py already holds (read.py assigns the result to a NEW key)."""
    s = _epcam_summary()
    before = copy.deepcopy(s)
    _ = resolve_expression_properties(s)
    assert s == before  # resolve is pure — no in-place mutation
    assert "expression_properties" not in s


def test_every_emitted_value_is_a_vocabulary_token():
    """Every resolved value must be a declared token for its property (local VALID_VALUES mirror)."""
    for scores in (_EPCAM_SCORES, [7.0] * 40, [0.1] * 40, [0.1] * 30 + [6.5] * 6):
        props = resolve_expression_properties(_summary_from_scores(scores))
        assert set(props) == set(VALID_VALUES)
        for name, value in props.items():
            assert value in VALID_VALUES[name], f"{name}={value!r} not a declared token"


# --------------------------------------------------------------------------------------------------
# PANEL coverage — broad, off/absent, long_tail, bimodal-broad, bimodal-subset (all RE-DERIVED).
# --------------------------------------------------------------------------------------------------
_PANEL = {
    # broadly-high: the whole panel highly-expresses (uniform, top of the range).
    "broadly_high": {
        "scores": [7.0] * 40,
        "expect": {"presence": "supported", "prevalence": "broad", "magnitude": "high", "heterogeneity": "uniform"},
    },
    # off/absent: nothing above the detection floor — a MEASURED negative.
    "off": {
        "scores": [0.1] * 40,
        "expect": {"presence": "absent", "prevalence": "rare", "magnitude": "unmeasured", "heterogeneity": "uniform"},
    },
    # long_tail: mostly off with a rare high tail — the twin's subset_high shape (prevalence=subset).
    "long_tail": {
        "scores": [0.1] * 30 + [6.5] * 6,
        "expect": {"presence": "weak", "prevalence": "subset", "heterogeneity": "high"},
    },
    # bimodal with a MAJORITY highly-expressing → prevalence=broad (twin broadly_high, high_frac≥0.5).
    "bimodal_broad": {
        "scores": [0.1] * 10 + [7.0] * 10,
        "expect": {"presence": "supported", "prevalence": "broad", "heterogeneity": "high"},
    },
    # bimodal with a distinct-but-minority high subset → prevalence=subset (EPCAM archetype).
    "bimodal_subset": {
        "scores": _EPCAM_SCORES,
        "expect": {"presence": "supported", "prevalence": "subset", "heterogeneity": "high", "magnitude": "moderate"},
    },
}


@pytest.mark.parametrize("name", sorted(_PANEL))
def test_panel_archetypes(name):
    spec = _PANEL[name]
    props = resolve_expression_properties(_summary_from_scores(spec["scores"]))
    for prop, expected in spec["expect"].items():
        assert props[prop] == expected, f"{name}: {prop} expected {expected}, got {props[prop]}"


# --------------------------------------------------------------------------------------------------
# ALL-SUPPLY mutation (M3) + single-supply control (M4). Defeat EVERY input that supplies a property.
# --------------------------------------------------------------------------------------------------
def _mutate(summary, **overrides):
    m = copy.deepcopy(summary)
    m.update(overrides)
    return m


def test_heterogeneity_high_is_over_determined_then_reachable():
    """heterogeneity=high is supplied by distribution_pattern AND coefficient_of_variation.
    Single-supply mutations only DEGRADE (M4: stays high); defeating BOTH flips it (M3: reach)."""
    s = _epcam_summary()
    assert resolve_expression_properties(s)["heterogeneity"] == "high"
    assert s["coefficient_of_variation"] >= resolve_mod._CV_HIGH  # the second supply is genuinely present

    # M4 single-supply: kill the shape → CoV alone still resolves high (over-determined).
    only_pattern = _mutate(s, distribution_pattern="continuous")
    assert resolve_expression_properties(only_pattern)["heterogeneity"] == "high"
    # M4 single-supply: kill the CoV → the bimodal shape alone still resolves high.
    only_cv = _mutate(s, coefficient_of_variation=0.0)
    assert resolve_expression_properties(only_cv)["heterogeneity"] == "high"

    # M3 all-supply: defeat BOTH supplies → high is no longer reachable (not confabulated).
    both = _mutate(s, distribution_pattern="continuous", coefficient_of_variation=0.0)
    assert resolve_expression_properties(both)["heterogeneity"] != "high"


def test_prevalence_subset_is_over_determined_then_reachable_both_directions():
    """prevalence=subset is supplied by the shape anchor (distribution_pattern + fraction_highly_expressed)
    AND by the substantial expressed/high fraction. Single-supply mutations only degrade; defeating
    ALL supplies flips it — and it flips in BOTH directions (→broad if the panel is widened, →rare if
    it is thinned), proving the subset call is genuinely reached, not a fall-through default."""
    s = _epcam_summary()
    assert resolve_expression_properties(s)["prevalence"] == "subset"

    # M4 single-supply: kill the bimodal shape → the substantial high fraction still resolves subset.
    only_pattern = _mutate(s, distribution_pattern="continuous")
    assert resolve_expression_properties(only_pattern)["prevalence"] == "subset"
    # M4 single-supply: zero the high fraction → the substantial expressed fraction still resolves subset.
    only_fh = _mutate(s, fraction_highly_expressed=0.0)
    assert resolve_expression_properties(only_fh)["prevalence"] == "subset"

    # M3 all-supply, widen: defeat shape + high fraction + push expressed fraction broad → broad.
    to_broad = _mutate(s, distribution_pattern="continuous", fraction_highly_expressed=0.0, fraction_expressed=0.85)
    assert resolve_expression_properties(to_broad)["prevalence"] == "broad"
    # M3 all-supply, thin: defeat shape + high fraction + drop expressed fraction → rare.
    to_rare = _mutate(s, distribution_pattern="continuous", fraction_highly_expressed=0.0, fraction_expressed=0.05)
    assert resolve_expression_properties(to_rare)["prevalence"] == "rare"


def test_presence_supported_is_reached_from_the_expressed_fraction():
    """presence=supported for EPCAM is reached from fraction_expressed (the median corroborates but
    is not an independent path at this level) — mutating the fraction down flips it, and defeating
    fraction AND median together confirms there is no hidden third supply. Asserting WHICH: presence
    is fraction-driven here, not over-determined."""
    s = _epcam_summary()
    assert resolve_expression_properties(s)["presence"] == "supported"

    # single-supply: drop the expressed fraction below the majority → no longer supported.
    thin = _mutate(s, fraction_expressed=0.2)
    assert resolve_expression_properties(thin)["presence"] != "supported"

    # all-supply: defeat fraction AND median → weak (detected but thin), still not confabulated as supported.
    both = _mutate(s, fraction_expressed=0.2, median_log2tpm_panel=0.1)
    assert resolve_expression_properties(both)["presence"] == "weak"


# --------------------------------------------------------------------------------------------------
# Gaps → unmeasured (never a zero tier); fleet-deferred always unmeasured.
# --------------------------------------------------------------------------------------------------
def test_data_unavailable_and_empty_resolve_all_unmeasured():
    for summary in (None, {}, {"_no_data": True}, {"expression_class": "data_unavailable"}):
        props = resolve_expression_properties(summary)
        assert set(props) == set(VALID_VALUES)
        assert all(v == "unmeasured" for v in props.values())


def test_fleet_deferred_properties_always_unmeasured():
    for scores in (_EPCAM_SCORES, [7.0] * 40, [0.1] * 40):
        props = resolve_expression_properties(_summary_from_scores(scores))
        for name in ("selectivity", "localization", "subtype_restriction"):
            assert props[name] == "unmeasured"


def test_missing_shape_and_cv_yields_unmeasured_heterogeneity_not_uniform():
    """unmeasured ≠ the measured low end: with NO shape and NO CoV, heterogeneity is a GAP (unmeasured),
    not `uniform` (which is a measured tight distribution)."""
    props = resolve_expression_properties({"fraction_expressed": 0.6})
    assert props["heterogeneity"] == "unmeasured"


# --------------------------------------------------------------------------------------------------
# Cross-repo contract: local VALID_VALUES must match the P1 vocabulary (target-contracts enum).
# Best-effort — skips when the sibling checkout is not reachable (keeps the unit suite hermetic).
# --------------------------------------------------------------------------------------------------
def test_valid_values_match_target_contracts_enum():
    yaml = pytest.importorskip("yaml")
    tc_root = Path(cli.DEFAULT_TARGET_CONTRACTS)
    enum_path = tc_root / "vocabularies" / "expression_property.enum.yaml"
    if not enum_path.exists():
        pytest.skip(f"target-contracts enum not reachable at {enum_path}")
    doc = yaml.safe_load(enum_path.read_text())
    declared = {p["id"]: tuple(v["value"] for v in p["values"]) for p in doc["properties"]}
    assert set(declared) == set(VALID_VALUES), "resolver property set drifted from the P1 vocabulary"
    for prop, values in VALID_VALUES.items():
        assert set(values) == set(declared[prop]), f"{prop}: local tokens {values} != enum {declared[prop]}"
