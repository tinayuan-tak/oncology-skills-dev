"""pair_selectivity_gate.gates — AND/OR/NOT pair-selectivity math (pure, no S3, synthetic per-sample).

Pins the ported biologics logic-gate physics + the two disciplines: the AND/NOT coverage gate (a
rare-in-tumor pair scores 0 regardless of ratio) and the Theme-1 dual denominator (a non-essential
normal tissue firing is surfaced, not hidden).
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.pair_selectivity_gate.gates import (  # noqa: E402
    _positive_fraction_by_group, reduce_gate, classify_and_selectivity,
    GATE_POSITIVE_THRESHOLD_TPM, AND_GATE_MIN_COFRACTION, AVIDITY_CAVEAT,
)

HI = GATE_POSITIVE_THRESHOLD_TPM + 5    # clearly positive
LO = 0.0                                # clearly negative


def _grp(*tpms):
    """Build {sample_id: tpm} for one group from a list of values."""
    return {f"s{i}": v for i, v in enumerate(tpms)}


# ── per-sample gate fractions ────────────────────────────────────────────────
def test_and_gate_fraction_needs_both_positive():
    a = {"COAD": _grp(HI, HI, HI, LO)}      # 3/4 A-positive
    b = {"COAD": _grp(HI, HI, LO, LO)}      # A&B positive only in samples 0,1 → 2/4 = 0.5
    frac = _positive_fraction_by_group(a, b, "AND")
    assert frac["COAD"] == 0.5


def test_or_gate_fraction_is_union():
    a = {"COAD": _grp(HI, LO, LO, LO)}
    b = {"COAD": _grp(LO, HI, LO, LO)}      # union = samples 0,1 → 2/4 = 0.5
    assert _positive_fraction_by_group(a, b, "OR")["COAD"] == 0.5


def test_not_gate_requires_veto_truly_absent():
    a = {"COAD": _grp(HI, HI, HI)}          # all A-positive
    # veto B: sample0 high (veto fires, excluded), sample1 mid (>=5 veto threshold, excluded),
    # sample2 truly absent (<5) → only sample2 fires the NOT gate → 1/3
    b = {"COAD": _grp(HI, 6.0, LO)}
    frac = _positive_fraction_by_group(a, b, "NOT")
    assert frac["COAD"] == 1 / 3


def test_groups_missing_an_arm_are_skipped():
    a = {"COAD": _grp(HI, HI), "READ": _grp(HI)}
    b = {"COAD": _grp(HI, HI)}              # READ absent in b → skipped
    frac = _positive_fraction_by_group(a, b, "AND")
    assert "COAD" in frac and "READ" not in frac


# ── reduction: selectivity, coverage gate, Theme-1 ───────────────────────────
def test_and_gate_tumor_selective_call():
    # EPCAM+CEACAM5-like: 100% tumor co-expr, 25% worst essential normal → selective
    tumor = {"COAD": 1.0}
    normal = {"LUNG": 0.25, "COLON": 0.10}
    r = reduce_gate("AND", tumor, normal, "COAD")
    assert r["tumor_fraction"] == 1.0
    assert r["max_essential_normal_tissue"] == "LUNG"
    assert r["selectivity"] == 4.0                       # 1.0 / 0.25
    assert "tumor-selective" in r["call"]


def test_coverage_gate_zeroes_rare_and_pairs():
    # a pair firing in only 3% of tumor with 0% essential-normal must NOT score astronomically —
    # the coverage gate zeroes AND/NOT pairs below AND_GATE_MIN_COFRACTION.
    r = reduce_gate("AND", {"COAD": 0.03}, {"LUNG": 0.0}, "COAD")
    assert r["selectivity"] == 0.0
    assert "too rare in tumor" in r["call"]


def test_resolution_floor_caps_zero_essential_selectivity():
    # 100% tumor, 0% essential → capped at ~1/floor (100x), not infinite from a pseudocount
    r = reduce_gate("AND", {"COAD": 1.0}, {"LUNG": 0.0}, "COAD")
    assert r["selectivity"] == 100.0                      # 1.0 / 0.01 resolution floor


def test_theme1_nonessential_normal_surfaced_in_call():
    # clean vs essential (lung 5%), but SKIN (non-essential) fires 60% → the call must CAUTION,
    # and max_any_normal must expose SKIN even though the essential denominator ignores it.
    tumor = {"COAD": 0.9}
    normal = {"LUNG": 0.05, "SKIN": 0.60}
    r = reduce_gate("AND", tumor, normal, "COAD")
    assert r["max_essential_normal_tissue"] == "LUNG"     # essential denominator: lung
    assert r["max_any_normal_tissue"] == "SKIN"           # full-normal denominator: skin (Theme-1)
    assert r["max_any_normal_fraction"] == 0.6
    assert "non-essential normal" in r["call"]            # broad-tissue liability surfaced


def test_and_gate_dirty_when_essential_also_fires():
    # both antigens co-express in an essential normal tissue too → not selective
    r = reduce_gate("AND", {"COAD": 0.8}, {"LUNG": 0.5}, "COAD")
    assert "also fires in essential normal" in r["call"]


def test_no_tumor_samples_yields_none_selectivity():
    r = reduce_gate("AND", {"READ": 0.9}, {"LUNG": 0.1}, "COAD")   # asked for COAD, only READ present
    assert r["tumor_fraction"] is None
    assert r["selectivity"] is None
    assert "cannot evaluate" in r["call"]


def test_or_gate_keeps_raw_selectivity_no_coverage_gate():
    # OR is a coverage gate — a low fraction is meaningful, so it is NOT zeroed like AND/NOT
    r = reduce_gate("OR", {"COAD": 0.10}, {"LUNG": 0.01}, "COAD")
    assert r["selectivity"] is not None and r["selectivity"] > 0
    assert "heterogeneity backstop" in r["call"]


def test_avidity_caveat_is_nonempty_and_names_same_cell():
    assert "same-CELL" in AVIDITY_CAVEAT and "avidity" in AVIDITY_CAVEAT


def test_classify_and_selectivity_categorical_2026_08_24():
    # rule-matchable companion to the free-text AND call; mirrors _call's {tumor,essential,any} cuts.
    T = AND_GATE_MIN_COFRACTION
    # tumor-selective, clean on essential AND non-essential normal
    assert classify_and_selectivity(0.80, 0.05, 0.05, 16.0) == "selective_and_pair"
    # tumor-selective vs essential, but fires broadly in NON-essential normal (Theme-1)
    assert classify_and_selectivity(0.80, 0.05, T + 0.10, 16.0) == "selective_but_broad_tissue_liability"
    # AND-gate also fires in essential normal → not selective
    assert classify_and_selectivity(0.80, T + 0.10, 0.90, 2.0) == "not_selective"
    # co-expression too rare in tumor (below coverage floor) → low value
    assert classify_and_selectivity(T - 0.10, 0.01, 0.01, 0.0) == "no_selective_pair"
    # no tumor samples / no selectivity → data_unavailable
    assert classify_and_selectivity(None, 0.0, 0.0, None) == "data_unavailable"
