"""Unit tests for the shared `_derive_reliability` deriver (evidence-property #2306 step 2).

Every field PATH is exercised, including the two SYNTHETIC pilot inputs the facet does not fire on any
1a/1b property but whose logic must still be proven (a purity r <= CONFOUND_R -> microenvironment_weighted;
an n-anchor + a calibrated floor -> powered true/false). Per SK#2091 each assertion must be able to FAIL:
the mutants that red each are named in-line and were run to red during development (see the PR body's
mutation battery). Verdict-inertness is NOT a proof obligation and is not asserted here.
"""

from __future__ import annotations

import sys
from pathlib import Path

# skills/conftest.py puts skills/ on the path; belt-and-suspenders for a direct file invocation.
_HERE = Path(__file__).resolve()
for _p in (_HERE.parents[2], _HERE.parents[1]):  # skills/ , skills/_skills_common/tests/..'s parent
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from _skills_common.reliability import (  # noqa: E402
    _FLOOR_TIE_PERCENTILE,
    _MICROENVIRONMENT_WEIGHTED,
    _derive_reliability,
)


def _anchor(field, value):
    return {"field": field, "value": value, "scale": "raw"}


# ── n_effective: projected from the named anchor; omitted when absent ─────────────────────────────
def test_n_effective_projected_from_named_anchor():
    # MUTANT: `n_eff = by_field.get(n_anchor)` -> `n_eff = None` reds this (key would be omitted).
    out = _derive_reliability(
        [_anchor("n_cell_lines_evaluated", 907)], {"n_effective_anchor": "n_cell_lines_evaluated"}
    )
    assert out["n_effective"] == 907


def test_n_effective_coerced_to_int_not_float():
    # MUTANT: drop `int(...)` -> stores 907.0; `isinstance(..., int)` reds (float is not int).
    out = _derive_reliability([_anchor("n_tissues_tested", 907.0)], {"n_effective_anchor": "n_tissues_tested"})
    assert out["n_effective"] == 907
    assert isinstance(out["n_effective"], int) and not isinstance(out["n_effective"], bool)


def test_n_effective_omitted_when_anchor_value_absent():
    # The anchor the spec names is not in the (filtered) anchor list -> key omitted, powered unmeasured.
    # MUTANT: emit `n_effective = 0` on absence reds "n_effective" not in out; a naive `powered = True`
    # default reds the powered assertion.
    out = _derive_reliability([_anchor("some_other_field", 5)], {"n_effective_anchor": "n_high_confidence"})
    assert "n_effective" not in out
    assert out["powered"] == "unmeasured"


def test_n_effective_omitted_when_spec_anchor_is_none():
    out = _derive_reliability([_anchor("pli_score", 0.99)], {"n_effective_anchor": None})
    assert "n_effective" not in out
    assert out["powered"] == "unmeasured"


def test_bool_anchor_value_is_not_a_count():
    # Defensive: a bool is not an int count -> n_effective omitted.
    out = _derive_reliability([_anchor("n_high_confidence", True)], {"n_effective_anchor": "n_high_confidence"})
    assert "n_effective" not in out


# ── powered: tri-state; 'unmeasured' unless n present AND a floor resolves (explicit or table) ─────
def test_powered_unmeasured_when_no_floor_even_with_n_present():
    # An UNCALIBRATED kind (#2327: n_tissues_tested is a fixed reference panel, deliberately no floor) with
    # n present -> 'unmeasured' (the honest sentinel), NOT true. MUTANT: `powered = True` whenever n present
    # reds this (would be bool True, not the string); a floor invented for this kind also reds.
    out = _derive_reliability([_anchor("n_tissues_tested", 31)], {"n_effective_anchor": "n_tissues_tested"})
    assert out["powered"] == "unmeasured"
    assert not isinstance(out["powered"], bool)


# ── powered via the #2327 calibration TABLE (no explicit floor in the spec) ───────────────────────
def test_powered_true_via_calibration_table_when_n_clears_the_kinds_floor():
    # crispr_essentiality's n_cell_lines_evaluated carries a table floor (PAN_ESSENTIAL_MIN_PANEL_N=300),
    # single-sourced from the method. n=907 clears it -> True with NO explicit powered_floor in the spec.
    # MUTANT: drop the `_powered_floor_for` fallback in reliability.py -> 'unmeasured' reds this.
    out = _derive_reliability(
        [_anchor("n_cell_lines_evaluated", 907)], {"n_effective_anchor": "n_cell_lines_evaluated"}
    )
    assert out["powered"] is True


