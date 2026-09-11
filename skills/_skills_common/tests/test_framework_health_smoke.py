"""Tests for the framework-health 'runs clean?' smoke harness.

The harness runs each wired subskill's real run.py under FRAMEWORK_HEALTH_SMOKE=1
(card readers stubbed → NO live data) and records run_health into a committed rollup.
These guard: the smoke seam short-circuits reads, the harness classifies clean vs
error vs clean_uninstrumented vs timeout, and the committed rollup stays fresh +
self-consistent.

Two of them are regression guards for 2026-09-11, when the harness was found to be lying in
both directions at once: its COVERAGE predicate text-matched "run_wired_skill" (admitting skills
that never reach resolve_cards, for which the offline smoke flag is inert → live S3 reads), and
its ERROR classification folded subprocess.TimeoutExpired into smoke="error" (publishing machine
load as a pipeline break). See test_coverage_predicate_requires_a_call_not_a_mention and
test_timeout_is_its_own_state_not_an_error.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # skills/

from _skills_common import framework_health_smoke as H  # noqa: E402
from _skills_common import resolve_cards  # noqa: E402


def test_smoke_seam_short_circuits_live_reads(monkeypatch):
    """With FRAMEWORK_HEALTH_SMOKE set, resolve_cards returns synthetic stubs and NEVER
    calls the live dispatcher (proves offline determinism)."""
    # If the seam leaked, _import_dispatcher would be reached; make it explode to prove it isn't.
    import _skills_common as C

    monkeypatch.setattr(
        C, "_import_dispatcher", lambda: (_ for _ in ()).throw(AssertionError("live read attempted under smoke"))
    )
    monkeypatch.setenv("FRAMEWORK_HEALTH_SMOKE", "1")
    out = resolve_cards(["card-a", "card-b"], "FIXTURE", "COADREAD")
    assert [c["card_id"] for c in out] == ["card-a", "card-b"]
    assert all(c["_smoke"] and not c["_missing"] for c in out)


def test_smoke_seam_off_by_default(monkeypatch):
    """Unset flag → the smoke branch is NOT entered (live path is taken)."""
    monkeypatch.delenv("FRAMEWORK_HEALTH_SMOKE", raising=False)
    import _skills_common as C

    monkeypatch.setattr(C, "_import_dispatcher", lambda: lambda cid, t, i, **k: None)
    out = resolve_cards(["card-a"], "T", "IND")
    # live path tagged it missing (dispatcher returned None) — proves smoke branch was skipped
    assert out[0]["_missing"] and not out[0].get("_smoke")


def test_wired_subskills_discovered():
    """The harness finds the wired subskills and skips infra/orchestration dirs."""
    skills = H._wired_subskills()
    assert "tumor-presence" in skills and "functional-requirement" in skills
    for skip in ("_skills_common", "compose-dashboard", "query-target-evidence"):
        assert skip not in skills


def test_coverage_predicate_requires_a_call_not_a_mention(tmp_path):
    """★ The 2026-09-11 root cause. The predicate was `"run_wired_skill" in read_text()`, so a
    run.py that merely NAMED the dispatcher in a comment — even to deny using it — was admitted.
    Those skills never reach resolve_cards, so FRAMEWORK_HEALTH_SMOKE is inert for them and the
    "offline" harness silently issued live S3 reads. Coverage must key on a real CALL."""
    mention_only = tmp_path / "mention.py"
    mention_only.write_text(
        '"""Mirrors the shared dispatcher\'s run_wired_skill argparse."""\n'
        "# this scan hand-rolls main() (no run_wired_skill)\n"
        "run_wired_skill = None\n"  # even a bare NAME reference is not a call
        "def main():\n    return 0\n"
    )
    assert H._calls_run_wired_skill(mention_only) is False

    real_call = tmp_path / "real.py"
    real_call.write_text("from _skills_common import run_wired_skill\n\nrun_wired_skill(skill_name='x')\n")
    assert H._calls_run_wired_skill(real_call) is True

    attr_call = tmp_path / "attr.py"
    attr_call.write_text("import _skills_common as C\n\nC.run_wired_skill(skill_name='x')\n")
    assert H._calls_run_wired_skill(attr_call) is True

    # Unparseable → uncovered, never falsely covered.
    assert H._calls_run_wired_skill(tmp_path / "nope.py") is False
    broken = tmp_path / "broken.py"
    broken.write_text("run_wired_skill(  # unclosed\n")
    assert H._calls_run_wired_skill(broken) is False


def test_every_covered_subskill_actually_calls_the_dispatcher():
    """The offline guarantee in the module docstring is only true if every covered skill routes
    through run_wired_skill → resolve_cards (where the smoke flag lives). Assert it directly, so a
    future hand-rolled entrypoint cannot re-enter coverage and start doing live reads under a
    harness that advertises no network."""
    for skill in H._wired_subskills():
        rp = H.SKILLS_DIR / skill / "scripts" / "run.py"
        assert H._calls_run_wired_skill(rp), f"{skill} is covered but never calls run_wired_skill"


