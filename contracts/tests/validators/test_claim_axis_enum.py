"""claim_axis enum validator tests — population conformance PLUS mutation teeth.

The same two halves as its 0a/0b/0c siblings, and the second is again the load-bearing one:

  * POPULATION — the committed vocabularies/claim_axis.enum.yaml passes every clause, and the facts it
    was built to record are pinned as FACTS rather than left in prose: 15 skills, 61 `(skill, axis_key)`
    pairs over 60 distinct tokens, exactly ONE collision (`DEP`), 23 axes resolving 28 catalogued
    properties (14/15 at v1.0.0, +5 axes / +8 properties from Wave-1a's safety.yaml, +4 axes /
    +5 properties from Wave-1b's dependency.yaml), and `integrated_families.normal_liability` resolved
    by THREE axes under three different display names.
    contracts/tests/ is collected wholesale by the `contracts-pytest` job with no path
    filter, so a regression reds trunk here without needing a workflow edit.

  * TEETH — each clause is exercised against a PLANTED defect and asserted RED with a SPECIFIC error
    substring. A validator nobody has watched fail is not a validator.

The anti-patterns arc #2210 has already paid for are avoided here too:

  1. A validator that RAISES is not a validator that FAILS — preland.sh prints `FAIL <label>` identically
     for "found a violation" and "crashed on line 1". `test_unparseable_enum_fails_rather_than_crashes`
     pins the difference.
  2. Monkeypatching the layer beneath a clause hides the clause. `test_gate_invocation_matches_preland_argv`
     invokes the validator EXACTLY as the gate does — cwd contracts/, relative paths, the literal argv,
     nothing patched — and `test_the_two_gate_argv_tests_match_what_preland_sh_ACTUALLY_RUNS` reads
     `preland.sh` and pins the wired flags to what those tests hardcode.
  3. A "validate it when present" clause is structurally blind to a key that should be ABSENT (0c's
     correction 4). Both absence-shaped contracts in this file — an EMPTY `resolves:` and an ABSENT
     `collides_with:` — are reconciled over the FULL axis population with absence a first-class value,
     and both directions of both are given teeth below.
  4. Per SK#2091 nothing here asserts verdict inertness, and every test below was proven able to fail by
     planting its mutant before it was committed.

A note on what is NOT tested here, deliberately: nothing in this file compares the registry against the
real `HeadlineSpec`s. contracts/ may not read skills' code — the dependency direction is
skills/ -> contracts/ — so the equality half lives in
skills/_skills_common/tests/test_claim_axis_registry_coverage.py, which re-derives every axis from the
ASTs fail-loud. A reader who assumed this file held the roster to the code would think the registry is
complete when it is only self-consistent, which is why clause 8's message names the split too.
"""

from __future__ import annotations

import copy
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

CONTRACTS = Path(__file__).resolve().parents[2]
VALIDATORS = CONTRACTS / "validators"
ENUM = CONTRACTS / "vocabularies" / "claim_axis.enum.yaml"
CATALOG = CONTRACTS / "vocabularies" / "property_catalog"
SKILLS = CONTRACTS.parent / "skills"

# The validator imports its helpers from its sibling, so validators/ must be importable. This mirrors
# what running it as a script does implicitly (sys.path[0] = the script's directory).
if str(VALIDATORS) not in sys.path:
    sys.path.insert(0, str(VALIDATORS))


def _load_validator():
    path = VALIDATORS / "validate_claim_axis.py"
    spec = importlib.util.spec_from_file_location("validate_claim_axis", path)
    mod = importlib.util.module_from_spec(spec)
    # Register BEFORE exec: @dataclass resolves its annotations through sys.modules[cls.__module__], and
    # Report is imported from the sibling module, which is itself loaded this way.
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


V = _load_validator()
DOC = yaml.safe_load(ENUM.read_text())


def _validate(path: Path) -> "list[str]":
    return V.validate_enum(path, CATALOG, SKILLS).errors