def test_powered_false_via_calibration_table_when_n_below_the_kinds_floor():
    # partner_conditional_dependency's n_partner_deficient carries a table floor (MIN_PARTNER_DEFICIENT_CELLS=5).
    # n=3 is a MEASURED underpowered read -> False (a real statement), distinct from 'unmeasured'.
    # MUTANT: fallback removed -> 'unmeasured' reds `is False`.
    out = _derive_reliability([_anchor("n_partner_deficient", 3)], {"n_effective_anchor": "n_partner_deficient"})
    assert out["powered"] is False


def test_explicit_spec_floor_wins_over_the_calibration_table():
    # An explicit powered_floor in the spec takes precedence over the kind's table floor. n_partner_deficient
    # table floor is 5, but an explicit floor of 100 makes n=50 read False. MUTANT: consulting the table
    # first (ignoring the explicit floor) would read True (50>=5) and red this.
    out = _derive_reliability(
        [_anchor("n_partner_deficient", 50)],
        {"n_effective_anchor": "n_partner_deficient", "powered_floor": 100},
    )
    assert out["powered"] is False


def test_powered_true_when_n_clears_supplied_floor():
    # SYNTHETIC pilot: proves the boolean powered path though no 1a/1b property supplies a floor today.
    # MUTANT: force 'unmeasured' reds; MUTANT: `>=` -> `<` reds (12 >= 10 would flip to False).
    out = _derive_reliability(
        [_anchor("n_paralogs_annotated", 12)],
        {"n_effective_anchor": "n_paralogs_annotated", "powered_floor": 10},
    )
    assert out["powered"] is True


def test_powered_false_when_n_below_supplied_floor():
    # A MEASURED underpowered read is `false` (a real statement), distinct from the `unmeasured` sentinel.
    # MUTANT: collapse false -> 'unmeasured' reds `is False`.
    out = _derive_reliability(
        [_anchor("n_partner_deficient", 3)],
        {"n_effective_anchor": "n_partner_deficient", "powered_floor": 10},
    )
    assert out["powered"] is False


def test_powered_unmeasured_when_floor_supplied_but_n_absent():
    # A floor without an n is still 'unmeasured' — absence outranks a naive read.
    out = _derive_reliability([], {"n_effective_anchor": "n_high_confidence", "powered_floor": 10})
    assert out["powered"] == "unmeasured"
    assert "n_effective" not in out


# ── confound_flags: default []; microenvironment_weighted iff a purity r <= CONFOUND_R ────────────
def test_confound_microenvironment_weighted_when_purity_r_below_cut():
    # SYNTHETIC pilot (CD274-style r=-0.39, does not occur on any 1a/1b anchor). MUTANT: never append
    # reds; MUTANT: `<=` -> `>=` reds (-0.39 >= -0.3 is False -> no flag).
    out = _derive_reliability(
        [_anchor("expression_purity_r", -0.39)],
        {"n_effective_anchor": None, "purity_confound_anchor": "expression_purity_r"},
    )
    assert out["confound_flags"] == [_MICROENVIRONMENT_WEIGHTED]


def test_confound_empty_when_purity_r_above_cut():
    # The boundary: r just above the cut does NOT flag. MUTANT: append unconditionally reds this.
    out = _derive_reliability(
        [_anchor("expression_purity_r", -0.2)],
        {"n_effective_anchor": None, "purity_confound_anchor": "expression_purity_r"},
    )
    assert out["confound_flags"] == []


def test_confound_empty_when_spec_names_no_purity_anchor():
    # THE 1a/1b PATH: no spec purity anchor -> [] even though a numeric anchor is present.
    out = _derive_reliability(
        [_anchor("n_cell_lines_evaluated", 907), _anchor("median_chronos_panel", -0.8)],
        {"n_effective_anchor": "n_cell_lines_evaluated"},
    )
    assert out["confound_flags"] == []


# ── artifact_flags: default []; floor_tie_percentile iff a floor_tie_anchor is present AND truthy ──
def test_artifact_flags_default_empty():
    # THE 1a/1b PATH: no spec floor_tie_anchor -> [] even with an unrelated numeric anchor present.
    out = _derive_reliability([_anchor("n_high_confidence", 4)], {"n_effective_anchor": "n_high_confidence"})
    assert out["artifact_flags"] == []


