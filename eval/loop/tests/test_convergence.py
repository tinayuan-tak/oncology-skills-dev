"""Teeth for eval/loop/convergence.py (SK#2303 Phase-0 WI-H, issue #2359).

The stopping rule is finding-set emptiness on the hash-fixed held-out roster. The ONLY thing that keeps
it defensible is that each of its three load-bearing properties has a planted-defect tooth that FIRES
and a paired clean case that stays SILENT (anti-vacuity, per the repo convention — see
eval/loop/tests/test_probes.py / test_substrate.py for the same discipline):

  NULL-blocking (the fail-open trap) — a dead/degraded package emits ZERO judge findings and ZERO probe
    *fails* (its probes are not_evaluable), so a naive "no findings => converged" reads it as a perfect
    pass. The teeth prove the NULL-block, not the finding count, is what stops it (acceptance #1).
  Hysteresis — a single empty pass with N>1 does NOT converge; N consecutive clean runs do (acceptance
    #2 and #3).
  Roster pinning — a run whose held-out membership was silently re-sampled pins differently and is not
    counted as converged.

All packages here are synthetic dicts shaped like critic/judge.judge() output + critic/probes tuples —
no live Bedrock, no fixtures needed (convergence consumes already-assessed outputs).
"""

from __future__ import annotations

import sys
from pathlib import Path

_LOOP = Path(__file__).resolve().parents[1]
if str(_LOOP) not in sys.path:
    sys.path.insert(0, str(_LOOP))

import convergence as C  # noqa: E402


# ── synthetic package builders (shaped like judge() output + probe tuples) ──────────────────────────
def _alive_clean_judge() -> dict:
    return {"skipped": None, "findings": [], "n_findings": 0, "report_only": True}


def _alive_with_findings(n: int) -> dict:
    return {"skipped": None, "findings": [{"kind": "divergence"}] * n, "n_findings": n, "report_only": True}


def _dead_judge() -> dict:
    # exactly what critic/judge.judge returns on a null_everything substrate: skipped set, findings empty.
    return {"skipped": "null_everything: n_cards_resolved == 0 (dead package)", "findings": [], "n_findings": 0}


def _probe_fail() -> list[tuple]:
    return [("C1", "S1", "fail", "rogue pair")]


def _probe_not_evaluable() -> list[tuple]:
    return [("C1", "S2", "not_evaluable", "integrated_properties section ABSENT")]


def _clean_run(run_id: str, keys=("ERBB2|BRCA|", "KRAS|COADREAD|"), *, expected_pin=None) -> C.HeldOutRunResult:
    packages = [(k, _alive_clean_judge(), []) for k in keys]
    return C.assess_run(run_id, packages, expected_pin=expected_pin)


# ── roster_pin: order-independent, set-identity-only ────────────────────────────────────────────────
def test_roster_pin_is_order_independent():
    assert C.roster_pin(["b", "a", "c"]) == C.roster_pin(["c", "a", "b"])


def test_roster_pin_changes_when_membership_changes():
    base = C.roster_pin(["a", "b", "c"])
    assert C.roster_pin(["a", "b"]) != base  # dropped
    assert C.roster_pin(["a", "b", "c", "d"]) != base  # added
    assert C.roster_pin(["a", "b", "x"]) != base  # swapped


def test_held_out_keys_selects_only_held_out():
    split = {"a|i|": "held_out", "b|i|": "dev", "c|i|": "held_out"}
    assert C.held_out_keys(split) == ["a|i|", "c|i|"]


# ── assess_package: alive/clean + NULL-block ────────────────────────────────────────────────────────
def test_assess_package_alive_clean():
    a = C.assess_package("ERBB2|BRCA|", _alive_clean_judge(), [])
    assert a.alive and a.clean and a.surviving_findings == 0


def test_assess_package_judge_findings_block_clean_but_stay_alive():
    a = C.assess_package("ERBB2|BRCA|", _alive_with_findings(2), [])
    assert a.alive and not a.clean and a.surviving_findings == 2


