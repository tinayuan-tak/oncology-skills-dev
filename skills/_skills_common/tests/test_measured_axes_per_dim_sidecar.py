"""Tests for the static per-dim axis-measurability sidecar (framework-health dimension 3 of 3).

The sidecar publishes, as a committed `measured_axes_per_dim.json`, whether each risk dim's axes
have an INSTRUMENT at all — declared measurement_types that carry measurement descriptors. These
guard the five things this particular feed can silently get wrong:

1. FRESHNESS THAT CAN FAIL — the committed file matches a fresh build AND `--check` really goes
   red on a mutated / absent file. A staleness guard nobody has seen fail is decoration.
2. THE TWO VOCABULARIES STAY APART — static CAPABILITY states must never collide with
   `risk_projection.COVERAGE_STATES`, the per-RUN outcome states. Collapsing them is how a
   consumer ends up reconciling a declaration against a measurement and "fixing" whichever
   disagrees. They are allowed to disagree, and today one axis does.
3. THE ROSTER CANNOT SILENTLY EMPTY — the producer must RAISE, not publish `{}`, when
   tp_fanout's literals move. This is target-contracts #795 in reverse: there the same literal
   was read from `run.py` after it moved to `tp_fanout.py`, and because a missing file and an
   unmapped axis both yield a falsy value, three artifact fields read `None` on 22 of 22 skills
   for weeks with nothing red.
4. NO SIBLING REPO ON ANY CODE PATH — the card->measurement_type registry lives in
   target-contracts. If `build()` could reach it, this producer's `--check` would red an
   unrelated skills PR whenever a card was edited next door: the cross-repo PR gate the
   framework-health handoff forbids.
5. FIELDS THAT COULD ONLY EVER SAY ONE THING — `gate_short` and `verdict_bearing` are asserted to
   actually VARY across the real roster. A field constant by construction still reads as evidence
   on a dashboard.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # skills/

from _skills_common import measured_axes_per_dim_sidecar as S  # noqa: E402
from _skills_common import risk_projection  # noqa: E402

# ---------- 1. freshness, with a control that proves it can fail ----------


def test_committed_sidecar_is_fresh():
    """The whole point of the feed: what is committed is what the code computes."""
    assert S._OUT.exists(), f"{S._OUT.name} is not committed"
    assert S._canonical(json.loads(S._OUT.read_text())) == S._canonical(S.build())


def test_check_returns_zero_on_the_committed_file(capsys):
    assert S.main(["--check"]) == 0
    assert "OK" in capsys.readouterr().out


def test_check_goes_red_on_a_mutated_feed(monkeypatch, tmp_path, capsys):
    """POSITIVE CONTROL. Mutating one integer must be enough to trip `--check`."""
    stale = json.loads(S._OUT.read_text())
    stale["summary"]["n_declared_types_distinct"] += 1
    target = tmp_path / "measured_axes_per_dim.json"
    target.write_text(json.dumps(stale, indent=2, sort_keys=True))
    monkeypatch.setattr(S, "_OUT", target)
    assert S.main(["--check"]) == 1
    assert "STALE" in capsys.readouterr().err


def test_check_goes_red_when_the_feed_is_absent(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(S, "_OUT", tmp_path / "nope.json")
    assert S.main(["--check"]) == 1
    assert "MISSING" in capsys.readouterr().err


def test_build_is_deterministic_across_calls():
    assert S._canonical(S.build()) == S._canonical(S.build())


# ---------- 2. static capability is not per-run outcome ----------


def test_static_states_are_disjoint_from_per_run_coverage_states():
    """The naming guard. `measured` / `unmeasured` / `undescribed` / `absent` are per-RUN outcomes
    computed from data; these four are declaration-time CAPABILITY. If the vocabularies ever
    overlap, a consumer can join a capability onto an outcome and neither reading survives."""
    assert not (S.STATIC_STATES & risk_projection.COVERAGE_STATES), (
        "static capability states now collide with per-run coverage states — rename before shipping"
    )
    states_in_feed = {v["static_state"] for v in S.build()["axes"].values()}
    assert states_in_feed <= S.STATIC_STATES


def test_static_capability_and_per_run_outcome_are_allowed_to_disagree():
    """`translational_readiness` is descriptor_covered here while the 504-target corpus measured it
    `undescribed` on 504/504 runs — the measured disagreement, encoded rather than smoothed over.

    Capability holds because its declared types carry measurement descriptors; the per-run outcome
    held because no field emitted by its RESOLVED cards matched one. Both correct — and the
    disagreement is now the STRONGEST possible: as of 2026-09-18 the descriptor-coverage sweep specced
    ALL FOUR declared types (model_availability, genotype_matched_model, pdx_drug_response were the
    last three), so static capability is full (4/4) yet the corpus still measured undescribed 504/504.
    If the counts below change, the note's worked example is stale and must be rewritten — do NOT just
    update the numbers.
    """
    axis = S.build()["axes"]["translational_readiness"]
    assert axis["static_state"] == S.STATE_DESCRIPTOR_COVERED
    assert axis["n_types_with_measurement_descriptor"] == 4, "all four declared types are now covered"
    assert axis["n_declared_types"] == 4
    assert sorted(axis["types_without_measurement_descriptor"]) == []
    note = S.build()["note"]
    assert "CAPABILITY, NOT OUTCOME" in note
    assert "504/504" in note


def test_note_warns_against_headlining_the_per_axis_flag():
    """One covered type earns `descriptor_covered`, so the per-axis flag saturates near 100% and
    measures the direction already finished. The live queue is per TYPE. The consumer is in another
    repo and will only ever read this note."""
    report = S.build()
    s = report["summary"]
    fanout = s["n_axes_descriptor_covered"] + s["n_axes_descriptor_blind"] + s["n_axes_no_declared_types"]
    assert s["n_axes_descriptor_covered"] / fanout > 0.85, (
        "the per-axis flag is no longer saturated — the note's 'do not headline it' warning may "
        "need rewriting rather than deleting"
    )
    assert s["n_types_without_measurement_descriptor"] > s["n_axes_descriptor_blind"], (
        "the per-type queue must be the larger, more informative number"
    )
    assert "DO NOT HEADLINE" in report["note"]


def test_descriptor_coverage_is_a_property_of_the_type_not_the_axis():
    """No measurement_type may be blind under one axis and covered under another.

    Measured true today, and the per-axis and per-dim roll-ups quietly depend on it: if a type
    could be covered in one place and blind in another, `types_without_measurement_descriptor`
    would not be a set-valued fact about types and every union over axes would be ambiguous.
    """
    report = S.build()
    blind_per_axis = {t for v in report["axes"].values() for t in v["types_without_measurement_descriptor"]}
    covered = {
        t
        for axis, types in report["rosters"]["declared_types_by_axis"].items()
        for t in types
        if t not in report["axes"][axis]["types_without_measurement_descriptor"]
    }
    assert not (blind_per_axis & covered), (
        f"type covered under one axis and blind under another: {sorted(blind_per_axis & covered)}"
    )


# ---------- 3. the roster cannot silently empty ----------


def test_fanout_roster_raises_rather_than_returning_an_empty_map(monkeypatch, tmp_path):
    """The #795 defect, guarded on the producing side. A module with no SUB_SKILLS must RAISE."""
    empty = tmp_path / "tp_fanout.py"
    empty.write_text("SOMETHING_ELSE = [('a', 'b')]\n")
    monkeypatch.setattr(S, "TP_FANOUT", empty)
    with pytest.raises(RuntimeError, match="SUB_SKILLS"):
        S._fanout_roster()