def test_artifact_flags_floor_tie_percentile_when_upstream_flag_true():
    # SYNTHETIC pilot (#2297/#2328): proves the floor-tie projection path though no 1a/1b property
    # names a floor_tie_anchor today. MUTANT: never append reds this.
    out = _derive_reliability(
        [_anchor("allgene_percentile_is_floor_tie", True)],
        {"n_effective_anchor": None, "floor_tie_anchor": "allgene_percentile_is_floor_tie"},
    )
    assert out["artifact_flags"] == [_FLOOR_TIE_PERCENTILE]


def test_artifact_flags_empty_when_upstream_flag_false():
    # MUTANT: append unconditionally (ignoring the anchor's value) reds this.
    out = _derive_reliability(
        [_anchor("allgene_percentile_is_floor_tie", False)],
        {"n_effective_anchor": None, "floor_tie_anchor": "allgene_percentile_is_floor_tie"},
    )
    assert out["artifact_flags"] == []


def test_artifact_flags_empty_when_spec_names_no_floor_tie_anchor():
    # A truthy same-named field is present in anchors, but the spec doesn't name it -> [] (the
    # projection is opt-in per property, exactly like purity_confound_anchor above).
    out = _derive_reliability(
        [_anchor("allgene_percentile_is_floor_tie", True), _anchor("n_high_confidence", 4)],
        {"n_effective_anchor": "n_high_confidence"},
    )
    assert out["artifact_flags"] == []


def test_artifact_flags_floor_tie_omitted_when_named_anchor_absent():
    # The spec names a floor_tie_anchor but no anchor with that field is in the (filtered) list ->
    # by_field.get(...) is None -> not truthy -> [] (absence, not a fabricated flag either way).
    out = _derive_reliability(
        [_anchor("some_other_field", True)],
        {"n_effective_anchor": None, "floor_tie_anchor": "allgene_percentile_is_floor_tie"},
    )
    assert out["artifact_flags"] == []


# ── detection_strength: OPTIONAL; emitted only when the spec names a calibrated scheme (#2329) ────
def test_detection_strength_omitted_when_spec_names_no_scheme():
    # THE 1a/1b PATH: no detection_strength_scheme -> key OMITTED (byte-stable) even with anchors present.
    # MUTANT: `out["detection_strength"] = "strong"` on no scheme reds this.
    out = _derive_reliability([_anchor("n_tissues_tested", 30)], {"n_effective_anchor": "n_tissues_tested"})
    assert "detection_strength" not in out


def test_detection_strength_ihc_low_is_weak_the_cd274_exemplar():
    # The canonical #2306 case: CD274 IHC (n_high=1,n_medium=1,n_not_detected=10 of 12 -> fraction 0.167
    # -> ihc_detected_low). The deriver PROJECTS the upstream protein_presence_class token -> weak.
    # MUTANT: map ihc_detected_low -> moderate/strong (or drop it) reds this.
    out = _derive_reliability(
        [_anchor("protein_presence_class", "ihc_detected_low")],
        {
            "detection_strength_scheme": "ihc_protein_presence_class",
            "detection_strength_anchor": "protein_presence_class",
        },
    )
    assert out["detection_strength"] == "weak"


def test_detection_strength_ihc_high_and_moderate():
    # MUTANT: swap the high/moderate mapping reds one of these.
    hi = _derive_reliability(
        [_anchor("protein_presence_class", "ihc_detected_high")],
        {
            "detection_strength_scheme": "ihc_protein_presence_class",
            "detection_strength_anchor": "protein_presence_class",
        },
    )
    mod = _derive_reliability(
        [_anchor("protein_presence_class", "ihc_detected_moderate")],
        {
            "detection_strength_scheme": "ihc_protein_presence_class",
            "detection_strength_anchor": "protein_presence_class",
        },
    )
    assert hi["detection_strength"] == "strong"
    assert mod["detection_strength"] == "moderate"


def test_detection_strength_ihc_not_detected_omits_the_key():
    # A MEASURED zero-detection read has nothing to grade -> key OMITTED, never a fabricated "weak".
    # MUTANT: mapping ihc_not_detected -> weak reds this.
    out = _derive_reliability(
        [_anchor("protein_presence_class", "ihc_not_detected")],
        {
            "detection_strength_scheme": "ihc_protein_presence_class",
            "detection_strength_anchor": "protein_presence_class",
        },
    )
    assert "detection_strength" not in out