def test_retired_scan_hook_skills_are_gone():
    """bispecific-pair-scan + surfaceome-cohort-ranking (retired 2026-09-11) were the two skills
    the text predicate falsely admitted. They must stay retired — the physics lives in
    analysis-methods and the in-spine cards that read it belong to surface-modality-fit.

    Asserts the SKILL is gone (no SKILL.md, no run.py, out of coverage), not that the path holds
    zero bytes: `git rm` leaves an untracked __pycache__ husk behind in any checkout that ran the
    old suite, so a bare `.exists()` here passes in CI's fresh clone and fails on every working
    tree — retired `skills/compose-dashboard/` (#654) is the standing precedent for such a husk."""
    for retired in ("bispecific-pair-scan", "surfaceome-cohort-ranking"):
        d = H.SKILLS_DIR / retired
        assert not (d / "SKILL.md").exists(), f"{retired} was retired; do not re-add the skill"
        assert not (d / "scripts" / "run.py").exists(), f"{retired} was retired; do not re-add its entrypoint"
        assert retired not in H._wired_subskills()


def test_stable_projection_drops_volatile_timings():
    """--check must ignore per-run seconds (volatile) but catch a status change."""
    base = {
        "subskills": {
            "s": {
                "smoke": "clean",
                "run_health": {"status": "ok", "read_secs": 0.1, "compute_secs": 0.2, "total_secs": 0.3},
            }
        }
    }
    slow = {
        "subskills": {
            "s": {
                "smoke": "clean",
                "run_health": {"status": "ok", "read_secs": 9.9, "compute_secs": 8.8, "total_secs": 18.7},
            }
        }
    }
    assert H._stable(base) == H._stable(slow)  # only timings differ → same projection
    broke = {"subskills": {"s": {"smoke": "error", "run_health": {}}}}
    assert H._stable(base) != H._stable(broke)  # status change IS caught


def test_timeout_is_its_own_state_not_an_error(monkeypatch):
    """★ The second half of the 2026-09-11 fix. TimeoutExpired subclasses SubprocessError, so a
    single `except subprocess.SubprocessError` recorded machine load as smoke="error" — a
    fabricated pipeline break, published into a cross-repo feed, reddening release-gate step 2."""

    def _timeout(*a, **k):
        raise H.subprocess.TimeoutExpired(cmd="run.py", timeout=H._TIMEOUT_SECS)

    monkeypatch.setattr(H.subprocess, "run", _timeout)
    rec = H._smoke_one("tumor-presence")
    assert rec["smoke"] == "timeout"
    assert "machine load" in rec["smoke_reason"]

    # A non-timeout SubprocessError is still a real error.
    def _other(*a, **k):
        raise H.subprocess.SubprocessError("boom")

    monkeypatch.setattr(H.subprocess, "run", _other)
    assert H._smoke_one("tumor-presence")["smoke"] == "error"


def test_timeout_does_not_count_as_error_in_the_summary(monkeypatch):
    monkeypatch.setattr(H, "_wired_subskills", lambda: ["a", "b"])
    monkeypatch.setattr(
        H, "_smoke_one", lambda s: {"skill_name": s, "smoke": "timeout" if s == "a" else "clean", "run_health": {}}
    )
    s = H.build()["summary"]
    assert (s["n_timeout"], s["n_error"], s["n_clean"]) == (1, 0, 1)


def test_timeout_is_dropped_from_the_check_comparison():
    """A timed-out skill produced NO reading. Comparing 'no reading' against the committed 'clean'
    would report the feed STALE on nothing but machine load, so it is excluded from BOTH sides —
    while a genuine status change on a MEASURED skill is still caught."""
    committed = {"subskills": {"s": {"smoke": "clean", "run_health": {"status": "ok"}}, "t": {"smoke": "clean"}}}
    fresh = {"subskills": {"s": {"smoke": "timeout"}, "t": {"smoke": "clean"}}}
    unmeasured = H._timed_out(fresh)
    assert unmeasured == {"s"}
    assert H._stable(committed, unmeasured) == H._stable(fresh, unmeasured)
    # ... but a real change on the still-measured skill is NOT masked
    regressed = {"subskills": {"s": {"smoke": "timeout"}, "t": {"smoke": "error"}}}
    assert H._stable(committed, unmeasured) != H._stable(regressed, unmeasured)


def test_a_partial_run_refuses_to_overwrite_the_committed_feed(monkeypatch, tmp_path, capsys):
    """Writing `timeout` into the committed artifact would publish "we don't know" as a subskill's
    standing health. A partial reading is not a health record — refuse, exit 1, write nothing."""
    out = tmp_path / "subskill_health.json"
    monkeypatch.setattr(H, "_OUT", out)
    monkeypatch.setattr(H, "_wired_subskills", lambda: ["a"])
    monkeypatch.setattr(H, "_smoke_one", lambda s: {"skill_name": s, "smoke": "timeout", "smoke_reason": "slow"})
    assert H.main([]) == 1
    assert not out.exists()
    assert "REFUSING" in capsys.readouterr().err


def test_committed_rollup_is_fresh_and_consistent():
    """The committed subskill_health.json must exist, be self-consistent, and pass --check
    (this is what a CI guard runs). If this fails, regenerate it."""
    if not H._OUT.exists():
        import pytest

        pytest.skip("no committed subskill_health.json")
    rep = json.loads(H._OUT.read_text())
    s = rep["summary"]
    # tallies match the per-subskill records
    smokes = [r["smoke"] for r in rep["subskills"].values()]
    assert s["n_clean"] == smokes.count("clean")
    assert s["n_error"] == smokes.count("error")
    assert s["n_clean_uninstrumented"] == smokes.count("clean_uninstrumented")
    assert s["n_subskills"] == len(smokes)
    # A committed feed must be a COMPLETE reading — main() refuses to write a partial one.
    assert s.get("n_timeout", 0) == 0 and "timeout" not in smokes
    # every clean record carries a run_health status
    for r in rep["subskills"].values():
        if r["smoke"] == "clean":
            assert r["run_health"]["status"] in ("ok", "degraded")