def _plant(tmp_path: Path, mutate) -> "list[str]":
    """Deep-copy the real enum, plant EXACTLY ONE defect, validate, return the errors.

    The temp file keeps the real filename: `enum_id` must equal the filename stem, so a renamed temp file
    would red every mutant for the wrong reason — and would red the clean control below too, which is how
    you find out.
    """
    doc = copy.deepcopy(DOC)
    mutate(doc)
    f = tmp_path / ENUM.name
    f.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True))
    return _validate(f)


def _axis(doc: dict, skill: str, axis_key: str) -> dict:
    for a in doc["axes"]:
        if a["skill"] == skill and a["axis_key"] == axis_key:
            return a
    raise AssertionError(f"fixture drift: no {skill}/{axis_key} entry in the registry")


# ── POPULATION ────────────────────────────────────────────────────────────────────────────────────────
def test_the_committed_enum_passes_every_clause():
    errors = _validate(ENUM)
    assert errors == [], errors


def test_the_clean_control_written_to_tmp_also_passes(tmp_path):
    """The control WITHOUT which every mutant below could be red for the wrong reason — a YAML round-trip
    through safe_dump under the real filename must itself be clean."""
    assert _plant(tmp_path, lambda d: None) == []


def test_the_measured_population_is_pinned():
    """The numbers this file was built from, asserted so a silent shrink reds. Each floor names its
    subject INSIDE the assert with a `len()`, because skills/tests/test_discovery_guards_carry_floors.py
    reads floors statically and a floor bound to a local first is invisible to it."""
    assert len(DOC["axes"]) == 61, "the axis roster changed — re-measure the HeadlineSpecs, then bump"
    assert len(DOC["skills"]) == 15, "the skill roster changed"
    assert len({(a["skill"], a["axis_key"]) for a in DOC["axes"]}) == 61, "a (skill, axis_key) pair is duplicated"
    assert len({a["axis_key"] for a in DOC["axes"]}) == 60, (
        "61 pairs over 60 distinct tokens is the whole argument for keying on the PAIR; if these are "
        "equal the collision is gone and the argument needs re-stating, if the gap grew a new collision "
        "landed undeclared"
    )


def test_the_pair_is_the_identity_and_DEP_is_why():
    """The measured collision, pinned. `DEP` is genetic dependency in one skill and alteration-conferred
    dependency in another — two properties, one token. This is the transposition of 0b's
    `single_source_only`-across-5-families result, and it is MEASURED here rather than assumed."""
    collisions = V._measured_collisions({(a["skill"], a["axis_key"]) for a in DOC["axes"]})
    assert sorted(collisions) == ["DEP"], collisions
    assert collisions["DEP"] == {"functional-requirement", "genomic-alteration-profile"}
    both = [_axis(DOC, s, "DEP") for s in sorted(collisions["DEP"])]
    assert all(a["collides_with"] for a in both), "both sides of a collision declare it, not just one"
    assert both[0]["resolves"] != both[1]["resolves"], (
        "the two DEP axes must resolve DIFFERENT properties — if they resolved the same one the "
        "collision would not be a collision, it would be an alignment and the tokens should merge"
    )


def test_the_owners_question_is_answered_by_the_property_index():
    """The deliverable, pinned as a fact. THREE axes with THREE different display names resolve ONE
    normal-tissue-liability property, and the `properties:` index makes that one lookup instead of a
    fifteen-file read. This is what replaces a rename."""
    entry = DOC["properties"]["integrated_families.normal_liability"]
    pairs = {(c["skill"], c["axis_key"]) for c in entry["resolved_by"]}
    assert pairs == {
        ("on-target-safety-liability", "NORMAL_TISSUE"),
        ("tumor-selectivity", "SAFE"),
        ("surface-modality-fit", "SAFETY"),
    }, pairs
    assert len({ax for _s, ax in pairs}) == 3, "three display names is the point — if they merged, #2229 landed"


