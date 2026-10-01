"""Unit tests for eval/loop/run_batch.py (#2345, SK#2303 Phase 0 WI-A).

Exercises the 4-clause preflight sentinel against synthetic packages (never a live run — the
dispatcher/subprocess seam is exercised separately, see test_run_one_resume_and_dispatch below,
which stubs subprocess.run so these stay offline/hermetic) and the --resume skip-logic.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # eval/loop/

import run_batch as RB  # noqa: E402


def _full_sections() -> dict:
    return {
        "source_properties": {"x": 1},
        "integrated_properties": {"y": 1},
        "local_composites": {"z": 1},
        "l3d": {"w": 1},
    }


def _alive_package(n_attempted: int = 17, n_passed: int = 17, fired: int = 1, verdict: str = "present") -> dict:
    pkg = {
        "governance": {
            "validation_summary": {
                "n_cards_attempted": n_attempted,
                "n_cards_passed": n_passed,
            }
        },
        "synthesis": {"verdict": verdict, "fired_rule_ids": [f"rule-{i}" for i in range(fired)]},
        "cards": [{"card_id": f"card-{i}", "validation_state": "passed"} for i in range(n_passed)],
    }
    pkg.update(_full_sections())
    return pkg


def test_alive_package_is_usable_and_alive():
    pkg = _alive_package()
    r = RB.preflight_sentinel(pkg)
    assert r.usable is True
    assert r.status == "alive"
    assert r.reasons == []


def test_partial_12_of_17_is_usable_and_partial():
    """A partial 12-16 of 17 cards resolved is FINE (per-target gap, not a defect) — accepted."""
    pkg = _alive_package(n_attempted=17, n_passed=12)
    r = RB.preflight_sentinel(pkg)
    assert r.usable is True
    assert r.status == "partial"
    assert r.n_cards_resolved == 12


def test_dead_run_zero_cards_resolved_is_rejected():
    pkg = _alive_package(n_attempted=17, n_passed=0)
    r = RB.preflight_sentinel(pkg)
    assert r.usable is False
    assert r.status == "dead"
    assert any("clause1" in reason for reason in r.reasons)


def test_read_error_card_is_rejected_even_with_good_verdict():
    pkg = _alive_package()
    pkg["cards"].append({"card_id": "poisoned-card", "availability_state": "read_error"})
    r = RB.preflight_sentinel(pkg)
    assert r.usable is False
    assert "poisoned-card" in r.read_error_cards
    assert any("clause4" in reason for reason in r.reasons)


def test_insufficient_verdict_with_no_fired_rules_is_rejected():
    pkg = _alive_package(verdict="insufficient", fired=0)
    r = RB.preflight_sentinel(pkg)
    assert r.usable is False
    assert any("clause2" in reason for reason in r.reasons)


def test_insufficient_verdict_but_fired_rules_present_still_rejected():
    """verdict == 'insufficient' alone fails clause 2 even when rules fired (the AND is strict)."""
    pkg = _alive_package(verdict="insufficient", fired=3)
    r = RB.preflight_sentinel(pkg)
    assert r.usable is False
    assert any("clause2" in reason for reason in r.reasons)


def test_missing_envelope_section_is_rejected():
    pkg = _alive_package()
    del pkg["l3d"]
    r = RB.preflight_sentinel(pkg)
    assert r.usable is False
    assert any("clause3" in reason and "l3d" in reason for reason in r.reasons)
    assert "l3d" not in r.sections_present


def test_fake_sentinel_rc0_identical_card_roster_does_not_fool_the_check():
    """A dead run that still carries rc=0-shaped signals (identical card_id roster,
    local_composites present) must still be rejected once n_cards_passed == 0 — the measured
    fake-sentinel trap this clause set exists to defeat."""
    pkg = _alive_package(n_attempted=17, n_passed=0)
    pkg["cards"] = [{"card_id": f"card-{i}"} for i in range(17)]  # roster present, nothing PASSED
    r = RB.preflight_sentinel(pkg)
    assert r.usable is False
    assert r.status == "dead"


# ── roster loading ──────────────────────────────────────────────────────────────────────────────


def test_load_roster_accepts_pair_lists(tmp_path):
    p = tmp_path / "roster.json"
    p.write_text(json.dumps([["KRAS", "COADREAD"], ["EGFR", "LUAD"]]))
    roster = RB.load_roster(p)
    assert roster[0].target == "KRAS" and roster[0].indication == "COADREAD"
    assert roster[1].target == "EGFR" and roster[1].indication == "LUAD"


def test_load_roster_accepts_objects_and_dedupes(tmp_path):
    p = tmp_path / "roster.json"
    p.write_text(
        json.dumps(
            [
                {"target": "KRAS", "indication": "COADREAD"},
                {"target": "KRAS", "indication": "COADREAD"},  # duplicate -> deduped
                {"target": "EGFR", "indication": "LUAD"},
            ]
        )
    )
    roster = RB.load_roster(p)
    assert len(roster) == 2


# ── --resume ────────────────────────────────────────────────────────────────────────────────────


def test_resume_skips_a_valid_existing_package(tmp_path):
    iter_dir = tmp_path / "iter-001-abc"
    iter_dir.mkdir()
    t = RB.Triple("KRAS", "COADREAD")
    (iter_dir / f"{t.key}.json").write_text(json.dumps(_alive_package()))
    assert RB._existing_package_is_valid(iter_dir / f"{t.key}.json") is True


def test_resume_rejects_a_dead_existing_package(tmp_path):
    iter_dir = tmp_path / "iter-001-abc"
    iter_dir.mkdir()
    t = RB.Triple("KRAS", "COADREAD")
    (iter_dir / f"{t.key}.json").write_text(json.dumps(_alive_package(n_attempted=17, n_passed=0)))
    assert RB._existing_package_is_valid(iter_dir / f"{t.key}.json") is False


def test_resume_rejects_a_missing_package(tmp_path):
    assert RB._existing_package_is_valid(tmp_path / "nope.json") is False


def test_run_batch_resume_only_reruns_invalid_triples(tmp_path, monkeypatch):
    """End-to-end (no subprocess): run_batch skips the valid existing triple and only dispatches
    run_one for the dead/missing ones."""
    iter_dir = tmp_path / "iter-001-abc"
    iter_dir.mkdir(parents=True)
    roster = [RB.Triple("KRAS", "COADREAD"), RB.Triple("EGFR", "LUAD"), RB.Triple("BRAF", "SKCM")]

    # KRAS/COADREAD already has a VALID package -> should be resumed, not re-run.
    (iter_dir / f"{roster[0].key}.json").write_text(json.dumps(_alive_package()))
    # EGFR/LUAD has a DEAD existing package -> must be re-run.
    (iter_dir / f"{roster[1].key}.json").write_text(json.dumps(_alive_package(n_attempted=17, n_passed=0)))
    # BRAF/SKCM has no existing package -> must be run.

    dispatched = []

    def fake_run_one(skill, triple, out_dir, timeout):
        dispatched.append(triple.key)
        out_dir.mkdir(parents=True, exist_ok=True)
        pkg_path = out_dir / "evidence_package.json"
        pkg_path.write_text(json.dumps(_alive_package()))
        return {
            "target": triple.target,
            "indication": triple.indication,
            "skill": skill,
            "package_path": str(pkg_path),
            "rc": 0,
            "status": "alive",
            "usable": True,
            "reasons": [],
            "duration_s": 0.1,
        }

    monkeypatch.setattr(RB, "run_one", fake_run_one)
    manifest = RB.run_batch(skill="tumor-presence", roster=roster, iter_dir=iter_dir, jobs=2, resume=True)

    assert sorted(dispatched) == sorted([roster[1].key, roster[2].key])
    assert manifest["n_resumed"] == 1
    assert manifest["n_run"] == 2
    assert manifest["roster_size"] == 3
    assert (iter_dir / "manifest.json").exists()