def test_fanout_roster_parses_a_literal_it_is_given(monkeypatch, tmp_path):
    """POSITIVE CONTROL for the test above: the raise must be caused by the ABSENT literal, not by
    the parser being unable to read a tmp_path module at all."""
    mod = tmp_path / "tp_fanout.py"
    mod.write_text("SUB_SKILLS = [('some-skill-dir', 'some_short')]\n")
    monkeypatch.setattr(S, "TP_FANOUT", mod)
    assert S._fanout_roster() == {"some_short": "some-skill-dir"}


def test_short_to_gate_raises_rather_than_returning_an_empty_map(monkeypatch, tmp_path):
    mod = tmp_path / "tp_fanout.py"
    mod.write_text("SUB_SKILLS = [('d', 's')]\n")
    monkeypatch.setattr(S, "TP_FANOUT", mod)
    with pytest.raises(RuntimeError, match="_SHORT_TO_GATE"):
        S._short_to_gate()


def test_the_real_roster_is_populated_and_covers_every_mapped_axis():
    """A floor plus named members, so a silently narrowed roster cannot pass vacuously."""
    roster = S._fanout_roster()
    assert len(roster) >= 15, f"expected the full fan-out roster, got {len(roster)}"
    for short in ("safety", "selectivity", "dependency", "expression", "immune_context"):
        assert short in roster
    assert len(S._short_to_gate()) >= 8