def test_resolves_uses_the_qualified_form_because_the_catalog_namespace_COLLIDES():
    """Why `resolves:` is `<catalog_id>.<entry_id>` and not the bare id, driven rather than asserted from
    prose: the catalog's 41 entries (Wave-1a added safety.yaml's 8, Wave-1b dependency.yaml's 6) have
    only 39 distinct bare ids. `collect_entry_ids()` — the namespace `estimates_property` already
    resolves against — flattens them, so 2 of 41 entries are genuinely ambiguous by bare name."""
    from validate_property_catalog import collect_entry_ids

    flat = collect_entry_ids(CATALOG)
    qualified = {f"{cid}.{eid}" for cid, eids in V._catalog_index(CATALOG)[1].items() for eid in eids}
    assert len(qualified) == 41, len(qualified)
    assert len(flat) == 39, (
        "the bare-id namespace is no longer ambiguous, so the qualified-form requirement has lost its "
        "measured justification — re-read the enum header before relaxing anything"
    )
    colliding = {q.split(".", 1)[1] for q in qualified} - flat
    assert colliding == set(), "sanity: every bare id of a qualified id is in the flat namespace"
    assert all(V._QUALIFIED_PROPERTY_ID.match(r) for a in DOC["axes"] for r in a["resolves"])


def test_every_unresolved_axis_says_WHY_and_every_resolved_one_does_not():
    """Clause 5 on the real population, both directions. 38 of 61 axes resolve nothing because three l2a
    catalogs remain Wave-1 items (safety.yaml landed Wave-1a, dependency.yaml Wave-1b; genomic/
    selectivity/surface = #2212-#2214 remain); each names the item that will fill it. PAN_ESSENTIAL — the
    one safety axis empty at v1.1.0 — is now RESOLVED (Wave-1b catalogued the shared
    dependency.crispr_essentiality it reads at liability valence)."""
    unresolved = [a for a in DOC["axes"] if not a["resolves"]]
    resolved = [a for a in DOC["axes"] if a["resolves"]]
    assert len(unresolved) == 38, len(unresolved)
    assert len(resolved) == 23, len(resolved)
    assert all(str(a.get("resolves_pending", "")).strip() for a in unresolved)
    assert not any("resolves_pending" in a for a in resolved)


def test_no_coverage_dimension_claims_to_be_a_gate():
    """Clause 9 on the real population. 38/61 is REPORTED; gating it would block this item behind its
    peer l2a epics or force catalog entries invented ahead of their measurement."""
    dims = DOC["coverage_dimensions"]
    assert len(dims) >= 3, dims
    assert all(d["is_a_gate"] is False for d in dims)
    assert all(isinstance(d["measured"], int) and isinstance(d["total"], int) for d in dims)


# ── TEETH ─────────────────────────────────────────────────────────────────────────────────────────────
def test_unparseable_enum_fails_rather_than_crashes(tmp_path):
    """Clause-independent. `preland.sh` prints `FAIL <label>` identically for a violation and a crash, so
    the distinction is invisible exactly when it matters."""
    f = tmp_path / ENUM.name
    f.write_text("enum_id: claim_axis\naxes: [ unterminated\n")
    errors = _validate(f)
    assert errors and "could not be read as YAML" in errors[0], errors


def test_duplicate_pair_is_red(tmp_path):
    errors = _plant(tmp_path, lambda d: d["axes"].append(copy.deepcopy(_axis(d, "immune-context", "IMMUNE"))))
    assert any("duplicate `(skill, axis_key)` pair" in e for e in errors), errors


def test_a_skill_that_is_not_a_real_directory_is_red(tmp_path):
    def mutate(d):
        _axis(d, "immune-context", "IMMUNE")["skill"] = "no-such-skill"
        d["skills"]["no-such-skill"] = d["skills"].pop("immune-context")

    errors = _plant(tmp_path, mutate)
    assert any("is not a directory under" in e for e in errors), errors


