"""Tests for the field-read-health sidecar.

The sidecar publishes reads MINUS declarations, per unit, as a committed `field_read_health.json`
that target-contracts' framework-health probe reads as a trending DIMENSION. These guard the four
things this particular feed can silently get wrong:

1. FRESHNESS THAT CAN FAIL — the committed file matches a rebuild, AND `--check` actually goes red
   on a mutated / absent / roster-less file. A staleness guard nobody has seen fail is not a guard.
2. THE ROSTER PIN HOLDS — a contracts-only card edit must NOT red `--check`. This is the whole
   reason the roster is committed: a pytest freshness test over a sibling-repo input is a cross-repo
   PR gate, and the handoff forbids exactly that. Tested by DRIFTING the live roster and asserting
   `--check` still passes while REPORTING the drift, because a pin that silently rots is worse than
   no pin.
3. `no_reads_detected` IS NOT `clean` — a unit the scraper's five shapes never matched must not be
   reported as healthy. `target-profile` is the live witness: it names `n_approved` in a spec dict
   and scrapes to zero reads.
4. THE CLASSIFICATION ONLY NARROWS — `meta_key` must be justified by the pinned roster itself (no
   declared field starts with `_`), not by a hand-written suppression list, and the queue must never
   change the exit code: a review queue is not a gate.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # skills/

from _skills_common import field_disposition as fd  # noqa: E402
from _skills_common import field_read_health_sidecar as S  # noqa: E402

COMMITTED = json.loads(S._OUT.read_text()) if S._OUT.exists() else {}


# ── 1. freshness that can fail ────────────────────────────────────────────────────────────────────
def test_committed_sidecar_is_fresh():
    assert S._OUT.exists(), f"{S._OUT.name} is not committed"
    pinned = S._pinned_roster(COMMITTED)
    assert pinned, "the committed census must ship the roster it was built against"
    assert S._canonical(COMMITTED) == S._canonical(S.build(declared=pinned))


def test_check_returns_zero_on_the_committed_file(capsys):
    assert S.main(["--check"]) == 0
    assert "OK" in capsys.readouterr().out


def test_check_goes_red_on_a_mutated_census(monkeypatch, tmp_path, capsys):
    """POSITIVE CONTROL. Without this, `--check` passing tells us nothing — a comparison that cannot
    fail is not a comparison."""
    stale = json.loads(json.dumps(COMMITTED))
    stale["summary"]["n_undeclared_pairs"] += 1
    target = tmp_path / "field_read_health.json"
    target.write_text(json.dumps(stale, indent=2, sort_keys=True))
    monkeypatch.setattr(S, "_OUT", target)
    assert S.main(["--check"]) == 1
    assert "STALE" in capsys.readouterr().err


def test_check_goes_red_when_the_census_is_absent(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(S, "_OUT", tmp_path / "nope.json")
    assert S.main(["--check"]) == 1
    assert "not committed" in capsys.readouterr().err


def test_check_goes_red_when_the_pinned_roster_is_missing(monkeypatch, tmp_path, capsys):
    """A census with no roster cannot be rebuilt deterministically, so it is STALE by definition —
    it must not silently fall back to the live sibling, which is the coupling being avoided."""
    without = json.loads(json.dumps(COMMITTED))
    without["rosters"].pop("declared_fields")
    target = tmp_path / "field_read_health.json"
    target.write_text(json.dumps(without, indent=2, sort_keys=True))
    monkeypatch.setattr(S, "_OUT", target)
    assert S.main(["--check"]) == 1
    assert "rosters.declared_fields" in capsys.readouterr().err


# ── 2. the roster pin holds ───────────────────────────────────────────────────────────────────────
def test_a_contracts_only_card_edit_does_not_red_the_check(monkeypatch, capsys):
    """THE LOAD-BEARING TEST. `declared_fields` reads the target-contracts sibling, so without the
    pin a card edit in another repo would fail an unrelated skills PR — a cross-repo PR gate. Drift
    the live roster hard (drop a card, add one, change a field list) and `--check` must still pass."""
    live = fd.declared_fields()
    drifted = {c: list(fs) for c, fs in live.items()}
    dropped, kept = sorted(drifted)[0], sorted(drifted)[1]
    drifted.pop(dropped)
    # Mutate a REAL card's field list, not the invented one — "a-card..." sorts first, so picking
    # after the insert would have exercised only the added-card case.
    drifted[kept] = drifted[kept] + ["a_field_nobody_declares"]
    drifted["a-card-that-does-not-exist"] = ["invented_field"]

    monkeypatch.setattr(fd, "declared_fields", lambda *a, **k: drifted)
    assert S.main(["--check"]) == 0, "the pin failed: a contracts-only edit reddened skills CI"


def test_check_reports_roster_drift_it_cannot_fail_on(monkeypatch, capsys):
    """The pin's cost is blindness to the roster going stale, so the drift MUST be printed. A pin
    that rots invisibly is worse than no pin."""
    live = fd.declared_fields()
    drifted = {c: list(fs) for c, fs in live.items()}
    drifted["a-card-that-does-not-exist"] = ["invented_field"]
    monkeypatch.setattr(fd, "declared_fields", lambda *a, **k: drifted)
    assert S.main(["--check"]) == 0
    out = capsys.readouterr().out
    assert "roster drift: 1 card(s) added" in out


def test_roster_drift_says_none_when_the_roster_matches():
    pinned = S._pinned_roster(COMMITTED)
    assert "roster drift: none" in S._roster_drift(pinned), (
        "the committed roster no longer matches the live contracts sibling — refresh it deliberately"
    )


def test_roster_drift_degrades_instead_of_crashing(monkeypatch):
    monkeypatch.setattr(fd, "declared_fields", lambda *a, **k: {})
    assert "NOT MEASURABLE" in S._roster_drift(S._pinned_roster(COMMITTED))


def test_build_is_a_pure_function_of_the_injected_roster(monkeypatch):
    """Injection must fully displace the sibling read — otherwise some path still reaches contracts
    and the pin is only partial."""
    pinned = S._pinned_roster(COMMITTED)

    def _boom(*a, **k):
        raise AssertionError("build(declared=...) still read the contracts sibling")

    monkeypatch.setattr(fd, "declared_fields", _boom)
    assert S.build(declared=pinned)["summary"]["n_reads_detected"] > 0


def test_code_readers_injection_matches_reading_the_sibling():
    """Back-compat: the new `declared` argument must not change what the scraper finds when it is
    handed the same roster it would have read itself."""
    live = fd.declared_fields()
    a, _ = fd.code_readers(S.SKILLS_DIR / "_skills_common")
    b, _ = fd.code_readers(S.SKILLS_DIR / "_skills_common", declared=live)
    assert dict(a) == dict(b)


def test_a_roster_without_a_card_stops_crediting_that_cards_reads():
    """POSITIVE CONTROL on the injection: if the roster is truly the input, removing a card must
    remove its reads. Otherwise the previous test passes vacuously."""
    live = fd.declared_fields()
    exact, _ = fd.code_readers(S.SKILLS_DIR / "tumor-presence", declared=live)
    read_cards = {c for ps in exact.values() for (c, _f) in ps}
    assert read_cards, "fixture assumption: tumor-presence reads at least one card"
    victim = sorted(read_cards)[0]
    without = {c: fs for c, fs in live.items() if c != victim}
    exact2, _ = fd.code_readers(S.SKILLS_DIR / "tumor-presence", declared=without)
    assert victim not in {c for ps in exact2.values() for (c, _f) in ps}


# ── 3. no_reads_detected is not clean ─────────────────────────────────────────────────────────────
def test_dispositions_are_exactly_the_three_documented_classes():
    seen = {u["disposition"] for u in COMMITTED["units"].values()}
    assert seen <= {"clean", "undeclared_reads", "no_reads_detected"}
    for name, u in COMMITTED["units"].items():
        if u["n_reads"] == 0:
            assert u["disposition"] == "no_reads_detected", f"{name}: silence reported as health"
        elif u["undeclared"]:
            assert u["disposition"] == "undeclared_reads"
        else:
            assert u["disposition"] == "clean"


def test_a_unit_the_scraper_cannot_see_is_not_reported_clean():
    """`target-profile` names `n_approved` in `tp_evidence_package.py`'s spec dict — a read none of
    the five recognised shapes match. It must land in `no_reads_detected`, never `clean`, or the
    dimension reports instrument blindness as a clean bill of health."""
    tp = COMMITTED["units"].get("target-profile")
    assert tp is not None, "target-profile is a real skill and must be scanned"
    assert tp["disposition"] == "no_reads_detected"
    assert COMMITTED["summary"]["n_no_reads_detected"] >= 1, (
        "if this ever reaches 0 the class is not being exercised and the distinction is untested"
    )


def test_the_shared_library_is_scanned_and_labelled_as_such():
    """`_skills_common` has no SKILL.md, so the skill criterion drops it — yet it makes ~a fifth of
    all reads in the tree. It is carried as an explicit `shared_library` unit so its reads are
    neither hidden nor miscounted as a skill's."""
    lib = COMMITTED["units"][S.SHARED_LIBRARY]
    assert lib["kind"] == "shared_library"
    assert lib["n_reads"] > 0
    kinds = {u["kind"] for u in COMMITTED["units"].values()}
    assert kinds == {"skill", "shared_library"}


