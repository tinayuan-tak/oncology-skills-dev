"""card_warnings — the CEL-subset evaluator (Track C Stage 4). The evaluator feeds user-facing warnings,
so the tests pin the two contracts hard: it evaluates the real operator set correctly, and it returns
None (never a guessed True/False) when a predicate cannot be decided.
"""

from __future__ import annotations

from _skills_common import card_warnings as cw


def test_comparisons_and_literals():
    assert cw.evaluate("fit_class == 'modality_ambiguous'", {"fit_class": "modality_ambiguous"}) is True
    assert cw.evaluate("fit_class == 'modality_ambiguous'", {"fit_class": "adc_favored"}) is False
    assert cw.evaluate("flag == true", {"flag": True}) is True
    assert cw.evaluate("flag != true", {"flag": False}) is True
    assert cw.evaluate("q < 0.05", {"q": 0.01}) is True
    assert cw.evaluate("q < 0.05", {"q": 0.2}) is False
    assert cw.evaluate("n >= 30", {"n": 30}) is True


def test_boolean_ops_and_parens():
    s = {"a": "sensitive", "b": "stable"}
    assert cw.evaluate("a == 'sensitive' || b == 'sensitive'", s) is True
    assert cw.evaluate("a == 'sensitive' && b == 'sensitive'", s) is False
    assert cw.evaluate("!(b == 'sensitive')", s) is True
    assert cw.evaluate("(a == 'sensitive' || b == 'x') && !(a == 'stable')", s) is True


def test_bare_field_is_truthy():
    assert cw.evaluate("flag", {"flag": True}) is True
    assert cw.evaluate("flag", {"flag": False}) is False
    assert cw.evaluate("!flag", {"flag": False}) is True


def test_negative_numbers_and_arithmetic():
    # negative literals (USub) — a wrong flag here would be a real defect
    assert cw.evaluate("z < -3.0 || z > 3.0", {"z": -4.0}) is True
    assert cw.evaluate("delta > -0.08", {"delta": -0.05}) is True
    assert cw.evaluate("delta > -0.08", {"delta": -0.5}) is False
    # arithmetic inside a comparison (BinOp)
    assert cw.evaluate("(hi - lo) > 0.20", {"hi": 0.9, "lo": 0.5}) is True
    assert cw.evaluate("n_a + n_b < 10", {"n_a": 4, "n_b": 3}) is True


def test_threshold_resolution():
    assert cw.evaluate("frac >= THRESHOLD.dom", {"frac": 0.8}, {"dom": 0.6}) is True
    assert cw.evaluate("frac >= THRESHOLD.dom", {"frac": 0.5}, {"dom": 0.6}) is False
    assert cw.evaluate("frac >= THRESHOLD.dom", {"frac": 0.8}, thresholds={}) is None  # missing threshold


def test_string_literal_is_not_operator_translated():
    # an operator-looking token inside a quoted string must survive verbatim
    assert cw.evaluate("label == 'a && b'", {"label": "a && b"}) is True
    assert cw.evaluate("label == 'a && b'", {"label": "a"}) is False


def test_none_when_undecidable_never_a_guess():
    assert cw.evaluate("foo == 'x'", {"bar": 1}) is None  # unknown field
    assert cw.evaluate("x > 'a'", {"x": "b"}) is None  # ordering on non-numeric
    assert cw.evaluate("len(flags) > 0", {"flags": []}) is None  # unsupported call
    assert cw.evaluate("arr.0.v >= 1", {"arr": [{"v": 2}]}) is None  # CEL list index (doesn't parse)
    assert cw.evaluate("", {"x": 1}) is None  # empty
    assert cw.evaluate("x ===", {"x": 1}) is None  # malformed


def test_triage_classifies():
    kf = {"fit_class", "q", "delta"}
    assert cw.triage_predicate("fit_class == 'x'", kf) == (True, "fireable")
    assert cw.triage_predicate("q < -0.05 && delta > 0", kf)[0] is True  # negative numbers are fireable
    fire, reason = cw.triage_predicate("undeclared_field == 'x'", kf)
    assert fire is False and "non-summary field" in reason
    fire, reason = cw.triage_predicate("len(q) > 0", kf)
    assert fire is False and "unsupported construct" in reason
    fire, reason = cw.triage_predicate("arr.0.v >= 1", kf)
    assert fire is False and "does not parse" in reason


# ── Stage-4 inc-2: fired_warnings (loader + calibration) + the dispatcher wiring ──────────────────────

_CID = "adc-tce-modality-fit"


def test_fired_warnings_loads_predicates_and_evaluates():
    # the card's `modality_ambiguous_needs_biology_context` predicate is `fit_class == 'modality_ambiguous'`
    fired = cw.fired_warnings(_CID, {"fit_class": "modality_ambiguous"}, apply_calibration=False)
    assert "modality_ambiguous_needs_biology_context" in fired
    assert cw.fired_warnings(_CID, {"fit_class": "adc_favored"}, apply_calibration=False) == []
    assert cw.fired_warnings("no-such-card", {"x": 1}) == []  # absent card, best-effort


def test_calibration_register_loads_the_committed_suppressed_set():
    reg = cw._load_calibration()
    assert len(reg) >= 50  # the committed register suppresses ~64 non-discriminating pairs
    assert (_CID, "isoform_selective_grades_suppressed") in reg  # a measured 0%-firing pair


def test_calibration_suppresses_a_fired_but_nondiscriminating_warning(monkeypatch):
    cw._load_calibration.cache_clear()
    monkeypatch.setattr(
        cw, "_load_calibration", lambda: frozenset({(_CID, "modality_ambiguous_needs_biology_context")})
    )
    s = {"fit_class": "modality_ambiguous"}
    assert cw.fired_warnings(_CID, s, apply_calibration=True) == []  # suppressed
    assert "modality_ambiguous_needs_biology_context" in cw.fired_warnings(
        _CID, s, apply_calibration=False
    )  # still fires uncalibrated


def test_dispatcher_envelope_wires_validation_state_and_warning_ids():
    from _skills_common.dispatcher import _envelope_card_present

    fired = _envelope_card_present({"card_id": _CID, "summary": {"fit_class": "modality_ambiguous"}})
    assert fired["validation_state"] == "passed_with_warnings"
    assert "modality_ambiguous_needs_biology_context" in fired["warning_ids"]
    clean = _envelope_card_present({"card_id": _CID, "summary": {"fit_class": "adc_favored"}})
    assert clean["validation_state"] == "pass"
    assert "warning_ids" not in clean  # no key when none fire (schema stays clean)
