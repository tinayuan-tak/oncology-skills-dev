"""W1c: the sc-normal named-organ liability is de-anonymized into the headline/tension.

The safety-essential veto used to surface an anonymous flag; analysis-methods #572 emits the NAMED
essential-cell driver, and run.py now builds a masking-safe `sc_normal_liability_detail` string and
interpolates it into the tension text — including the case where a coarser window KILL wins the
verdict LABEL but the sc-normal arm ALSO flagged a named critical organ (the masking fix)."""

from __future__ import annotations

from pathlib import Path

import pytest
from _test_support import load_run_py

ts = load_run_py(Path(__file__).resolve().parent.parent, "ts_run_w1c")


def _sc(cls, cell="kidney proximal tubule cell", tissue="kidney", n_atlas=3):
    """A W1c-era record: organ + cell + atlas count, and NO magnitude fields.

    This fixture predates the W3c severity axis, so it is also — incidentally but usefully — the
    exact shape of a liability that FIRED and cannot be graded. That is why the two naming tests
    below now read "severity ungraded": see `test_absent_grading_fields_grade_ungraded_rather_
    than_a_manufactured_low` for the deliberate version. Live records from AM #665 always carry all
    three magnitude fields, so this shape is reached only by the absent-data path.
    """
    return {
        "sc_normal_safety_essential_class": cls,
        "sc_normal_essential_max_cell_type": cell,
        "sc_normal_essential_max_tissue": tissue,
        "sc_normal_essential_n_datasets_reliable": n_atlas,
    }


def test_liability_detail_names_organ_cell_and_atlases():
    d = ts._sc_normal_liability_detail(_sc("critical_organ_liability"))
    # This assertion previously read
    #     assert d == "kidney kidney proximal tubule cell (3 atlases)"
    # i.e. a fired critical-organ liability whose magnitude fields are absent printed NO severity at
    # all, because the grader returned `None` and the caller's `if sev:` dropped the annotation. The
    # string was therefore INDISTINGUISHABLE from one whose severity had been considered and found
    # unremarkable. Absent evidence now reads as absent evidence.
    assert d == "kidney kidney proximal tubule cell (3 atlases, severity ungraded)"


def test_liability_detail_origin_tissue_also_named():
    d = ts._sc_normal_liability_detail(_sc("origin_tissue_liability", cell="pneumocyte", tissue="lung", n_atlas=1))
    # Previously `assert d == "lung pneumocyte (1 atlas)"`. The origin-tissue arm gets the same
    # treatment as the critical-organ arm on purpose — both are FIRED classes, so neither may go
    # quiet about a grade it could not compute.
    assert d == "lung pneumocyte (1 atlas, severity ungraded)"


def test_liability_detail_none_when_no_essential_hit():
    assert ts._sc_normal_liability_detail(_sc("none")) is None
    assert ts._sc_normal_liability_detail(_sc("data_unavailable")) is None
    assert (
        ts._sc_normal_liability_detail(
            {"sc_normal_safety_essential_class": "critical_organ_liability", "sc_normal_essential_max_cell_type": None}
        )
        is None
    )
    assert ts._sc_normal_liability_detail({}) is None


def test_tension_names_organ_for_preserving_liability():
    hl = {
        "selectivity_class": "selective_with_normal_liability",
        "sc_normal_liability_detail": "kidney kidney proximal tubule cell (3 atlases)",
    }
    t = ts._selectivity_tension_extra(hl)
    assert "kidney proximal tubule cell" in t["text"]
    assert t["severity"] == 3


def test_masking_fix_surfaces_named_liability_under_window_kill():
    """When the window KILL wins the label, a co-fired sc-normal named liability is NOT discarded."""
    hl = {
        "selectivity_class": "selective_but_broadly_normal",
        "sc_normal_liability_detail": "kidney kidney proximal tubule cell (3 atlases)",
    }
    t = ts._selectivity_tension_extra(hl)
    assert "also flags a critical-organ single-cell liability" in t["text"]
    assert "kidney proximal tubule cell" in t["text"]
    assert t["severity"] == 4  # the KILL still owns the slot


def test_masking_fix_noop_when_no_sc_normal_liability():
    hl = {"selectivity_class": "selective_but_broadly_normal", "sc_normal_liability_detail": None}
    t = ts._selectivity_tension_extra(hl)
    assert "also flags" not in t["text"]


