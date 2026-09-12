"""Hermetic tests for diff_discordance_ledger (the monitored-cadence diff). No network."""

from __future__ import annotations

import sys
from pathlib import Path

_EVAL = Path(__file__).resolve().parents[1]
if str(_EVAL) not in sys.path:
    sys.path.insert(0, str(_EVAL))

import diff_discordance_ledger as dd  # noqa: E402


def _ledger(*rows, counts=None, covered=None):
    """`covered` = the (skill,target,indication) triples the run examined. Omit it to simulate a
    pre-v2.1 ledger (the rows-derived conservative fallback)."""
    led = {"rows": list(rows), "summary": {"by_gap_class": counts or {}}, "corpus_fingerprint": "fp"}
    if covered is not None:
        led["covered"] = [list(t) for t in covered]
    return led


def _row(skill, target, ind, axis, gap="calibration_gap", **extra):
    r = {
        "skill": skill,
        "target": target,
        "indication": ind,
        "axis_key": axis,
        "gap_class": gap,
        "n_verified_citations": 2,
        "claim_signal": "absent",
    }
    r.update(extra)
    return r


def test_sharp_keys_only_calibration_and_verdict_rule():
    led = _ledger(
        _row("s", "T", "I", "A", "calibration_gap"),
        _row("s", "T", "I", "B", "verdict_rule_gap"),
        _row("s", "T", "I", "C", "blind_spot_gap"),
    )
    assert dd.sharp_keys(led) == {"s|T|I|A|calibration_gap", "s|T|I|B|verdict_rule_gap"}


def test_diff_flags_new_and_resolved():
    """RESOLVED requires the run to have RE-EXAMINED the pair — here OLD/I is in `covered` but no
    longer fires, which is the only situation that licenses the word."""
    base = {"keys": ["s|OLD|I|A|calibration_gap"], "counts": {}}
    led = _ledger(_row("s", "NEW", "I", "A", "calibration_gap"), covered=[("s", "NEW", "I"), ("s", "OLD", "I")])
    rep = dd.diff(led, base)
    assert rep["n_new"] == 1 and rep["new_sharp_gaps"][0]["target"] == "NEW"
    assert rep["n_resolved"] == 1 and rep["resolved_sharp_gaps"] == ["s|OLD|I|A|calibration_gap"]
    assert rep["n_uncovered"] == 0 and rep["scope"]["baseline_fully_covered"] is True


def test_a_scoped_run_reports_out_of_scope_baseline_keys_as_UNCOVERED_not_resolved():
    """THE SCOPE-GUARD REGRESSION (2026-09-12). The 20-pair functional-requirement panel diffed
    against the 7-skill baseline used to report all 33 baseline keys RESOLVED — 28 from skills the
    ledger never ran. A key the run did not re-examine is silent, not fixed."""
    base = {
        "keys": [
            "functional-requirement|PARP1|OV|COND|calibration_gap",  # FR, but not in this panel
            "tractability-small-molecule|X|I|LIG|calibration_gap",  # a skill this run never touched
        ],
        "counts": {},
    }
    led = _ledger(
        _row("functional-requirement", "PARP1", "BRCA", "COND", "calibration_gap"),
        covered=[("functional-requirement", "PARP1", "BRCA")],
    )
    rep = dd.diff(led, base)
    assert rep["n_resolved"] == 0, "a run that never examined the pair cannot resolve it"
    assert rep["n_uncovered"] == 2
    assert rep["scope"] == {"n_covered_pairs": 1, "source": "covered", "baseline_fully_covered": False}
    assert rep["n_new"] == 1  # PARP1/BRCA is genuinely new