def test_a_dropped_axis_entry_is_red(tmp_path):
    """The `skills:` index is the inverse view, so dropping an axis from the roster alone cannot pass."""
    errors = _plant(tmp_path, lambda d: d["axes"].remove(_axis(d, "functional-requirement", "SEL")))
    assert any("does not match this skill's `axes` entries in order" in e for e in errors), errors


def test_a_skill_missing_from_the_index_is_red(tmp_path):
    errors = _plant(tmp_path, lambda d: d["skills"].pop("immune-context"))
    assert any("have no `skills:` index entry" in e for e in errors), errors


def test_a_scrambled_display_order_is_red(tmp_path):
    """The index carries the DISPLAY ORDER, which the flat roster would lose, so it is pinned to the
    roster SEQUENCE and not merely to its set."""
    errors = _plant(tmp_path, lambda d: d["skills"]["literature-context"]["axis_keys"].reverse())
    assert any("does not match this skill's `axes` entries in order" in e for e in errors), errors


def test_two_skills_claiming_one_gate_is_red(tmp_path):
    errors = _plant(tmp_path, lambda d: d["skills"]["immune-context"].update(gate="presence"))
    assert any("is claimed by" in e for e in errors), errors


def test_a_bare_property_id_is_red(tmp_path):
    def mutate(d):
        a = _axis(d, "functional-requirement", "DEP")
        a["resolves"] = ["essentiality"]
        d["properties"].pop("integrated_families.essentiality")

    errors = _plant(tmp_path, mutate)
    assert any("must be the QUALIFIED form" in e for e in errors), errors


def test_a_qualified_id_that_does_not_resolve_is_red(tmp_path):
    def mutate(d):
        _axis(d, "functional-requirement", "DEP")["resolves"] = ["integrated_families.no_such_entry"]
        d["properties"]["integrated_families.no_such_entry"] = d["properties"].pop("integrated_families.essentiality")

    errors = _plant(tmp_path, mutate)
    assert any("declares no entry" in e for e in errors), errors


def test_an_empty_resolves_without_a_pending_note_is_red(tmp_path):
    """Clause 5, first direction: an unexplained empty list is indistinguishable from an oversight."""

    def mutate(d):
        a = _axis(d, "combination-and-vulnerability", "SL")
        a.pop("resolves_pending")

    errors = _plant(tmp_path, mutate)
    assert any("`resolves_pending` is REQUIRED" in e for e in errors), errors


def test_a_pending_note_on_a_resolved_axis_is_red(tmp_path):
    """Clause 5, second direction: a stale roadmap claim."""
    errors = _plant(tmp_path, lambda d: _axis(d, "functional-requirement", "DEP").update(resolves_pending="later"))
    assert any("may not be present" in e for e in errors), errors


def test_dropping_a_resolves_the_CATALOG_declares_is_red(tmp_path):
    """★ CLAUSE 6, the direction 0c's correction 4 says a conditional check cannot see. The axis becomes
    `resolves: []` + a pending note — internally perfectly well-formed — while the catalog still names it
    as a consumer. Only a reconciliation over the FULL population, with the EMPTY set a first-class
    value, reds this. A 'validate `resolves` when present' clause would be GREEN."""

    def mutate(d):
        a = _axis(d, "tumor-selectivity", "SAFE")
        a["resolves"] = []
        a["resolves_pending"] = "deliberately blanked by the mutant"
        d["properties"]["integrated_families.normal_liability"]["resolved_by"] = [
            c
            for c in d["properties"]["integrated_families.normal_liability"]["resolved_by"]
            if c["skill"] != "tumor-selectivity"
        ]

    errors = _plant(tmp_path, mutate)
    assert any("FALSE ABSENCE" in e for e in errors), errors


def test_a_resolves_claim_the_catalog_does_not_declare_is_red(tmp_path):
    """CLAUSE 6, the other direction: an unsourced alignment claim."""

    def mutate(d):
        _axis(d, "literature-context", "VOLUME")["resolves"] = ["expression.presence"]
        _axis(d, "literature-context", "VOLUME").pop("resolves_pending")
        d["properties"]["expression.presence"] = {
            "resolved_by": [{"skill": "literature-context", "axis_key": "VOLUME"}]
        }

    errors = _plant(tmp_path, mutate)
    assert any("NOT declared as `consumers:`" in e for e in errors), errors


