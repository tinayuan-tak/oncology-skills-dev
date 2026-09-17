"""Tests for the descriptor-coverage sidecar.

The sidecar publishes `field_descriptor.coverage_report()` (plus rosters) as a committed
`descriptor_coverage.json` that target-contracts' framework-health probe reads as a trending
DIMENSION. These guard the three things a cross-repo feed can silently get wrong:

1. FRESHNESS THAT CAN FAIL — the committed file matches a fresh build, AND `--check` actually
   goes red on a mutated / absent file. A staleness guard nobody has seen fail is not a guard.
2. THE ROSTER REALLY REPLACES THE JOIN — classifying a field by set membership over the shipped
   rosters must agree with `field_descriptor.classify_field` on every field, including the
   envelope and unclassified paths. If it can disagree, the consumer needs its own copy of the
   join, which is the drift trap this whole design exists to avoid.
3. THE CELL/FIELD DISTINCTION SURVIVES — `n_descriptor_cells` and `n_distinct_fields` must be
   published as different numbers, because they ARE different (14 fields are declared by more
   than one measurement_type) and `coverage_report`'s own `n_descriptor_fields` name hides it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # skills/

from _skills_common import descriptor_coverage_sidecar as S  # noqa: E402
from _skills_common import display_gloss, field_descriptor  # noqa: E402


def test_committed_sidecar_is_fresh():
    """The whole point of the feed: what is committed is what the code computes."""
    assert S._OUT.exists(), f"{S._OUT.name} is not committed"
    assert S._canonical(json.loads(S._OUT.read_text())) == S._canonical(S.build())


def test_check_returns_zero_on_the_committed_file(capsys):
    assert S.main(["--check"]) == 0
    assert "OK" in capsys.readouterr().out


def test_check_goes_red_on_a_mutated_feed(monkeypatch, tmp_path, capsys):
    """POSITIVE CONTROL. Without this, `--check` passing tells us nothing — a comparison that
    cannot fail is decoration. Mutating one integer must be enough to trip it."""
    stale = json.loads(S._OUT.read_text())
    stale["summary"]["n_distinct_fields"] += 1
    target = tmp_path / "descriptor_coverage.json"
    target.write_text(json.dumps(stale, indent=2, sort_keys=True))
    monkeypatch.setattr(S, "_OUT", target)
    assert S.main(["--check"]) == 1
    assert "STALE" in capsys.readouterr().err


def test_check_goes_red_when_the_feed_is_absent(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(S, "_OUT", tmp_path / "nope.json")
    assert S.main(["--check"]) == 1
    assert "MISSING" in capsys.readouterr().err


def test_rosters_reproduce_classify_field_exactly():
    """The consumer classifies by SET MEMBERSHIP over the shipped rosters instead of re-deriving
    the SALIENCE_SPECS x display_gloss join. That substitution is only sound if it agrees with
    `classify_field` everywhere — so check every declared field, every envelope field, a private
    `_`-prefixed name, and a name in no spec at all."""
    report = S.build()
    rosters = report["rosters"]
    role_by_field = rosters["role_by_field"]
    envelope = set(rosters["envelope_fields"])

    def consumer_side(field: str) -> str:
        if field in role_by_field:
            return role_by_field[field]
        if field in envelope or field.startswith("_"):
            return field_descriptor.ROLE_ENVELOPE
        return field_descriptor.ROLE_UNCLASSIFIED

    probes = (
        list(rosters["declared_fields"])
        + list(envelope)
        + ["_private_thing", "a_field_no_spec_declares", "serum_marker"]
    )
    disagreements = [
        (f, consumer_side(f), field_descriptor.classify_field(f))
        for f in probes
        if consumer_side(f) != field_descriptor.classify_field(f)
    ]
    assert not disagreements, f"roster disagrees with classify_field on {disagreements[:5]}"
    assert len(probes) > 300, "the agreement check swept a suspiciously small roster"


def test_declared_roles_are_all_in_the_role_vocabulary():
    report = S.build()
    assert set(report["rosters"]["role_by_field"].values()) <= set(report["rosters"]["roles"])
    assert set(report["rosters"]["roles"]) == set(field_descriptor.ROLES)


def test_cells_and_distinct_fields_are_reported_separately():
    """`coverage_report`'s `n_descriptor_fields` is a (type, field) CELL count under a name that
    reads like a field count. A consumer reconciling the wrong one over-counts the roster, so the
    sidecar must publish both AND they must actually differ on the real vocabulary."""
    s = S.build()["summary"]
    assert s["n_descriptor_cells"] > s["n_distinct_fields"], (
        "if these ever coincide, no field is shared across measurement_types and "
        "n_multi_type_fields must be 0 — check that before relaxing this"
    )
    assert s["n_multi_type_fields"] > 0
    assert s["n_descriptor_cells"] == sum(len(v) for v in S.build()["fields_by_measurement_type"].values())


def test_multi_type_fields_really_span_several_measurement_types():
    report = S.build()
    by_type = report["fields_by_measurement_type"]
    for field in report["multi_type_fields"]:
        n = sum(1 for fields in by_type.values() if field in fields)
        assert n > 1, f"{field} is listed as multi-type but appears in {n} measurement_type(s)"


def test_gloss_gap_is_measured_in_both_directions():
    """`coverage_report` only asks 'numeric field with no gloss?'. The reverse — a curated
    METRIC_GLOSS entry that NO spec declares — is a real queue that direction cannot see."""
    report = S.build()
    declared = set(report["rosters"]["declared_fields"])
    for field in report["gloss_without_descriptor"]:
        assert field in display_gloss.METRIC_GLOSS
        assert field not in declared
        # These are exactly the static half of "emitted but undeclared": display semantics exist,
        # the salience layer cannot see the field.
        assert field_descriptor.classify_field(field) == field_descriptor.ROLE_UNCLASSIFIED
    assert report["summary"]["n_gloss_without_descriptor"] == len(report["gloss_without_descriptor"])


def test_summary_counts_agree_with_their_own_lists():
    """Every count must be re-derivable from the artifact itself, so a downstream self-check can
    catch a corrupted feed without recomputing the census."""
    report = S.build()
    s = report["summary"]
    assert s["n_numeric_fields_without_gloss"] == len(report["numeric_fields_without_gloss"])
    assert s["n_multi_type_fields"] == len(report["multi_type_fields"])
    assert s["n_distinct_fields"] == len(report["rosters"]["declared_fields"])
    assert s["n_envelope_fields"] == len(report["rosters"]["envelope_fields"])
    assert s["n_measurement_types"] == len(report["fields_by_measurement_type"])
    assert sum(report["role_counts"].values()) == s["n_descriptor_cells"]
    assert s["n_numeric_fields_with_gloss"] + s["n_numeric_fields_without_gloss"] <= s["n_numeric_fields"]


def test_the_feed_carries_no_timestamp():
    """A `generated_at` would be the only volatile field and would force a stable projection,
    which would weaken the drift basis for every other field. Keep the census pure.

    Checked over the KEY SET, recursively — NOT as a substring of the serialized blob. `generated_at`
    legitimately appears as a VALUE in `rosters.envelope_fields` (it is one of the 11 envelope field
    names), so a text scan reports a timestamp that isn't there. Absence-of-text is the wrong
    instrument for absence-of-structure.
    """
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
    hits = [(p, k) for p, k in keys(report) if k in volatile]
    assert not hits, f"volatile key(s) in the feed: {hits}"
    # ...and prove the scan can see a key at that depth at all, or it proves nothing.
    assert ("$.rosters", "role_by_field") in list(keys(report))
    assert "generated_at" in report["rosters"]["envelope_fields"], (
        "this test's whole point is that a substring scan would false-positive here"
    )


def test_build_is_deterministic_across_calls():
    assert S._canonical(S.build()) == S._canonical(S.build())


def test_source_class_tally_is_documented_as_constant_by_construction():
    """`source_class_counts` cannot currently say anything but `instrument` — the backing map is
    empty. A tally that cannot vary still READS as evidence on a dashboard, so the note has to
    say so; if the map ever gains entries this test fails and the note needs rewriting."""
    assert field_descriptor._SOURCE_CLASS_BY_MEASUREMENT_TYPE == {}, (
        "source classes are now real — drop the constant-by-construction caveat from the note"
    )
    report = S.build()
    assert set(report["source_class_counts"]) == {"instrument"}
    assert "CONSTANT BY CONSTRUCTION" in report["note"]


def test_note_warns_that_zero_unclassified_is_not_success():
    """field_descriptor says twice that an empty `unclassified` set means the classifier is
    fabricating roles. The consumer is in another repo and will only ever read this note."""
    note = S.build()["note"]
    assert "FABRICATING" in note
    assert "not that coverage is complete" in note


def test_writing_the_feed_is_pure_and_offline(monkeypatch):
    """Unlike the subskill smoke harness this must stay a milliseconds-long constant fold — that
    is what lets its --check gate every PR. Prove it never shells out."""
    import subprocess

    for name in ("run", "check_output", "Popen", "call"):
        monkeypatch.setattr(
            subprocess, name, lambda *a, **k: (_ for _ in ()).throw(AssertionError("sidecar spawned a subprocess"))
        )
    S.build()
