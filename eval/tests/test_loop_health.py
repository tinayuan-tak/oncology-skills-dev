"""Hermetic tests for loop_health (the discordance-loop precision instrument). No network."""
from __future__ import annotations

import sys
from pathlib import Path

_EVAL = Path(__file__).resolve().parents[1]
if str(_EVAL) not in sys.path:
    sys.path.insert(0, str(_EVAL))

import loop_health as lh  # noqa: E402


def test_compute_precision_math():
    disp = {
        "a|T|I|X|calibration_gap": "fixed",
        "b|T|I|X|calibration_gap": "fixed",
        "c|T|I|X|calibration_gap": "real_deferred",
        "d|T|I|X|calibration_gap": "dismissed_scope",
        "e|T|I|X|calibration_gap": "dismissed_concordant",
        "f|T|I|X|calibration_gap": "dismissed_data_absent",
    }
    m = lh.compute(disp)
    assert m["n_sharp"] == 6
    assert m["precision_strict"] == round(3 / 6, 3)          # fixed(2)+real_deferred(1)
    assert m["precision_incl_scope"] == round(4 / 6, 3)       # + scope(1)
    assert m["noise_rate"] == round(2 / 6, 3)                 # concordant(1)+data_absent(1)
    assert m["unknown_disposition"] == []


def test_unknown_disposition_flagged():
    m = lh.compute({"a|T|I|X|calibration_gap": "banana"})
    assert m["unknown_disposition"] == ["banana"]


def test_by_skill_grouping():
    m = lh.compute({"skillA|T|I|X|calibration_gap": "fixed",
                    "skillA|U|I|Y|calibration_gap": "dismissed_concordant",
                    "skillB|V|I|Z|calibration_gap": "fixed"})
    assert m["by_skill"]["skillA"] == {"fixed": 1, "dismissed_concordant": 1}
    assert m["by_skill"]["skillB"] == {"fixed": 1}


def test_committed_dispositions_load_and_are_all_known():
    """The shipped loop_dispositions.yaml must parse and use only known disposition tokens."""
    disp = lh.load_dispositions(_EVAL / "loop_dispositions.yaml")
    assert len(disp) == 32
    m = lh.compute(disp)
    assert m["unknown_disposition"] == []
    assert m["n_sharp"] == 32


def test_render_md_contains_governance_and_precision():
    md = lh.render_md(lh.compute({"a|T|I|X|calibration_gap": "fixed"}))
    assert "precision_strict" in md and "NO-GO stands" in md and "citable_in_nominations: false" in md