def test_a_property_index_entry_disagreeing_with_the_roster_is_red(tmp_path):
    def mutate(d):
        d["properties"]["integrated_families.normal_liability"]["resolved_by"].append(
            {"skill": "immune-context", "axis_key": "IMMUNE"}
        )

    errors = _plant(tmp_path, mutate)
    assert any("disagrees with the axes whose `resolves` cites" in e for e in errors), errors


def test_an_undeclared_collision_is_red(tmp_path):
    """★ CLAUSE 7, the absence direction. Removing `collides_with` leaves a perfectly well-formed entry;
    only reconciling the DECLARED collisions against the MEASURED ones with absence a first-class value
    catches it."""
    errors = _plant(tmp_path, lambda d: _axis(d, "genomic-alteration-profile", "DEP").pop("collides_with"))
    assert any("carries no `collides_with`" in e for e in errors), errors


def test_a_declared_collision_that_does_not_exist_is_red(tmp_path):
    """CLAUSE 7, the other direction: a fictional collision misdirects every reader of the entry."""

    def mutate(d):
        _axis(d, "immune-context", "IMMUNE")["collides_with"] = [{"skill": "tumor-presence", "axis_key": "IMMUNE"}]

    errors = _plant(tmp_path, mutate)
    assert any("used by no other skill" in e for e in errors), errors


def test_a_collision_declared_against_a_DIFFERENT_token_is_red(tmp_path):
    def mutate(d):
        _axis(d, "genomic-alteration-profile", "DEP")["collides_with"] = [
            {"skill": "functional-requirement", "axis_key": "SEL"}
        ]

    errors = _plant(tmp_path, mutate)
    assert any("a collision is by DEFINITION the SAME token" in e for e in errors), errors


def test_an_undocumented_collision_is_red(tmp_path):
    errors = _plant(tmp_path, lambda d: d["documented_collisions"].clear())
    assert any("must be a non-empty list when present" in e for e in errors), errors


def test_documented_collisions_naming_the_wrong_skill_set_is_red(tmp_path):
    errors = _plant(tmp_path, lambda d: d["documented_collisions"][0].update(skills=["functional-requirement"]))
    assert any("must be exactly the skills measured using" in e for e in errors), errors


def test_a_missing_critical_flag_is_red(tmp_path):
    """`critical` is REQUIRED, not defaulted: an absent flag would read as 'not critical', so a forgotten
    key would silently understate a decision-critical axis — and critical-axis membership floors
    confidence in `headline_core.derive_confidence`."""
    errors = _plant(tmp_path, lambda d: _axis(d, "functional-requirement", "DEP").pop("critical"))
    assert any("missing required key `critical`" in e for e in errors), errors


def test_a_misspelled_key_is_red_not_ignored(tmp_path):
    """Closed allowlists at every level. A silently-ignored `resolves_pendng:` would fail OPEN on clause
    5, which is this file's central discipline."""

    def mutate(d):
        a = _axis(d, "combination-and-vulnerability", "SL")
        a["resolves_pendng"] = a.pop("resolves_pending")

    errors = _plant(tmp_path, mutate)
    assert any("resolves_pendng" in e for e in errors), errors


def test_a_shrunken_floor_is_red(tmp_path):
    errors = _plant(tmp_path, lambda d: d["axes"].clear())
    assert any("`axes` must be a non-empty list" in e for e in errors), errors


def test_a_floor_raised_above_the_population_is_red(tmp_path):
    errors = _plant(tmp_path, lambda d: d["population_floors"].update(axes=999))
    assert any("the population SHRANK" in e for e in errors), errors


