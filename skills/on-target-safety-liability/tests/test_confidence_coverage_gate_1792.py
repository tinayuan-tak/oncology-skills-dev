"""SK#1792 mutation teeth — whole-axis coverage gating on the SURFACED safety confidence.

The defect: `critical_axes=("CONSTRAINT",)` made headline_core's thin-coverage floor
(`n_crit_measured*2 < len(crit)`) unfireable on any measured-CONSTRAINT gene, so a CLEAN
(tolerant_reduced_safety_risk) verdict measured on gnomAD-tolerant ALONE — with the other six legs
(BURDEN/DOSAGE/CLINVAR/MOUSE_KO/PAN_ESSENTIAL/NORMAL_TISSUE) entirely unmeasured — surfaced `strong`
confidence the moment an agreeing s_het arm bumped CONSTRAINT corroboration to `high`. That is the
dangerous direction for a safety skill: a false-negative-prone reassuring call that reads well-supported.
The whole-axis coverage number existed (`_safety_certainty`) but flowed only to the dead
claim_record_shadow, never to the surfaced headline confidence.

The fix broadens `critical_axes` to all 7 legs (every leg can independently drive a concern HOLD), so
<4 measured legs caps the surfaced confidence at `weak` ("capped by thin coverage"). These tests
RED-fail if `critical_axes` is reverted to `("CONSTRAINT",)` — verified by reverting.

Verdict-INERT: only headline_block.confidence moves; the resolver/scalar verdict spine is untouched
(frozen by test_safety_replay.py + the golden-oracle resolver test). No I/O.
"""

from __future__ import annotations

import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
SKILLS_ROOT = SKILL_DIR.parent
if str(SKILLS_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILLS_ROOT))

from _test_support import load_run_py  # noqa: E402 — needs SKILLS_ROOT on sys.path first

_RUN = load_run_py(SKILL_DIR, "_safety_run_conf_1792")

_ALL_AXES = ("CONSTRAINT", "BURDEN", "DOSAGE", "CLINVAR", "MOUSE_KO", "PAN_ESSENTIAL", "NORMAL_TISSUE")


def _headline(claim_vector: dict, verdict: str = "tolerant_reduced_safety_risk") -> dict:
    return {"safety_verdict": verdict, "claim_vector": claim_vector, "key_signals": {}}


def test_all_seven_legs_are_decision_critical():
    """Every safety leg can independently drive a concern HOLD, so all 7 must floor coverage. Reverting
    critical_axes to ("CONSTRAINT",) RED-fails here (and functionally below)."""
    assert tuple(_RUN._SAFETY_HEADLINE_SPEC.critical_axes) == _ALL_AXES


def test_bare_tolerant_constraint_is_coverage_demoted_not_strong():
    """THE motivating cell: only CONSTRAINT measured (tolerant, s_het-corroborated → corroboration
    `high`), all other legs unmeasured, clean verdict. The surfaced confidence must be coverage-demoted
    (weak/insufficient), never strong/moderate. Under the reverted single-critical-axis spec this reads
    `strong` (weakest-link over the one measured axis = high, no floor fires) — RED."""
    cv = {"CONSTRAINT": {"signal": "absent", "corroboration": "high"}}  # measured tolerant, two arms agree
    block = _RUN._build_headline_block(_headline(cv))
    conf = block["confidence"]
    assert conf["level"] in {"weak", "insufficient"}, (
        f"clean verdict on ONE measured leg surfaced {conf['level']!r} — whole-axis coverage gating lost"
    )
    assert "thin coverage" in conf["basis"]
    assert conf["coverage"] == {"n_measured": 1, "n_axes": 7, "n_critical_measured": 1}


def test_two_measured_legs_still_capped():
    """The pattern, not the instance: CONSTRAINT + MOUSE_KO measured (2/7) is still thin coverage —
    the cap must fire on any <4/7-measured reassuring read, not only the single-leg motivating case."""
    cv = {
        "CONSTRAINT": {"signal": "absent", "corroboration": "high"},
        "MOUSE_KO": {"signal": "absent", "corroboration": "single_arm"},
    }
    conf = _RUN._build_headline_block(_headline(cv))["confidence"]
    assert conf["level"] in {"weak", "insufficient"}
    assert "thin coverage" in conf["basis"]


def test_well_covered_gene_is_not_demoted_by_the_floor():
    """No single-target overfit in the conservative direction either: with 5/7 legs measured the floor
    must NOT fire — confidence stays the corroboration-derived weakest-link (here `moderate`)."""
    cv = {
        "CONSTRAINT": {"signal": "strong", "corroboration": "moderate"},
        "BURDEN": {"signal": "strong", "corroboration": "moderate"},
        "DOSAGE": {"signal": "absent", "corroboration": "moderate"},
        "CLINVAR": {"signal": "strong", "corroboration": "moderate"},
        "MOUSE_KO": {"signal": "strong", "corroboration": "moderate"},
    }
    conf = _RUN._build_headline_block(_headline(cv, verdict="highly_constrained_safety_concern"))["confidence"]
    assert conf["level"] == "moderate"
    assert "thin coverage" not in conf["basis"]


def test_nothing_measured_is_insufficient():
    """Conservative fall-through: no leg measured at all → `insufficient`, never a confidence word."""
    conf = _RUN._build_headline_block(_headline({}))["confidence"]
    assert conf["level"] == "insufficient"
