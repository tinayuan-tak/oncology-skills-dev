"""Known-target calibration harness (Phase 1).

The framework's standing regression suite: runs the fixture set in
`vocabularies/known_target_calibration_set.yaml` against checked-in decision
SNAPSHOTS (captured from live DepMap-26q1 framework runs this session) and
asserts per each entry's `assertion_type`. This codifies the ad-hoc known-target
backtests as a runnable, deterministic suite — every future framework change is
MEASURED against known targets, not argued.

The three assertion types are the executable form of the Phase-0 reframes
(docs/design/KNOWN_TARGET_FRAMEWORK_REFRAMES.md):
  - must_not_veto           — NECESSITY: an approved target must not hit a gate-C veto.
  - abstention_expected     — ABSTENTION: a data-blocked axis returns honest insufficient.
  - known_gap_expected_fail — a currently-false-negatived ADVANCED target reads the
                              documented gap verdict TODAY (flips when a fix lands).

Deterministic by design: it reads snapshots, not live data (no Bedrock, no S3, CI-safe).
REFRESH (opt-in, NOT run in CI): to re-capture snapshots against live data, run each
sub-skill with `/opt/conda/bin/python` (py3.12 — the pixi py3.14 default breaks live
reads and silently returns false-`insufficient`) and `AWS_PROFILE=cbg`, output under
~/dev/framework-runs/portfolio-validation/, then re-extract the minimal snapshots.
"""

from __future__ import annotations

from pathlib import Path

import json
import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "vocabularies" / "known_target_calibration_set.yaml"
SNAP_DIR = Path(__file__).resolve().parent / "snapshots"

# Dependency verdicts the nomination gate converts to a VETO (nomination_verdict_gate.yaml).
VETO_VERDICTS = {"non_dependent", "pan_essential_killer"}


def _load_fixtures() -> dict:
    return yaml.safe_load(FIXTURES.read_text())


def _load_snapshot(name: str) -> dict:
    p = SNAP_DIR / name
    assert p.exists(), f"snapshot missing: {p} (fixture declares measured:true)"
    return json.loads(p.read_text())


def _all_entries(fixtures: dict):
    """Yield (bucket, name, entry) across all fixture buckets."""
    for bucket in ("positive_controls", "known_gap_watchlist", "abstention_cases"):
        for name, entry in (fixtures.get(bucket) or {}).items():
            yield bucket, name, entry


# ---------------------------------------------------------------------------
# Fixture-set integrity (the config itself must stay well-formed)
# ---------------------------------------------------------------------------

def test_fixture_set_loads_and_versioned():
    f = _load_fixtures()
    assert f["version"] and f["depmap_release_pin"]
    assert any(_all_entries(f)), "fixture set is empty"


def test_every_entry_well_formed():
    valid_types = {"must_not_veto", "abstention_expected", "known_gap_expected_fail"}
    for bucket, name, e in _all_entries(_load_fixtures()):
        assert e.get("indication"), f"{name}: missing indication"
        assert e.get("assertion_type") in valid_types, f"{name}: bad assertion_type {e.get('assertion_type')!r}"
        assert "measured" in e, f"{name}: missing measured flag"
        # a measured entry must name a snapshot that exists
        if e.get("measured"):
            assert e.get("snapshot"), f"{name}: measured:true but no snapshot named"
            assert (SNAP_DIR / e["snapshot"]).exists(), f"{name}: snapshot file absent"


# ---------------------------------------------------------------------------
# The calibration assertions (parametrized over measured entries)
# ---------------------------------------------------------------------------

def _measured_entries():
    out = []
    for bucket, name, e in _all_entries(_load_fixtures()):
        if e.get("measured"):
            out.append(pytest.param(bucket, name, e, id=f"{name}-{e['indication']}"))
    return out


