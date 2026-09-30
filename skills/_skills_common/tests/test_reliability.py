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


# ── powered: tri-state; 'unmeasured' unless n present AND a calibrated floor supplied ─────────────
def test_powered_unmeasured_when_no_floor_even_with_n_present():
    # THE 1a/1b OUTCOME: n is present but no floor exists -> 'unmeasured' (the honest sentinel), NOT true.
    # MUTANT: `powered = True` whenever n present reds this (would be bool True, not the string).
    out = _derive_reliability(
        [_anchor("n_cell_lines_evaluated", 907)], {"n_effective_anchor": "n_cell_lines_evaluated"}
    )
    assert out["powered"] == "unmeasured"
    assert not isinstance(out["powered"], bool)


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


# ── detection_strength: DEFERRED, always OMITTED this step ────────────────────────────────────────
def test_detection_strength_omitted():
    # MUTANT: `out["detection_strength"] = "strong"` reds this — cutpoints uncalibrated, key omitted.
    out = _derive_reliability([_anchor("n_tissues_tested", 30)], {"n_effective_anchor": "n_tissues_tested"})
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
    assert "unmeasured" in powered_tokens  # the sentinel this deriver emits uniformly on 1a/1b
    assert _MICROENVIRONMENT_WEIGHTED in confound_tokens
    assert _FLOOR_TIE_PERCENTILE in artifact_tokens
