"""Hermetic tests for diff_discordance_ledger (the monitored-cadence diff). No network."""
from __future__ import annotations

import sys
from pathlib import Path

_EVAL = Path(__file__).resolve().parents[1]
if str(_EVAL) not in sys.path:
    sys.path.insert(0, str(_EVAL))

import diff_discordance_ledger as dd  # noqa: E402


def _ledger(*rows, counts=None):
    return {"rows": list(rows), "summary": {"by_gap_class": counts or {}}, "corpus_fingerprint": "fp"}


def _row(skill, target, ind, axis, gap="calibration_gap", **extra):
    r = {"skill": skill, "target": target, "indication": ind, "axis_key": axis, "gap_class": gap,
         "n_verified_citations": 2, "claim_signal": "absent"}
    r.update(extra)
    return r


def test_sharp_keys_only_calibration_and_verdict_rule():
    led = _ledger(_row("s", "T", "I", "A", "calibration_gap"),
                  _row("s", "T", "I", "B", "verdict_rule_gap"),
                  _row("s", "T", "I", "C", "blind_spot_gap"))
    assert dd.sharp_keys(led) == {"s|T|I|A|calibration_gap", "s|T|I|B|verdict_rule_gap"}


def test_diff_flags_new_and_resolved():
    base = {"keys": ["s|OLD|I|A|calibration_gap"], "counts": {}}
    led = _ledger(_row("s", "NEW", "I", "A", "calibration_gap"))
    rep = dd.diff(led, base)
    assert rep["n_new"] == 1 and rep["new_sharp_gaps"][0]["target"] == "NEW"
    assert rep["n_resolved"] == 1 and rep["resolved_sharp_gaps"] == ["s|OLD|I|A|calibration_gap"]


def test_diff_quiet_when_matches_baseline():
    row = _row("s", "T", "I", "A", "calibration_gap")
    led = _ledger(row)
    base = dd.baseline_from_ledger(led)
    rep = dd.diff(led, base)
    assert rep["n_new"] == 0 and rep["n_resolved"] == 0


def test_baseline_from_ledger_roundtrips_sharp_keys():
    led = _ledger(_row("s", "T", "I", "A", "calibration_gap"),
                  _row("s", "T", "I", "B", "blind_spot_gap"), counts={"calibration_gap": 1})
    base = dd.baseline_from_ledger(led)
    assert base["keys"] == ["s|T|I|A|calibration_gap"]           # blind_spot excluded from sharp baseline
    assert base["counts"] == {"calibration_gap": 1}


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