def test_skill_units_agree_with_the_skill_md_criterion():
    """The unit roster must match what target-contracts' `probe.list_skill_names` enumerates, since
    the dashboard joins the two by name. Same criterion: a dir with a SKILL.md."""
    for name, u in COMMITTED["units"].items():
        if u["kind"] == "skill":
            assert (S.SKILLS_DIR / name / "SKILL.md").exists(), f"{name} is not a skill dir"


# ── 4. classification narrows, and the queue is not a gate ────────────────────────────────────────
def test_the_meta_key_rule_is_justified_by_the_roster_not_by_a_waiver():
    """`meta_key` is sound only because NO declared field starts with `_`. If one ever does, the rule
    starts silently suppressing a real undeclared read and must be revisited."""
    pinned = S._pinned_roster(COMMITTED)
    underscored = [(c, f) for c, fs in pinned.items() for f in fs if f.startswith("_")]
    assert underscored == [], f"the meta_key rule is no longer sound: {underscored[:5]}"


def test_classifications_are_exactly_the_two_documented_classes():
    seen = {r["classification"] for r in COMMITTED["undeclared_queue"]}
    assert seen <= {"meta_key", "emission_undetermined"}
    for row in COMMITTED["undeclared_queue"]:
        assert row["classification"] == S._classify(row["field"])