def test_detection_strength_sc_fraction_bins_strong_moderate_weak():
    # Single-cell malignant detection fraction, binned at the sc method's OWN cuts (0.5 / 0.10 / 0.05).
    # MUTANT: shift any cut (>= -> >, or a wrong constant) reds one of these three.
    def _sc(frac):
        return _derive_reliability(
            [_anchor("malignant_detection_fraction", frac)],
            {
                "detection_strength_scheme": "sc_malignant_detection_fraction",
                "detection_strength_anchor": "malignant_detection_fraction",
            },
        )

    assert _sc(0.76)["detection_strength"] == "strong"  # ceacam5-style broadly detected
    assert _sc(0.156)["detection_strength"] == "moderate"  # apc-style subset detected
    assert _sc(0.07)["detection_strength"] == "weak"  # low but above the undetected floor


def test_detection_strength_sc_below_floor_omits_the_key():
    # <= BROADLY_LOW_MAX (0.05) == effectively undetected -> key OMITTED. MUTANT: emit "weak" reds this.
    out = _derive_reliability(
        [_anchor("malignant_detection_fraction", 0.03)],
        {
            "detection_strength_scheme": "sc_malignant_detection_fraction",
            "detection_strength_anchor": "malignant_detection_fraction",
        },
    )
    assert "detection_strength" not in out


def test_detection_strength_surface_density_band():
    # Surface copies/cell, classified by the surface method's OWN _classify (100/1000/10000).
    # MUTANT: map the very_low band to weak (instead of OMIT) reds the last assertion.
    def _surf(value):
        return _derive_reliability(
            [_anchor("absolute_density_copies_per_cell", value)],
            {
                "detection_strength_scheme": "surface_absolute_density",
                "detection_strength_anchor": "absolute_density_copies_per_cell",
            },
        )

    assert _surf(50000)["detection_strength"] == "strong"  # > 10000
    assert _surf(5000)["detection_strength"] == "moderate"  # [1000, 10000]
    assert _surf(500)["detection_strength"] == "weak"  # [100, 1000)
    assert "detection_strength" not in _surf(50)  # very_low -> OMIT


def test_detection_strength_omitted_when_anchor_absent_though_scheme_named():
    # The spec names a scheme but no anchor with that field is in the list -> value None -> OMIT
    # (honest_degradation, never a fabricated strength). MUTANT: emit on a None datum reds this.
    out = _derive_reliability(
        [_anchor("some_other_field", "ihc_detected_high")],
        {
            "detection_strength_scheme": "ihc_protein_presence_class",
            "detection_strength_anchor": "protein_presence_class",
        },
    )
    assert "detection_strength" not in out


def test_detection_strength_omitted_for_unknown_scheme():
    # A scheme string the calibration does not know -> None -> OMIT (never a crash).
    out = _derive_reliability(
        [_anchor("protein_presence_class", "ihc_detected_high")],
        {"detection_strength_scheme": "not_a_real_scheme", "detection_strength_anchor": "protein_presence_class"},
    )
    assert "detection_strength" not in out


# ── required fields always present on an empty-anchor input ───────────────────────────────────────
def test_required_fields_always_present_on_empty_input():
    # The empty-anchor / no-n-anchor path: powered/confound/artifact are the three required fields and
    # nothing else is invented (no n_effective, no detection_strength).
    out = _derive_reliability([], {"n_effective_anchor": None})
    assert set(out) == {"powered", "confound_flags", "artifact_flags"}
    assert out == {"powered": "unmeasured", "confound_flags": [], "artifact_flags": []}


def test_emitted_tokens_are_governed():
    # Cross-check the only tokens this deriver can emit against reliability.enum.yaml's governed rosters,
    # so a drift in either the deriver or the enum reds. Reads the enum from contracts/.
    import yaml

    enum_path = _HERE.parents[3] / "contracts" / "vocabularies" / "reliability.enum.yaml"
    enum = yaml.safe_load(enum_path.read_text())
    by_field = {f["field"]: f for f in enum["fields"]}
    powered_tokens = {t["token"] for t in by_field["powered"]["tokens"]}
    confound_tokens = {t["token"] for t in by_field["confound_flags"]["tokens"]}
    artifact_tokens = {t["token"] for t in by_field["artifact_flags"]["tokens"]}
    detection_tokens = {t["token"] for t in by_field["detection_strength"]["tokens"]}
    assert "unmeasured" in powered_tokens  # the sentinel this deriver emits uniformly on 1a/1b
    assert _MICROENVIRONMENT_WEIGHTED in confound_tokens
    assert _FLOOR_TIE_PERCENTILE in artifact_tokens
    # every detection_strength value the calibration can emit is a governed enum token (drift in either
    # the calibration ordinal or the enum reds).
    from onc_methods.reliability_calibration.detection_strength import MODERATE, STRONG, WEAK

    assert {WEAK, MODERATE, STRONG} <= detection_tokens