# ── W3c: severity grade + data_unavailable "unknown-mass" caveat ────────────────────────────────


def _scg(cls, det, frac, n_ds, cell="type B pancreatic cell", tissue="pancreas"):
    return {
        "sc_normal_safety_essential_class": cls,
        "sc_normal_essential_max_cell_type": cell,
        "sc_normal_essential_max_tissue": tissue,
        "sc_normal_essential_n_datasets_reliable": n_ds,
        "sc_normal_essential_max_detection_fraction": det,
        "sc_normal_essential_donor_fraction": frac,
    }


def test_severity_grades_by_magnitude_consistency_replication():
    # robust: high detection + consistent + multi-atlas (INS β-cell 1.0 / 11 atlases class)
    assert ts._sc_normal_essential_severity(_scg("critical_organ_liability", 1.0, 0.98, 11)) == "high_severity"
    # SINGLE-ATLAS → low_CONFIDENCE, and the rename is the point. This assertion previously read
    #     assert ts._sc_normal_essential_severity(_scg("critical_organ_liability", 0.85, 0.9, 1)) == "low_severity"
    # under the comment "marginal: single-atlas → low regardless of detection". det 0.85 at donor 0.90 is
    # not MARGINAL — it is UNREPLICATED. `low_severity` asserted a magnitude the data does not license;
    # the licensed claim is about our confidence, not the liability's size.
    assert ts._sc_normal_essential_severity(_scg("critical_organ_liability", 0.85, 0.9, 1)) == "low_confidence"
    # sub-0.30 detection → low_confidence (was `"low_severity"`)
    assert ts._sc_normal_essential_severity(_scg("critical_organ_liability", 0.22, 0.8, 4)) == "low_confidence"
    # in-between → moderate (e.g. det 0.41 pneumocyte, replicated across 3 atlases — under the
    # replication-dominant floor of 15, so the new rung must NOT reach it)
    assert ts._sc_normal_essential_severity(_scg("critical_organ_liability", 0.41, 0.75, 3)) == "moderate_severity"
    # `None` is now reserved for "no essential hit fired" ALONE.
    assert ts._sc_normal_essential_severity(_sc("none")) is None
    # A FIRED hit with no magnitude field is `ungraded`, NOT None. This assertion previously read
    #     assert ts._sc_normal_essential_severity(_sc("critical_organ_liability")) is None  # no det field
    # which CONFLATED "nothing to grade" with "a critical-organ liability fired and we could not grade
    # it" — and because the caller does `if sev:`, the second case silently dropped the severity
    # annotation entirely, so a liability with absent evidence displayed as LESS alarming than a graded
    # one. The method has always called this `ungraded` and deliberately ranks it ABOVE `moderate`.
    assert ts._sc_normal_essential_severity(_sc("critical_organ_liability")) == "ungraded"


def test_liability_detail_appends_severity_when_graded():
    d = ts._sc_normal_liability_detail(_scg("critical_organ_liability", 1.0, 0.98, 11))
    assert d == "pancreas type B pancreatic cell (11 atlases, high-severity)"
    # SINGLE-ATLAS reads "low-confidence" in the string a reviewer actually sees. This assertion
    # previously read
    #     assert d2 == "lung acinar cell (1 atlas, low-severity)"
    # i.e. the shipped output described a det-0.85 / donor-0.90 hit as LOW-SEVERITY. Renaming the token
    # alone would NOT have fixed it: the old read-out was f"{sev.split('_')[0]}-severity", which prints
    # "low-severity" for `low_confidence` too. That is the AM #665 shape — a corrected grade that never
    # reaches the name displayed beside it — which is why the read-out is now an explicit map.
    d2 = ts._sc_normal_liability_detail(
        _scg("critical_organ_liability", 0.85, 0.9, 1, cell="acinar cell", tissue="lung")
    )
    assert d2 == "lung acinar cell (1 atlas, low-confidence)"