def test_a_skills_floor_below_the_measured_fleet_is_red(tmp_path):
    """The floor may not be relaxed below 15, and the message names WHERE the equality half lives — a
    reader who thinks this validator pins the roster to the code would believe a wrong thing."""
    errors = _plant(tmp_path, lambda d: d["population_floors"].update(skills=1))
    assert any("`skills` floor must be >= 15" in e for e in errors), errors


def test_a_dimension_claiming_to_be_a_gate_is_red(tmp_path):
    errors = _plant(tmp_path, lambda d: d["coverage_dimensions"][0].update(is_a_gate=True))
    assert any("must be present and exactly `false`" in e for e in errors), errors


def test_a_dimension_without_its_denominator_is_red(tmp_path):
    """Every coverage number needs a denominator; 14 without 61 is not a coverage statement."""
    errors = _plant(tmp_path, lambda d: d["coverage_dimensions"][0].pop("total"))
    assert any("`total` must be an int" in e for e in errors), errors


@pytest.mark.parametrize("clause", ["role", "versioning", "ownership", "change_discipline", "identity_is_the_pair"])
def test_an_empty_governance_clause_is_red(tmp_path, clause):
    errors = _plant(tmp_path, lambda d: d["governance"].update({clause: "  "}))
    assert any(clause in e for e in errors), errors


def test_a_renamed_enum_id_is_red(tmp_path):
    errors = _plant(tmp_path, lambda d: d.update(enum_id="claim_axes"))
    assert any("the filename says" in e for e in errors), errors


def test_an_unreadable_catalog_is_red_not_quietly_green(tmp_path):
    """Cross-file clauses must FAIL on an unreadable counterpart, never pass quietly — clause 6 is this
    validator's load-bearing cross-check."""
    errors = V.validate_enum(ENUM, tmp_path / "no-such-catalog", SKILLS).errors
    assert any("must not be reported green unrun" in e for e in errors), errors


# ── ADDITIVITY ────────────────────────────────────────────────────────────────────────────────────────
def test_the_enum_EXISTS_at_HEAD_so_the_additivity_teeth_are_not_vacuous():
    """★ The anti-vacuity guard for everything below it. `check_additivity` returns CLEAN when the file is
    absent at the ref — correctly, since there is nothing to be additive against — so every additivity
    tooth in this module passes vacuously until the enum is committed. That is exactly how the five of
    them below were first seen to be green while proving nothing. Named as its own test so the vacuity is
    a RED with an explanation, never a silent pass."""
    from validate_property_catalog import _git_show

    rel = ENUM.resolve().relative_to(V.REPO_ROOT).as_posix()
    assert _git_show("HEAD", rel) is not None, (
        f"{rel} does not exist at HEAD, so `check_additivity` short-circuits CLEAN and every additivity "
        f"test below is vacuous. Commit the enum first, then re-run — this is the 'commit first, then "
        f"re-probe any git-derived population' trap."
    )


def test_additivity_against_HEAD_is_clean():
    assert V.check_additivity(ENUM, "HEAD").errors == []


def test_additivity_on_an_unresolvable_ref_is_an_ERROR_not_a_skip():
    errors = V.check_additivity(ENUM, "definitely-not-a-ref-4f2a").errors
    assert any("refusing to report green on an unrun clause" in e for e in errors), errors


def test_additivity_runs_on_a_RELATIVE_enum_path(monkeypatch):
    """PR-0a shipped and caught the bug this pins: `relative_to` needs both sides absolute, so a relative
    path made the clause CRASH instead of run — and `preland.sh` passes it relative from cwd contracts/."""
    monkeypatch.chdir(CONTRACTS)
    assert V.check_additivity(Path("vocabularies/claim_axis.enum.yaml"), "HEAD").errors == []


def _additivity_errors(tmp_path, mutate) -> "list[str]":
    """Additivity compares the WORKING file against a git ref, so the mutant must be the working file.
    Planting it in tmp_path would put it outside the repo root and trip the `outside the repo root`
    guard instead of the clause under test — so the real file is swapped and restored.
    """
    original = ENUM.read_text()
    doc = copy.deepcopy(DOC)
    mutate(doc)
    try:
        ENUM.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True))
        return V.check_additivity(ENUM, "HEAD").errors
    finally:
        ENUM.write_text(original)