@pytest.mark.parametrize("bucket,name,entry", _measured_entries())
def test_known_target_calibration(bucket, name, entry):
    snap = _load_snapshot(entry["snapshot"])
    headline = snap.get("headline") or {}
    atype = entry["assertion_type"]

    if atype == "must_not_veto":
        # NECESSITY: an approved/validated target must NOT hit a gate-C veto verdict.
        verdict = headline.get("dependency_verdict")
        assert verdict is not None, f"{name}: no dependency_verdict in snapshot"
        assert verdict not in VETO_VERDICTS, (
            f"{name}: NECESSITY VIOLATION — approved target reads veto verdict "
            f"{verdict!r} (osimertinib-guard failure)")
        # also honor an explicit not-in list if provided
        for bad in entry.get("expected_verdict_not_in", []):
            assert verdict != bad, f"{name}: verdict {verdict!r} is in expected_verdict_not_in"

    elif atype == "abstention_expected":
        # ABSTENTION: the surface (sufficiency) gate must return honest insufficient,
        # NOT a fabricated nomination. This is a PASS, not a coverage failure.
        v = headline.get("surface_modality_verdict")
        assert v == entry.get("expected_surface_modality_verdict", "insufficient"), (
            f"{name}: ABSTENTION VIOLATION — surface verdict {v!r}, expected insufficient "
            f"(a data-blocked axis must abstain, not fabricate a nomination)")
        # fit_class must be null/None when abstaining
        assert headline.get("fit_class") in (None, "null"), (
            f"{name}: fit_class {headline.get('fit_class')!r} should be null when abstaining")

    elif atype == "known_gap_expected_fail":
        # KNOWN GAP: an ADVANCED program the framework currently false-negatives.
        # The suite PASSES when it still reads the documented gap verdict — this is the
        # regression anchor that Phase-2 (context-SL) will FLIP. When the fix lands,
        # change assertion_type→must_not_veto and this becomes a violation-if-regressed.
        verdict = headline.get("dependency_verdict")
        exp = entry.get("expected_verdict_current")
        assert verdict == exp, (
            f"{name}: known-gap watch verdict changed: {verdict!r} != expected {exp!r}. "
            f"If a fix (e.g. Phase-2 context-SL) landed, update the fixture "
            f"(assertion_type→must_not_veto, expected_after_context_sl).")
        drv = headline.get("driving_rule_id")
        assert drv == entry.get("expected_driving_rule_current"), (
            f"{name}: driving rule changed: {drv!r}")


# ---------------------------------------------------------------------------
# Coverage report (informational — always passes; documents what's measured)
# ---------------------------------------------------------------------------

def test_calibration_coverage_report(capsys):
    f = _load_fixtures()
    measured = pending = 0
    by_type: dict[str, int] = {}
    for bucket, name, e in _all_entries(f):
        by_type[e["assertion_type"]] = by_type.get(e["assertion_type"], 0) + 1
        if e.get("measured"):
            measured += 1
        else:
            pending += 1
    with capsys.disabled():
        print(f"\n[calibration] measured={measured} pending(reasoned-only)={pending} "
              f"by_assertion_type={by_type}")
    assert measured >= 1  # the suite is not empty of measured anchors


# ---------------------------------------------------------------------------
# Reference-profile well-formedness (2026-07-19 deep-research fidelity assessment)
# ---------------------------------------------------------------------------
# The reference_profiles section is the committed ASSESSMENT ground truth (deciding
# axis + coverage + agreement + severity per target). It is not a per-entry snapshot
# assertion (those stay in the measured buckets above); these guards keep it from
# silently rotting and pin the vocabularies so a fix-driven blind→captured flip is a
# clean, reviewable diff.

_COVERAGE_VOCAB = {"captured", "partial", "blind", "license_blocked", "out_of_scope"}
_SEVERITY_VOCAB = {"dangerous_false_positive", "silent_false_negative",
                   "honest_blind", "validated_lane"}


def _reference_profiles():
    return _load_fixtures().get("reference_profiles") or {}


def test_reference_profiles_present_and_well_formed():
    rp = _reference_profiles()
    assert rp, "reference_profiles section missing"
    for name, e in rp.items():
        assert e.get("deciding_axis"), f"{name}: missing deciding_axis"
        assert e.get("deciding_axis_coverage") in _COVERAGE_VOCAB, (
            f"{name}: bad deciding_axis_coverage {e.get('deciding_axis_coverage')!r}")
        assert e.get("severity") in _SEVERITY_VOCAB, (
            f"{name}: bad severity {e.get('severity')!r}")
        assert e.get("agreement"), f"{name}: missing agreement"


def test_reference_profile_severity_consistency():
    """severity must be consistent with the agreement class — the assessment's core
    taxonomy. A dangerous tier must be a false-positive; a validated-lane must agree."""
    rp = _reference_profiles()
    for name, e in rp.items():
        sev, agr = e["severity"], e["agreement"]
        if sev == "dangerous_false_positive":
            assert agr == "framework_false_positive", f"{name}: dangerous tier but agreement={agr}"
        if sev == "silent_false_negative":
            assert agr == "framework_false_negative", f"{name}: silent tier but agreement={agr}"
        if sev == "validated_lane":
            assert agr.startswith("agree"), f"{name}: validated_lane but agreement={agr}"


def test_reference_profile_coverage_report(capsys):
    rp = _reference_profiles()
    import collections
    sev = collections.Counter(e["severity"] for e in rp.values())
    cov = collections.Counter(e["deciding_axis_coverage"] for e in rp.values())
    with capsys.disabled():
        print(f"\n[reference-profiles] n={len(rp)} severity={dict(sev)} coverage={dict(cov)}")
    # the headline fidelity fact: deciding-axis is blind/partial/oos for the majority
    non_captured = sum(v for k, v in cov.items() if k != "captured")
    assert non_captured > len(rp) // 2, "sanity: assessment headline is majority-not-captured"