def test_unassessed_caveat_fires_on_selective_call_with_no_sc_normal_data():
    hl = {
        "selectivity_class": "strong_tumor_selective",
        "sc_normal_safety_essential_class": "data_unavailable",
        "sc_normal_liability_detail": None,
    }
    t = ts._selectivity_tension_extra(hl)
    assert t is not None and t["source"] == "sc_normal_unassessed"
    assert "UNASSESSED" in t["text"] and t["severity"] == 2


def test_unassessed_caveat_silent_when_sc_normal_measured_or_veto_won():
    # sc-normal measured (none) → no unassessed caveat, clean selective call has no tension
    assert (
        ts._selectivity_tension_extra(
            {
                "selectivity_class": "strong_tumor_selective",
                "sc_normal_safety_essential_class": "none",
                "sc_normal_liability_detail": None,
            }
        )
        is None
    )
    # a veto already downgraded → the veto tension owns the slot, not the unassessed caveat
    t = ts._selectivity_tension_extra(
        {
            "selectivity_class": "selective_but_broadly_normal",
            "sc_normal_safety_essential_class": "data_unavailable",
            "sc_normal_liability_detail": None,
        }
    )
    assert t["source"] == "normal_breadth_veto"


# ── The severity ladder must not drift from analysis-methods (2026-09-18) ────────────────────────────
#
# WHY THESE EXIST. `_sc_normal_essential_severity` is a hand-copy of `_essential_severity` in
# analysis-methods `methods/sc_normal_expression/stats.py`, and it CANNOT be an import: skills CI checks
# analysis-methods out at a pinned SHA (0006164e, 2026-09-14) that PREDATES the function (AM #647,
# fe65660), so the import would raise ImportError in CI while passing locally off the editable path dep.
# That same pin is why the copy silently rotted: any CI test comparing the two ladders compares against a
# tree where one of them is absent. Measured on 2026-09-18 by a differential grid, the copy had drifted in
# FOUR independent ways at once and disagreed on 394 of 616 cells.
#
# So the guard is split in two, deliberately:
#   * `test_ladder_cutoffs_are_the_values_the_method_declares` is UNCONDITIONAL and self-contained. It
#     runs in CI. It cannot notice the method MOVING, only this copy moving.
#   * `test_severity_ladder_agrees_with_the_method_cell_for_cell` reads the method and therefore runs
#     LOCALLY and SKIPS IN CI, with the pin named in the skip reason. A skip that is predicted, named and
#     reconciled is not a silent skip — but it is the reason the unconditional test above is not optional.

_DETS = [None, 0.10, 0.29, 0.30, 0.39, 0.40, 0.45, 0.49, 0.50, 0.75, 1.00]
_FRACS = [None, 0.00, 0.50, 0.69, 0.70, 0.88, 1.00]
_NDSS = [None, 0, 1, 2, 5, 14, 15, 26]


def test_ladder_cutoffs_are_the_values_the_method_declares():
    """The five cutoffs, pinned as literals so this copy cannot drift unnoticed in CI.

    Values are those of analysis-methods `stats.py` at b95a8b6 (HIGH_LIABILITY_DET_THRESHOLD,
    HIGH_LIABILITY_DONOR_FRACTION, the 0.30 low line, REPLICATION_DOMINANT_DET_FLOOR,
    REPLICATION_DOMINANT_N_DATASETS). The names match the method's on purpose, so one grep finds every
    home of a cutoff.
    """
    assert ts._HIGH_LIABILITY_DET_THRESHOLD == 0.50
    assert ts._HIGH_LIABILITY_DONOR_FRACTION == 0.70
    assert ts._LOW_CONFIDENCE_DET == 0.30
    assert ts._REPLICATION_DOMINANT_DET_FLOOR == 0.40
    assert ts._REPLICATION_DOMINANT_N_DATASETS == 15
    # The replication rung must sit BELOW the plain high line, or it is unreachable and this whole
    # anti-drift apparatus would be guarding an inert branch.
    assert ts._REPLICATION_DOMINANT_DET_FLOOR < ts._HIGH_LIABILITY_DET_THRESHOLD
    # ...and ABOVE the low line, or it would claim to rescue hits the method calls unrescuable.
    assert ts._REPLICATION_DOMINANT_DET_FLOOR >= ts._LOW_CONFIDENCE_DET