def test_additivity_reds_on_a_removed_pair(tmp_path):
    errors = _additivity_errors(tmp_path, lambda d: d["axes"].remove(_axis(d, "translational-readiness", "PDX")))
    assert any("pair(s) REMOVED" in e for e in errors), errors


def test_additivity_reds_on_a_changed_label(tmp_path):
    errors = _additivity_errors(tmp_path, lambda d: _axis(d, "immune-context", "IMMUNE").update(label="something else"))
    assert any("`label` changed" in e for e in errors), errors


def test_additivity_reds_on_a_flipped_critical_flag(tmp_path):
    errors = _additivity_errors(tmp_path, lambda d: _axis(d, "functional-requirement", "DEP").update(critical=False))
    assert any("`critical` flipped" in e for e in errors), errors


def test_additivity_reds_on_a_dropped_resolves_entry(tmp_path):
    errors = _additivity_errors(tmp_path, lambda d: _axis(d, "tumor-selectivity", "SAFE").update(resolves=[]))
    assert any("no longer resolves" in e for e in errors), errors


def test_additivity_reds_on_an_unbumped_addition(tmp_path):
    def mutate(d):
        d["axes"].append(
            {
                "skill": "immune-context",
                "axis_key": "NEW_AXIS",
                "label": "x",
                "informs": "x",
                "critical": False,
                "resolves": [],
                "resolves_pending": "x",
            }
        )

    errors = _additivity_errors(tmp_path, mutate)
    assert any("an additive change is a MINOR bump" in e for e in errors), errors


# ── DOCUMENTED DELIBERATE NON-FAILURES ────────────────────────────────────────────────────────────────
# What must stay GREEN, so the teeth above cannot ossify legitimate growth. Without these, the next
# person to add an axis cannot tell a real violation from a validator that forbids all change.
def test_adding_an_axis_with_a_version_bump_stays_green(tmp_path):
    def mutate(d):
        # A version STRICTLY above the committed one (now 1.2.0 after Wave-1b): the additivity half of
        # this test compares the mutated working file against HEAD, so the bump must clear HEAD's version
        # or the addition reads as unbumped and this "stays green" control would red for the wrong reason.
        d["version"] = "1.3.0"
        d["axes"].append(
            {
                "skill": "immune-context",
                "axis_key": "NEW_AXIS",
                "label": "a newly declared axis",
                "informs": "Does the new thing hold?\n",
                "critical": False,
                "resolves": [],
                "resolves_pending": "a future wave\n",
            }
        )
        d["skills"]["immune-context"]["axis_keys"].append("NEW_AXIS")

    assert _plant(tmp_path, mutate) == []
    assert _additivity_errors(tmp_path, mutate) == []


def test_an_absent_optional_note_stays_green(tmp_path):
    assert _plant(tmp_path, lambda d: d["properties"]["integrated_families.normal_liability"].pop("note")) == []


def test_dropping_the_whole_optional_tail_stays_green(tmp_path):
    """`coverage_dimensions`, `documented_collisions` and `related_ungoverned_vocabularies` are optional
    in shape — EXCEPT that a measured collision forces the second, which is asserted separately below so
    the two facts do not get confused."""

    def mutate(d):
        d.pop("coverage_dimensions")
        d.pop("related_ungoverned_vocabularies")

    assert _plant(tmp_path, mutate) == []


def test_removing_documented_collisions_entirely_is_RED_because_one_is_measured(tmp_path):
    errors = _plant(tmp_path, lambda d: d.pop("documented_collisions"))
    assert any("no `documented_collisions` block" in e for e in errors), errors


def test_an_axis_resolving_MORE_THAN_ONE_property_stays_green():
    """tumour-presence A resolves four. A registry that admitted only 1:1 joins would be the wrong shape:
    an axis aggregates a lens across modalities."""
    multi = [a for a in DOC["axes"] if len(a["resolves"]) > 1]
    assert len(multi) >= 3, multi
    assert len(_axis(DOC, "tumor-presence", "A")["resolves"]) == 4