def test_the_queue_is_not_split_into_the_runtime_classes_here():
    """`read_of_None` / `emitted_but_undeclared` need observed-package evidence this producer cannot
    see. Inventing them here — from the repo's own part-synthetic fixtures — would make the metric
    measure our own paperwork, so the vocabulary must be ABSENT from the artifact."""
    measured = json.dumps({k: COMMITTED[k] for k in ("summary", "units", "undeclared_queue")})
    assert "read_of_None" not in measured
    assert "emitted_but_undeclared" not in measured
    # The prose MAY name them — it has to say who resolves them and why not here.
    assert "read_of_None" in COMMITTED["rosters"]["classification_rule"]


def test_a_populated_queue_does_not_change_the_exit_code():
    assert COMMITTED["summary"]["n_undeclared_pairs"] > 0, (
        "fixture assumption: the queue is populated on trunk, so 'returns 0 anyway' is not vacuous"
    )
    assert S.main(["--check"]) == 0


def test_every_queue_row_carries_the_evidence_a_reviewer_needs():
    for row in COMMITTED["undeclared_queue"]:
        assert row["unit"] in COMMITTED["units"]
        assert row["reader_kinds"], "a queue row with no reader kind cannot be triaged"
        assert set(row["reader_kinds"]) <= set(COMMITTED["rosters"]["reader_kinds"])
        assert row["field"] not in (S._pinned_roster(COMMITTED).get(row["card"]) or ()), (
            "a declared field must never reach the undeclared queue"
        )


def test_undeclared_finds_a_synthetic_undeclared_read_and_ignores_a_declared_one():
    declared = {"card-a": ["declared"]}
    exact = {"skill_code": {("card-a", "declared"), ("card-a", "invented")}}
    assert S._undeclared(exact, declared) == {("card-a", "invented"): {"skill_code"}}


def test_undeclared_treats_an_unknown_card_as_declaring_nothing():
    assert S._undeclared({"skill_code": {("ghost", "f")}}, {}) == {("ghost", "f"): {"skill_code"}}


# ── attribution reconciliation ────────────────────────────────────────────────────────────────────
def test_per_unit_attribution_reproduces_the_whole_tree_scrape():
    att = COMMITTED["attribution"]
    assert att["reconciled"] is True
    assert att["unattributed"] == [], (
        "a recognised read shape now joins across two top-level dirs, so the per-unit attribution is "
        "incomplete — the union, not the sum, is the invariant"
    )
    assert att["whole_tree_pairs"] == att["per_unit_union_pairs"]


def test_the_summed_credits_are_published_as_a_different_number():
    """Two skills reading the same field is two credits but one distinct read. Publishing only one of
    these numbers invites reconciling the wrong pair and concluding the instrument is broken."""
    att = COMMITTED["attribution"]
    assert att["per_unit_read_credits"] >= att["whole_tree_pairs"]
    assert att["per_unit_read_credits"] == sum(u["n_reads"] for u in COMMITTED["units"].values())