def test_severity_ladder_agrees_with_the_method_cell_for_cell():
    """Differential grid: this copy and the method must grade EVERY input identically.

    The grid brackets every cutoff in either ladder on BOTH sides (0.29/0.30, 0.39/0.40, 0.49/0.50,
    0.69/0.70, 1/2, 14/15) and puts `None` on all three axes, so it is exhaustive over the input's
    equivalence classes rather than a sample of them. That is what makes it a proof of agreement on live
    data rather than evidence for it.
    """
    try:
        from onc_methods.sc_normal_expression.stats import _essential_severity as method_grade
    except ImportError:  # pragma: no cover - the CI path
        pytest.skip(
            "analysis-methods is pinned in skills CI (skills-validate.yml) to a SHA that predates "
            "_essential_severity (AM #647, fe65660), so the method's ladder is not readable here. This "
            "test is live LOCALLY only; the unconditional guard is "
            "test_ladder_cutoffs_are_the_values_the_method_declares."
        )

    disagreements = []
    for det in _DETS:
        for frac in _FRACS:
            for n_ds in _NDSS:
                mine = ts._sc_normal_essential_severity(
                    {
                        "sc_normal_safety_essential_class": "critical_organ_liability",
                        "sc_normal_essential_max_detection_fraction": det,
                        "sc_normal_essential_donor_fraction": frac,
                        "sc_normal_essential_n_datasets_reliable": n_ds,
                    }
                )
                theirs = method_grade(
                    {
                        "median_detection_fraction": det,
                        "expressing_donor_fraction": frac,
                        "n_datasets_reliable": n_ds,
                    }
                )
                if mine != theirs:
                    disagreements.append((det, frac, n_ds, theirs, mine))

    cells = len(_DETS) * len(_FRACS) * len(_NDSS)
    assert cells == 616, f"grid shrank to {cells} cells — the aperture argument no longer holds"
    assert not disagreements, f"{len(disagreements)} of {cells} cells disagree, e.g. {disagreements[:5]}"
    # ANTI-VACUITY: a grid that only ever produced one grade would pass while testing nothing.
    grades = {
        ts._sc_normal_essential_severity(
            {
                "sc_normal_safety_essential_class": "critical_organ_liability",
                "sc_normal_essential_max_detection_fraction": det,
                "sc_normal_essential_donor_fraction": frac,
                "sc_normal_essential_n_datasets_reliable": n_ds,
            }
        )
        for det in _DETS
        for frac in _FRACS
        for n_ds in _NDSS
    }
    assert grades == {"high_severity", "moderate_severity", "low_confidence", "ungraded"}, grades


def test_replication_dominant_rung_promotes_heavy_atlas_agreement():
    """The MSLN-PAAD shape: 26 independent atlases at donor 0.881 but det 0.413.

    Measured live on all 504 corpus-20260914 pairs, this rung promotes 60 of the 451 accessible-graded
    pairs from `moderate_severity` to `high_severity`, and all 60 have det in [0.405, 0.497] with
    n_datasets_reliable in [15, 30] — i.e. every one of them is unreachable by the plain high rung.
    """
    msln = _scg("critical_organ_liability", 0.413, 0.881, 26)
    assert ts._sc_normal_essential_severity(msln) == "high_severity"
    # ANTI-VACUITY, both arms. (a) the fixture must NOT be reachable by the plain high rung, or this
    # test would pass on the old code:
    assert msln["sc_normal_essential_max_detection_fraction"] < ts._HIGH_LIABILITY_DET_THRESHOLD
    # (b) the replication floor must actually BITE — one atlas below it and the same hit is moderate:
    just_under = _scg("critical_organ_liability", 0.413, 0.881, ts._REPLICATION_DOMINANT_N_DATASETS - 1)
    assert ts._sc_normal_essential_severity(just_under) == "moderate_severity"