# ---------- 4. no sibling repo on any code path ----------


def test_build_never_reaches_the_target_contracts_registry(monkeypatch):
    """The cross-repo safety property, tested by BREAKING the sibling reader rather than by reading
    the imports. `measurement_types._load_registry` resolves `vocabularies/measurement_types.yaml`
    out of the target-contracts checkout; if any path in `build()` called it, a card edit next door
    could red this producer's `--check` in skills CI."""
    from _skills_common import measurement_types

    def explode(*a, **k):
        raise AssertionError("build() reached the target-contracts measurement_types registry")

    monkeypatch.setattr(measurement_types, "_load_registry", explode)
    monkeypatch.setattr(measurement_types, "card_measurement_type", explode)
    S.build()  # must not raise


def test_writing_the_feed_is_pure_and_offline(monkeypatch):
    """Pure constant-folding plus local file reads is what lets `--check` gate every PR."""
    import subprocess

    for name in ("run", "check_output", "Popen", "call"):
        monkeypatch.setattr(
            subprocess, name, lambda *a, **k: (_ for _ in ()).throw(AssertionError("sidecar spawned a subprocess"))
        )
    S.build()


def test_the_feed_carries_no_timestamp():
    """A `generated_at` would be the only volatile field and would force a stable projection,
    weakening the drift basis for every other field. Checked over the KEY SET recursively, not as a
    substring of the blob — absence-of-text is the wrong instrument for absence-of-structure."""
    volatile = {"generated_at", "timestamp", "run_at", "produced_at", "root_shas"}

    def keys(node, path="$"):
        if isinstance(node, dict):
            for k, v in node.items():
                yield path, k
                yield from keys(v, f"{path}.{k}")
        elif isinstance(node, list):
            for item in node:
                yield from keys(item, f"{path}[]")

    report = S.build()
    assert not [(p, k) for p, k in keys(report) if k in volatile]
    # ...and prove the scan can see a key at that depth at all, or it proves nothing.
    assert ("$.rosters", "declared_types_by_axis") in list(keys(report))


# ---------- 5. fields that could only ever say one thing ----------


def test_gate_short_and_verdict_bearing_actually_vary():
    """Both fields would read as evidence on a dashboard while being constant by construction. So
    assert each takes more than one value on the real roster: `gate_short` must be present on some
    axes and absent on others (absence is Decision 3 excluding a gateless axis from a bin, not a
    gap), and `verdict_bearing` must show all three of True / False / None."""
    axes = S.build()["axes"]
    gated = {a for a, v in axes.items() if v["gate_short"]}
    ungated = {a for a, v in axes.items() if not v["gate_short"]}
    assert gated and ungated, "gate_short says the same thing for every axis"
    assert "safety" in gated and "cis_coherence" in ungated

    verdicts = {v["verdict_bearing"] for v in axes.values()}
    assert verdicts == {True, False, None}, (
        f"verdict_bearing takes only {verdicts} — None must stay distinct from False (an axis with "
        "no lens is UNKNOWN, not verdict-less)"
    )
    assert "necessary, not sufficient" in S.build()["note"]