def test_assess_package_probe_fail_counts_as_surviving_finding():
    a = C.assess_package("ERBB2|BRCA|", _alive_clean_judge(), _probe_fail())
    assert a.alive and not a.clean and a.surviving_findings == 1


def test_assess_package_dead_judge_is_not_alive():
    a = C.assess_package("ERBB2|BRCA|", _dead_judge(), [])
    assert not a.alive and not a.clean
    assert any("skipped" in r for r in a.null_reasons)


def test_assess_package_not_evaluable_probe_is_not_alive():
    a = C.assess_package("ERBB2|BRCA|", _alive_clean_judge(), _probe_not_evaluable())
    assert not a.alive and not a.clean
    assert any("not_evaluable" in r for r in a.null_reasons)


def test_assess_package_non_dict_judge_is_not_alive():
    a = C.assess_package("ERBB2|BRCA|", None, [])
    assert not a.alive


# ── Acceptance #1: NULL/degraded blocks convergence (the fail-open trap) ────────────────────────────
def test_acceptance_1_planted_dead_package_blocks_convergence():
    """A held-out run that is finding-empty EXCEPT for one planted dead package must NOT converge — and
    the block reason must name the NULL, not a finding count (the dead package has zero of those)."""
    packages = [
        ("ERBB2|BRCA|", _alive_clean_judge(), []),
        ("DEAD|RUN|", _dead_judge(), _probe_not_evaluable()),  # planted dead package
    ]
    run = C.assess_run("r1", packages)
    assert not run.converged
    assert not run.all_alive
    assert any("NULL/degraded" in r for r in run.block_reasons), run.block_reasons
    # even with hysteresis_n=1 and the SAME dead run repeated, convergence never fires.
    rep = C.declare_convergence([run, C.assess_run("r2", packages)], hysteresis_n=1)
    assert not rep.converged


def test_acceptance_1_the_block_is_the_null_not_the_finding_count():
    """Proof the NULL-block (not an incidental finding) is what stops it: the dead package reports ZERO
    surviving findings, yet removing JUST the dead member makes the identical run converge."""
    dead = ("DEAD|RUN|", _dead_judge(), _probe_not_evaluable())
    alive = ("ERBB2|BRCA|", _alive_clean_judge(), [])

    dead_assessment = C.assess_package(*dead)
    assert dead_assessment.surviving_findings == 0  # a naive finding-counter would call this clean

    with_dead = C.assess_run("r", [alive, dead])
    without_dead = C.assess_run("r", [alive])
    assert not with_dead.converged  # blocked purely by the NULL
    assert without_dead.converged  # same alive package, now the roster converges


# ── Acceptance #2: hysteresis — a single empty pass with N>1 does not converge ──────────────────────
def test_acceptance_2_single_empty_pass_does_not_converge_when_hysteresis_gt_1():
    rep = C.declare_convergence([_clean_run("r1")], hysteresis_n=2)
    assert not rep.converged
    assert rep.consecutive_clean == 1


def test_acceptance_2_a_break_resets_the_streak():
    """One clean, one dirty, one clean, with N=2: the trailing streak is only 1 — no convergence."""
    dirty = C.assess_run("r2", [("ERBB2|BRCA|", _alive_with_findings(1), [])])
    rep = C.declare_convergence([_clean_run("r1"), dirty, _clean_run("r3")], hysteresis_n=2)
    assert not rep.converged
    assert rep.consecutive_clean == 1


# ── Acceptance #3: N consecutive fully-alive finding-empty runs declare convergence ─────────────────
def test_acceptance_3_n_consecutive_clean_runs_converge():
    rep = C.declare_convergence([_clean_run("r1"), _clean_run("r2")], hysteresis_n=2)
    assert rep.converged
    assert rep.consecutive_clean == 2
    assert rep.latest_block_reasons == []


def test_acceptance_3_only_the_trailing_runs_matter():
    """A dirty run EARLY followed by N clean runs still converges — hysteresis is a trailing streak."""
    dirty = C.assess_run("r0", [("ERBB2|BRCA|", _alive_with_findings(1), [])])
    rep = C.declare_convergence([dirty, _clean_run("r1"), _clean_run("r2")], hysteresis_n=2)
    assert rep.converged