def test_replication_cannot_rescue_a_weak_or_donor_inconsistent_hit():
    """The rung is a bounded relaxation of DETECTION ONLY — the two other axes stay closed.

    This is the guard that keeps the rung a scalpel. Without it, "replication promotes" could be widened
    later into a general escape hatch and no test would notice.
    """
    # donor consistency is NOT tradeable: replication says a signal is REAL, not that it is CONSISTENT
    # ACROSS DONORS. 200 atlases cannot buy a donor fraction below the floor.
    inconsistent = _scg("critical_organ_liability", 0.45, 0.50, 200)
    assert inconsistent["sc_normal_essential_donor_fraction"] < ts._HIGH_LIABILITY_DONOR_FRACTION
    assert ts._sc_normal_essential_severity(inconsistent) == "moderate_severity"
    # the low band is NOT rescuable: replication makes a weak signal CREDIBLE, not LARGE.
    weak = _scg("critical_organ_liability", 0.10, 1.0, 200)
    assert weak["sc_normal_essential_max_detection_fraction"] < ts._LOW_CONFIDENCE_DET
    assert ts._sc_normal_essential_severity(weak) == "low_confidence"


def test_absent_grading_fields_grade_ungraded_rather_than_a_manufactured_low():
    """Unmeasured means NULL, not 0.

    The old code defaulted a missing donor fraction to 0.0 and a missing atlas count to 0, then ran the
    ladder over them — manufacturing `low_severity`, a measured-sounding claim, out of an absent column.
    Over a 616-cell grid that affected 140 cells. `ungraded` is the honest token and the method
    deliberately ranks it ABOVE `moderate`, so thinner data can never RELAX a veto.
    """
    for missing in ("sc_normal_essential_donor_fraction", "sc_normal_essential_n_datasets_reliable"):
        rec = _scg("critical_organ_liability", 0.85, 0.9, 11)
        rec[missing] = None
        got = ts._sc_normal_essential_severity(rec)
        assert got == "ungraded", f"{missing} absent → {got!r}"
        # the specific fail-open being closed: it must not read as the WEAKEST token
        assert got != "low_confidence"
    # ANTI-VACUITY: the very same record WITH the fields present grades high, so `ungraded` above is
    # caused by the absence and not by the fixture being weak.
    assert ts._sc_normal_essential_severity(_scg("critical_organ_liability", 0.85, 0.9, 11)) == "high_severity"


def test_none_is_reserved_for_no_hit_fired():
    """`None` and `ungraded` are different claims and must not be conflated.

    `None` = "no essential liability fired, there is nothing to grade" (the caller drops the annotation).
    `ungraded` = "a liability fired and we could not grade it" (the caller must SAY so).
    """
    assert ts._sc_normal_essential_severity(_sc("none")) is None
    assert ts._sc_normal_essential_severity(_sc("data_unavailable")) is None
    assert ts._sc_normal_essential_severity({}) is None
    assert ts._sc_normal_essential_severity(None) is None
    # ...but a FIRED class with nothing to grade on is a claim, not a silence — for BOTH fired classes.
    assert ts._sc_normal_essential_severity(_sc("critical_organ_liability")) == "ungraded"
    assert ts._sc_normal_essential_severity(_sc("origin_tissue_liability")) == "ungraded"


def test_severity_readout_is_an_explicit_map_not_a_string_transform():
    """The read-out must survive a token rename — this is the half a reviewer reads."""
    assert ts._ESSENTIAL_SEVERITY_READOUT["low_confidence"] == "low-confidence"
    # The defect this replaces, stated as executable evidence: the old transform maps the NEW token onto
    # the OLD, wrong wording, so a token rename alone would have changed nothing a human sees.
    assert f"{'low_confidence'.split('_')[0]}-severity" == "low-severity"
    assert ts._ESSENTIAL_SEVERITY_READOUT["low_confidence"] != "low-severity"
    # every token the ladder can return has a wording, and no wording is orphaned
    assert set(ts._ESSENTIAL_SEVERITY_READOUT) == {
        "high_severity",
        "moderate_severity",
        "low_confidence",
        "ungraded",
    }
    # an unknown token must fail LOUDLY rather than inherit a plausible-looking wording
    with pytest.raises(KeyError):
        ts._ESSENTIAL_SEVERITY_READOUT["catastrophic_severity"]


def test_liability_detail_says_ungraded_out_loud():
    """A fired liability we cannot grade is NAMED as ungraded, not silently un-annotated."""
    rec = _scg("critical_organ_liability", 0.85, 0.9, 11, cell="acinar cell", tissue="pancreas")
    rec["sc_normal_essential_donor_fraction"] = None
    assert ts._sc_normal_liability_detail(rec) == "pancreas acinar cell (11 atlases, severity ungraded)"