def test_a_property_resolved_by_MORE_THAN_ONE_axis_stays_green():
    """The whole point of the file. If this ever became 1:1 there would be no alignment to record."""
    shared = {k: v for k, v in DOC["properties"].items() if len(v["resolved_by"]) > 1}
    assert len(shared) >= 3, sorted(DOC["properties"])


# ── GATE PARITY ───────────────────────────────────────────────────────────────────────────────────────
def test_gate_invocation_matches_preland_argv():
    """Invoke the validator EXACTLY as preland.sh does — cwd contracts/, the literal relative argv,
    nothing patched. Session 1 of this arc had four teeth pass while the real invocation was broken
    because they patched the layer underneath and passed absolute paths."""
    proc = subprocess.run(
        [
            sys.executable,
            "validators/validate_claim_axis.py",
            "--enum",
            "vocabularies/claim_axis.enum.yaml",
            "--catalog",
            "vocabularies/property_catalog",
            "--skills",
            "../skills",
        ],
        cwd=CONTRACTS,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, f"gate argv failed:\nstdout={proc.stdout}\nstderr={proc.stderr}"
    assert "15 skill(s), 61 axis pair(s), 60 distinct axis_key(s)" in proc.stdout, proc.stdout
    assert "1 collision(s) (DEP)" in proc.stdout, proc.stdout


def test_gate_invocation_with_additive_against_matches_preland_argv():
    proc = subprocess.run(
        [
            sys.executable,
            "validators/validate_claim_axis.py",
            "--enum",
            "vocabularies/claim_axis.enum.yaml",
            "--catalog",
            "vocabularies/property_catalog",
            "--skills",
            "../skills",
            "--additive-against",
            "HEAD",
        ],
        cwd=CONTRACTS,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, f"gate argv failed:\nstdout={proc.stdout}\nstderr={proc.stderr}"


def test_the_two_gate_argv_tests_match_what_preland_sh_ACTUALLY_RUNS():
    """The two tests above hardcode the argv they BELIEVE the gate uses — so if someone edits
    `preland.sh` they keep passing while testing an invocation that no longer exists, which is the very
    thing "invoke it exactly as the gate does" was meant to prevent. This reads the script and pins BOTH
    wired lines to the flags those tests pass. Deliberately a SUBSTRING check on flags, not whole-line
    equality: the label column and line continuations are formatting, and pinning those would red on a
    reindent. Join backslash continuations FIRST or the additivity invocation, wrapped over three lines,
    is found nowhere and this test reds on formatting."""
    script = (CONTRACTS / "scripts" / "preland.sh").read_text().replace("\\\n", " ")
    wired = [
        " ".join(ln.split())
        for ln in script.splitlines()
        if "validate_claim_axis.py" in ln and not ln.lstrip().startswith("#")
    ]
    assert len(wired) == 2, (
        f"expected the validator wired TWICE in preland.sh (pool shape clauses + additivity), found "
        f"{len(wired)}: {wired}"
    )
    shape, additivity = wired[0], wired[1]
    for flag in (
        "--enum vocabularies/claim_axis.enum.yaml",
        "--catalog vocabularies/property_catalog",
        "--skills ../skills",
    ):
        assert flag in shape, f"preland.sh shape line is missing {flag!r}; the gate-argv test is now fiction"
    assert "--additive-against" in additivity, (
        "the second wiring must pass --additive-against, otherwise the pair-additivity clause never runs "
        "in the gate and this registry is governed in name only"
    )
    for flag in ("--catalog vocabularies/property_catalog", "--skills ../skills"):
        assert flag in additivity, (
            f"the additivity line must ALSO pass {flag!r}: it validates the shape clauses on the way "
            f"through, and a missing path there degrades clause 6 to a reported-but-unrun cross-check"
        )