def test_hysteresis_n_1_converges_on_a_single_clean_pass():
    rep = C.declare_convergence([_clean_run("r1")], hysteresis_n=1)
    assert rep.converged


# ── Roster pinning ──────────────────────────────────────────────────────────────────────────────────
def test_roster_resample_breaks_convergence():
    """Two clean passes, but the second silently re-sampled its held-out membership (swapped a member).
    Pinned against the first roster's hash, the moved run does NOT converge — the streak never reaches 2."""
    pin = C.roster_pin(["ERBB2|BRCA|", "KRAS|COADREAD|"])
    r1 = _clean_run("r1", keys=("ERBB2|BRCA|", "KRAS|COADREAD|"), expected_pin=pin)
    r2 = _clean_run("r2", keys=("ERBB2|BRCA|", "EGFR|LUAD|"), expected_pin=pin)  # re-sampled!
    assert r1.roster_matches and not r2.roster_matches
    rep = C.declare_convergence([r1, r2], hysteresis_n=2)
    assert not rep.converged
    assert any("roster pin mismatch" in r for r in rep.latest_block_reasons), rep.latest_block_reasons


def test_declare_convergence_applies_expected_pin_to_every_run():
    """expected_pin passed to declare_convergence is applied to runs that lack one, so the whole sequence
    is judged against the same pinned roster — a mid-sequence re-sample is caught without pre-stamping."""
    pin = C.roster_pin(["ERBB2|BRCA|", "KRAS|COADREAD|"])
    r1 = _clean_run("r1", keys=("ERBB2|BRCA|", "KRAS|COADREAD|"))  # no pin stamped
    r2 = _clean_run("r2", keys=("ERBB2|BRCA|", "EGFR|LUAD|"))  # no pin stamped, re-sampled
    rep = C.declare_convergence([r1, r2], hysteresis_n=2, expected_pin=pin)
    assert not rep.converged


def test_matching_roster_pin_still_converges():
    """Paired positive: the SAME pinned membership across both runs converges — the pin check reacts to a
    move, not to pinning per se."""
    pin = C.roster_pin(["ERBB2|BRCA|", "KRAS|COADREAD|"])
    r1 = _clean_run("r1", keys=("ERBB2|BRCA|", "KRAS|COADREAD|"), expected_pin=pin)
    r2 = _clean_run("r2", keys=("KRAS|COADREAD|", "ERBB2|BRCA|"), expected_pin=pin)  # same set, diff order
    rep = C.declare_convergence([r1, r2], hysteresis_n=2)
    assert rep.converged


# ── vacuity guards ──────────────────────────────────────────────────────────────────────────────────
def test_empty_held_out_roster_never_converges():
    """An EMPTY held-out roster is vacuous emptiness (nothing evaluated), never convergence."""
    empty = C.assess_run("r1", [])
    assert not empty.all_alive and not empty.converged
    assert any("EMPTY" in r for r in empty.block_reasons)
    rep = C.declare_convergence([empty, C.assess_run("r2", [])], hysteresis_n=2)
    assert not rep.converged


def test_no_runs_never_converges():
    rep = C.declare_convergence([], hysteresis_n=2)
    assert not rep.converged
    assert rep.consecutive_clean == 0


def test_hysteresis_n_zero_never_converges():
    """A nonsensical hysteresis_n <= 0 must not declare convergence (would be a trivial always-stop)."""
    rep = C.declare_convergence([_clean_run("r1"), _clean_run("r2")], hysteresis_n=0)
    assert not rep.converged


# ── report shape ────────────────────────────────────────────────────────────────────────────────────
def test_report_is_jsonable_and_keyed_on_property_coverage():
    coverage = {"required_pairs_total": 12, "covered_pairs_total": 9, "coverage_fraction": 0.75}
    rep = C.declare_convergence([_clean_run("r1"), _clean_run("r2")], hysteresis_n=2, property_coverage=coverage)
    blob = rep.to_jsonable()
    import json

    json.dumps(blob)  # must be serialisable
    assert blob["converged"] is True
    assert blob["property_coverage"] == coverage
    assert blob["n_runs"] == 2