def test_missing_covered_field_falls_back_conservatively():
    """A pre-v2.1 ledger has no `covered`, so scope is derived from ROWS. A concordant pair emits no
    row, so it reads as uncovered — under-reporting a fix rather than inventing one."""
    base = {"keys": ["s|CLEAN|I|A|calibration_gap"], "counts": {}}
    led = _ledger(_row("s", "OTHER", "I", "A", "calibration_gap"))  # no covered= → fallback
    rep = dd.diff(led, base)
    assert rep["scope"]["source"] == "rows_fallback"
    assert rep["n_resolved"] == 0 and rep["uncovered_baseline_gaps"] == ["s|CLEAN|I|A|calibration_gap"]


def test_diff_quiet_when_matches_baseline():
    row = _row("s", "T", "I", "A", "calibration_gap")
    led = _ledger(row, covered=[("s", "T", "I")])
    base = dd.baseline_from_ledger(led)
    rep = dd.diff(led, base)
    assert rep["n_new"] == 0 and rep["n_resolved"] == 0 and rep["n_uncovered"] == 0
    assert rep["coarse_count_delta_comparable"] is True  # same scope → the count trend is meaningful


def test_count_delta_marked_incomparable_across_a_scope_change():
    base = dd.baseline_from_ledger(
        _ledger(_row("s", "T", "I", "A"), _row("s", "U", "I", "A"), covered=[("s", "T", "I"), ("s", "U", "I")])
    )
    narrower = _ledger(_row("s", "T", "I", "A"), covered=[("s", "T", "I")])
    assert dd.diff(narrower, base)["coarse_count_delta_comparable"] is False


def test_baseline_from_ledger_roundtrips_sharp_keys():
    led = _ledger(
        _row("s", "T", "I", "A", "calibration_gap"),
        _row("s", "T", "I", "B", "blind_spot_gap"),
        counts={"calibration_gap": 1},
        covered=[("s", "T", "I")],
    )
    base = dd.baseline_from_ledger(led)
    assert base["keys"] == ["s|T|I|A|calibration_gap"]  # blind_spot excluded from sharp baseline
    assert base["counts"] == {"calibration_gap": 1}
    assert base["scope"] == [["s", "T", "I"]]


def test_write_baseline_merges_by_default_and_replaces_only_on_demand():
    """A scoped --write-baseline must not delete the reviewed keys of pairs it never looked at."""
    prior = {"keys": ["other-skill|X|I|A|calibration_gap", "s|T|I|A|calibration_gap"], "counts": {}}
    # this run re-examined s/T/I and found the gap gone; it never looked at other-skill/X/I
    led = _ledger(covered=[("s", "T", "I")])
    merged = dd.baseline_from_ledger(led, prior)
    assert merged["keys"] == ["other-skill|X|I|A|calibration_gap"]
    assert merged["n_carried_forward_out_of_scope"] == 1
    assert "counts_note" in merged  # counts describe only the covered pair, and say so
    # explicit replace throws the out-of-scope key away
    assert dd.baseline_from_ledger(led, None)["keys"] == []


def test_replace_baseline_requires_write_baseline(tmp_path):
    import json

    import pytest

    (tmp_path / "l.json").write_text(json.dumps(_ledger(covered=[("s", "T", "I")])))
    (tmp_path / "b.json").write_text(json.dumps({"keys": [], "counts": {}}))
    with pytest.raises(SystemExit):
        dd.main(["--ledger", str(tmp_path / "l.json"), "--baseline", str(tmp_path / "b.json"), "--replace-baseline"])


def test_fail_on_new_exit_code(tmp_path, capsys):
    import json

    led = _ledger(_row("s", "NEW", "I", "A"))
    (tmp_path / "l.json").write_text(json.dumps(led))
    (tmp_path / "b.json").write_text(json.dumps({"keys": [], "counts": {}}))
    rc = dd.main(["--ledger", str(tmp_path / "l.json"), "--baseline", str(tmp_path / "b.json"), "--fail-on-new"])
    assert rc == 1
    # without --fail-on-new the same NEW gap is reported but does not fail
    rc2 = dd.main(["--ledger", str(tmp_path / "l.json"), "--baseline", str(tmp_path / "b.json")])
    assert rc2 == 0