def test_card_fed_dims_are_distinguishable_from_blind_dims():
    """`clinical` / `commercial` read 0 of 1 axes covered. That is 'card-fed', not 'blind', and the
    ONLY thing letting a consumer tell the difference is `not_a_fanout_axes` — the same guard
    `evidence_coverage_by_dim` makes on the per-run side."""
    dims = S.build()["dims"]
    for dim in ("clinical", "commercial"):
        d = dims[dim]
        assert d["n_axes_counted"] == 1
        assert d["n_axes_descriptor_covered"] == 0
        assert d["not_a_fanout_axes"] == [dim], "the disambiguating list is empty — 0/1 now reads as blindness"
        assert d["descriptor_blind_axes"] == [], "a card-fed axis must not be classed as an instrument gap"
    assert "not_a_fanout_axes" in S.build()["note"]


def test_coverage_only_axes_annotate_dims_that_already_exist():
    """A coverage-only or context-display axis may annotate a dim, never invent one — the same
    invariant `test_coverage_only_axes_add_no_new_dim` pins on the per-run side."""
    report = S.build()
    assert set(report["dims"]) == set(risk_projection.AXIS_TO_DIM.values())
    for dim, d in report["dims"].items():
        for axis in d["coverage_only_axes"] + d["displayed_context_axes"]:
            assert axis in report["axes"]


# ---------- self-consistency of the published counts ----------


def test_summary_counts_agree_with_their_own_lists():
    """Every count must be re-derivable from the artifact, so a downstream self-check can catch a
    corrupted feed without recomputing the census."""
    report = S.build()
    s = report["summary"]
    assert s["n_axes"] == len(report["axes"])
    assert s["n_dims"] == len(report["dims"])
    assert s["n_types_without_measurement_descriptor"] == len(report["types_without_measurement_descriptor"])
    assert s["n_spec_types_pulled_by_no_axis"] == len(report["spec_types_pulled_by_no_axis"])
    assert (
        s["n_types_with_measurement_descriptor"] + s["n_types_without_measurement_descriptor"]
        == s["n_declared_types_distinct"]
    )
    assert s["n_declared_types_distinct"] == len(
        {t for ts in report["rosters"]["declared_types_by_axis"].values() for t in ts}
    )
    for state in S.STATIC_STATES:
        assert s[f"n_axes_{state}"] == sum(1 for v in report["axes"].values() if v["static_state"] == state)


def test_the_reverse_queue_is_published_as_a_number_even_at_zero():
    """A SALIENCE_SPEC no axis pulls. Empty today (the catalog is a strict subset of the declared
    set), and the field must still exist: an absent key reads as 'not applicable' rather than
    'measured, and currently none'."""
    report = S.build()
    assert "n_spec_types_pulled_by_no_axis" in report["summary"]
    assert report["spec_types_pulled_by_no_axis"] == []
    assert report["summary"]["n_salience_spec_types"] == report["summary"]["n_types_with_measurement_descriptor"], (
        "every spec'd type used to be pulled by some axis AND carry a measurement field; if this "
        "breaks, reading note (4) about descriptor_blind == absent-from-SALIENCE_SPECS is stale"
    )


def test_declared_absence_rationales_are_not_copied_into_the_feed():
    """Only the `state` crosses the repo boundary. Each AXIS_DIM_EXCLUSIONS reason is a paragraph of
    reviewed argument; a copy in a second repo is a copy that drifts out of date silently."""
    blob = S._canonical(S.build())
    for axis, entry in risk_projection.AXIS_DIM_EXCLUSIONS.items():
        assert entry["reason"] not in blob, f"{axis}'s rationale prose was copied into the feed"
    states = S.build()["rosters"]["declared_absence_states"]
    assert set(states) == set(risk_projection.AXIS_DIM_EXCLUSIONS)
    assert set(states.values()) <= risk_projection.AXIS_DIM_EXCLUSION_STATES
    assert states["subtype_fit"] == risk_projection.OPEN_PENDING_REVIEW
