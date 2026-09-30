"""comparability_state enum validator tests — population conformance PLUS mutation teeth.

The same two halves as its 0a/0b siblings, and the second is again the load-bearing one:

  * POPULATION — the committed vocabularies/comparability_state.enum.yaml passes every clause, and the
    design decisions it records are pinned as FACTS rather than left in prose: exactly one family is
    piloted, all 13 are declared, and `normalized_to_compare` is declared by 3 families while emitted
    by none. contracts/tests/ is collected wholesale by the `contracts-pytest` job with no path
    filter, so a regression reds trunk here without needing a workflow edit.

  * TEETH — each clause is exercised against a PLANTED defect and asserted RED with a SPECIFIC error
    substring. A validator nobody has watched fail is not a validator.

The three anti-patterns arc #2210 has already paid for are avoided here too:

  1. A validator that RAISES is not a validator that FAILS — preland.sh prints `FAIL <label>`
     identically for "found a violation" and "crashed on line 1".
     `test_unparseable_enum_fails_rather_than_crashes` pins the difference.
  2. Monkeypatching the layer beneath a clause hides the clause.
     `test_gate_invocation_matches_preland_argv` and `test_additivity_runs_on_a_RELATIVE_enum_path`
     invoke the validator EXACTLY as the gate does — cwd contracts/, relative paths, the literal argv —
     with nothing patched.
  3. Per SK#2091 nothing here asserts verdict inertness, and every test below was proven able to fail by
     planting its mutant before it was committed. One of them (`comparability_state` emitted where the
     enum says the key is omitted) was found to be a REAL HOLE that way and is now covered on the skills
     side by test_comparability_state_coverage.py — a mutant that survives is information.

A note on what is NOT tested, deliberately: the validator does not compare a family's `basis` against
the catalog's `integration.comparability` PROSE, and neither does this file. Prose is not
machine-comparable, and a substring-matching clause would be green-for-the-wrong-reason theatre that
ossified wording rather than checking meaning. `basis` is an audit trail for a human; its REQUIRED
NON-EMPTINESS is what is enforced.
"""

from __future__ import annotations

import copy
import importlib.util
import subprocess
import sys
from pathlib import Path

import yaml

CONTRACTS = Path(__file__).resolve().parents[2]
VALIDATORS = CONTRACTS / "validators"
ENUM = CONTRACTS / "vocabularies" / "comparability_state.enum.yaml"
FAMILIES = CONTRACTS / "vocabularies" / "property_catalog" / "integrated_families.yaml"
CONCORDANCE = CONTRACTS / "vocabularies" / "concordance_class.enum.yaml"

# The validator imports its helpers from its sibling, so validators/ must be importable. This mirrors
# what running it as a script does implicitly (sys.path[0] = the script's directory).
if str(VALIDATORS) not in sys.path:
    sys.path.insert(0, str(VALIDATORS))


def _load_validator():
    path = VALIDATORS / "validate_comparability_state.py"
    spec = importlib.util.spec_from_file_location("validate_comparability_state", path)
    mod = importlib.util.module_from_spec(spec)
    # Register BEFORE exec: @dataclass resolves its annotations through sys.modules[cls.__module__],
    # and Report is imported from the sibling module, which is itself loaded this way.
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


V = _load_validator()
DOC = yaml.safe_load(ENUM.read_text())


def _plant(tmp_path: Path, mutate) -> "list[str]":
    """Deep-copy the real enum, plant EXACTLY ONE defect, validate, return the errors.

    The temp file keeps the real filename: `enum_id` must equal the filename stem, so a renamed temp
    file would red every mutant for the wrong reason — and would red the clean control below too, which
    is how you find out.
    """
    doc = copy.deepcopy(DOC)
    mutate(doc)
    p = tmp_path / ENUM.name
    p.write_text(yaml.safe_dump(doc, sort_keys=False))
    return V.validate_enum(p, FAMILIES, CONCORDANCE).errors


def _assert_red(errors, *substrings):
    assert errors, "the planted defect produced NO error — the clause is inert"
    blob = " | ".join(errors)
    for s in substrings:
        assert s in blob, f"expected {s!r} in the errors, got: {blob[:600]}"


# ==================================================================================================
# POPULATION — the committed file, and the design facts it records
# ==================================================================================================
def test_committed_enum_passes_every_clause():
    r = V.validate_enum(ENUM, FAMILIES, CONCORDANCE)
    assert r.ok, f"committed {ENUM.name} has errors: {r.errors}"


def test_control_a_deep_copied_unmutated_doc_is_green(tmp_path):
    """The control for every teeth test below. If the round-trip itself reddened, each mutant would be
    red for the wrong reason and the whole file would prove nothing."""
    assert _plant(tmp_path, lambda d: None) == []


def test_every_l2b_family_in_the_catalog_has_a_declared_state():
    catalog = yaml.safe_load(FAMILIES.read_text())["families"]
    assert set(DOC["families"]) == set(catalog), (
        f"roster drift: undeclared {sorted(set(catalog) - set(DOC['families']))}, "
        f"unknown {sorted(set(DOC['families']) - set(catalog))}"
    )
    assert len(DOC["families"]) == 13, f"expected 13 L2b families, found {len(DOC['families'])}"


def test_exactly_one_family_is_piloted_and_it_is_recurrence():
    """0c pilots ONE family by design (it may add no family and touch no golden). Pinned as a fact so a
    later session cannot quietly widen the pilot without this test, and its reviewer, noticing."""
    piloted = sorted(f for f, s in DOC["families"].items() if s["emission"] == "piloted")
    assert piloted == ["recurrence"], f"expected exactly ['recurrence'] piloted, found {piloted}"
    declared_only = [f for f, s in DOC["families"].items() if s["emission"] == "declared_only"]
    assert len(declared_only) == 12, f"expected 12 declared_only families, found {len(declared_only)}"


def test_all_three_states_have_at_least_one_declared_family():
    """The design question this file was built to answer. A three-token enum whose middle token no family
    can reach would be the wrong shape; `normalized_to_compare` has 3 declared families, so it is
    unemitted-but-instantiated rather than hypothetical."""
    for entry in DOC["values"]:
        assert entry["families"], f"state {entry['value']!r} has no declared family"
    by_state = {e["value"]: e["families"] for e in DOC["values"]}
    assert sorted(by_state) == ["comparable", "non_comparable", "normalized_to_compare"]
    assert len(by_state["normalized_to_compare"]) == 3, (
        f"expected 3 normalized_to_compare families, found {by_state['normalized_to_compare']}"
    )


def test_the_pilot_map_is_exhaustive_over_the_concordance_tokens():
    """(family, token) is the unit of identity — 0b measured that `single_source_only` is emitted by 5
    families and means something different in each. So the pilot's map must cover exactly the tokens of
    ITS family, resolved from the 0b enum rather than restated here."""
    rec = DOC["families"]["recurrence"]
    tokens = set(yaml.safe_load(CONCORDANCE.read_text())["families"]["recurrence"]["tokens"])
    covered = set(rec["per_concordance_class"]) | set(rec["omits_state_for"])
    assert covered == tokens, f"uncovered {sorted(tokens - covered)}, unknown {sorted(covered - tokens)}"
    assert set(rec["per_concordance_class"]) & set(rec["omits_state_for"]) == set()
    assert "single_source_only" in rec["omits_state_for"], (
        "single_source_only must OMIT the key — no comparison was attempted, so there is no relation to gate"
    )


def test_documented_not_emitted_matches_the_declared_only_reality():
    dne = {e["state"] for e in DOC["documented_not_emitted"]}
    assert dne == {"normalized_to_compare"}, dne
    entry = DOC["documented_not_emitted"][0]
    assert "abundance" in entry["named_in"], "the candidate emitter must be NAMED, not left implicit"


def test_no_coverage_dimension_claims_to_be_a_gate():
    for d in DOC["coverage_dimensions"]:
        assert d["is_a_gate"] is False, f"{d['dimension']}: dimensions are reported, never enforced"


# ==================================================================================================
# TEETH — one planted defect per clause
# ==================================================================================================
def test_clause1_unknown_top_level_key_is_red(tmp_path):
    _assert_red(_plant(tmp_path, lambda d: d.update({"comparabilty_state": "typo"})), "unknown key")


def test_clause1_enum_id_must_match_the_filename(tmp_path):
    _assert_red(_plant(tmp_path, lambda d: d.update({"enum_id": "something_else"})), "enum_id")


def test_clause1_non_semver_version_is_red(tmp_path):
    _assert_red(_plant(tmp_path, lambda d: d.update({"version": "1.0"})), "semver")


def test_clause1_empty_criterion_is_red(tmp_path):
    """`criterion` is required NON-EMPTY because it is the only thing keeping 13 independent readings of
    `comparable` vs `normalized_to_compare` consistent. An enum that classified without stating its rule
    would be 13 opinions."""
    _assert_red(_plant(tmp_path, lambda d: d.update({"criterion": "   "})), "criterion")


def test_clause1_missing_governance_clause_is_red(tmp_path):
    _assert_red(_plant(tmp_path, lambda d: d["governance"].pop("declaration_is_not_emission")), "governance")


def test_clause2_indexes_that_disagree_are_red(tmp_path):
    def mutate(d):
        d["values"][0]["families"].remove("essentiality")

    _assert_red(_plant(tmp_path, mutate), "indexes disagree")


def test_clause3_an_undeclared_catalog_family_is_red(tmp_path):
    """The load-bearing clause: a peer epic adding a 14th L2b family must RED here rather than leave a
    silent coverage gap. An undeclared family is a FALSE ABSENCE."""
    _assert_red(_plant(tmp_path, lambda d: d["families"].pop("essentiality")), "NO comparability_state declared")


def test_clause3_a_family_absent_from_the_catalog_is_red(tmp_path):
    def mutate(d):
        d["families"]["invented_family"] = {
            "emission": "declared_only",
            "states": ["comparable"],
            "basis": "x",
        }
        d["values"][0]["families"].append("invented_family")

    _assert_red(_plant(tmp_path, mutate), "absent from integrated_families.yaml")


def test_clause3_unreadable_catalog_is_red_not_skipped(tmp_path):
    """A cross-file clause that cannot read its counterpart must FAIL, never pass quietly. This is the
    fail-open shape the arc keeps finding: the check reports green having examined nothing."""
    p = tmp_path / ENUM.name
    p.write_text(ENUM.read_text())
    errors = V.validate_enum(p, tmp_path / "does_not_exist.yaml", CONCORDANCE).errors
    _assert_red(errors, "load-bearing clause and must not be skipped")


def test_clause4_missing_basis_is_red(tmp_path):
    """A declaration read from prose with no citation is unauditable, and 12 of 13 are exactly that."""
    _assert_red(_plant(tmp_path, lambda d: d["families"]["abundance"].pop("basis")), "missing `basis`")


def test_clause4_unknown_emission_value_is_red(tmp_path):
    _assert_red(_plant(tmp_path, lambda d: d["families"]["abundance"].update({"emission": "sort_of"})), "emission")


def test_clause4_a_state_outside_the_roster_is_red(tmp_path):
    def mutate(d):
        d["families"]["abundance"]["states"] = ["made_up_state"]

    _assert_red(_plant(tmp_path, mutate), "not in the `values` roster")


def test_clause5_declared_only_family_carrying_a_pilot_map_is_red(tmp_path):
    """Declaration is not emission. A per-claim resolution map on a family whose builder emits nothing
    claims a resolution no code performs — a false claim of coverage."""

    def mutate(d):
        d["families"]["abundance"]["per_concordance_class"] = {"abundance_concordant": ["normalized_to_compare"]}

    _assert_red(_plant(tmp_path, mutate), "may NOT carry", "Declaration is not emission")


def test_clause5_piloted_family_missing_its_map_is_red(tmp_path):
    _assert_red(
        _plant(tmp_path, lambda d: d["families"]["recurrence"].pop("per_concordance_class")),
        "requires `per_concordance_class`",
    )


def test_clause5_piloted_family_missing_its_gate_rule_is_red(tmp_path):
    _assert_red(_plant(tmp_path, lambda d: d["families"]["recurrence"].pop("gate_rule")), "requires `gate_rule`")


def test_clause6_a_token_with_no_comparability_decision_is_red(tmp_path):
    """A new fold outcome with no comparability licence must not pass — which also means a peer adding a
    token to a piloted family is RED here until its comparability is decided. That is the point."""
    _assert_red(
        _plant(tmp_path, lambda d: d["families"]["recurrence"]["per_concordance_class"].pop("exome_masks_recurrence")),
        "have no comparability decision",
    )


def test_clause6_a_token_from_another_family_is_red(tmp_path):
    """(family, token), never the bare token."""

    def mutate(d):
        d["families"]["recurrence"]["per_concordance_class"]["abundance_concordant"] = ["comparable"]

    _assert_red(_plant(tmp_path, mutate), "not `concordance_class` tokens of family", "(family, token)")


def test_clause6_a_token_both_mapped_and_omitted_is_red(tmp_path):
    def mutate(d):
        d["families"]["recurrence"]["omits_state_for"].append("panel_masks_recurrence")

    _assert_red(_plant(tmp_path, mutate), "BOTH")


def test_clause6_an_unreachable_declared_state_is_red(tmp_path):
    """NOTE the shape of this mutation. Dropping `non_comparable` from ONE token's list leaves it
    reachable via another and is INERT — the first draft of this test did exactly that and passed while
    proving nothing. To create genuine unreachability every token must be redirected."""

    def mutate(d):
        pcc = d["families"]["recurrence"]["per_concordance_class"]
        pcc["recurrence_concordant"] = ["comparable"]
        pcc["panel_masks_recurrence"] = ["comparable"]

    _assert_red(_plant(tmp_path, mutate), "no `concordance_class` token resolves to them")


def test_clause6_unreadable_concordance_enum_is_red_not_skipped(tmp_path):
    p = tmp_path / ENUM.name
    p.write_text(ENUM.read_text())
    errors = V.validate_enum(p, FAMILIES, tmp_path / "no_such_enum.yaml").errors
    _assert_red(errors, "cannot be reported green on an unrun cross-check")


def test_clause7_an_orphan_value_nobody_declares_is_red(tmp_path):
    def mutate(d):
        d["values"].append({"value": "orphan_state", "definition": "x", "admits": "y", "families": ["abundance"]})

    # `abundance` does not list it in `states`, so this is an index disagreement AND an orphan.
    _assert_red(_plant(tmp_path, mutate), "indexes disagree")


def test_clause8_a_state_with_no_families_is_red(tmp_path):
    _assert_red(_plant(tmp_path, lambda d: d["values"][1].update({"families": []})), "unreachable vocabulary")


def test_clause9_a_floor_above_the_measured_population_is_red(tmp_path):
    _assert_red(
        _plant(tmp_path, lambda d: d["population_floors"].update({"family_state_pairs": 99})),
        "population SHRANK",
    )


def test_clause9_family_floor_must_equal_the_catalog_count(tmp_path):
    _assert_red(
        _plant(tmp_path, lambda d: d["population_floors"].update({"families": 12})),
        "pinned to EQUALITY with the catalog",
    )


def test_clause9_a_zero_piloted_floor_is_red(tmp_path):
    """At zero piloted families every reconciliation in the skills-side suite examines nothing while
    staying green — the floor is what stops the suite going quietly vacuous."""
    _assert_red(
        _plant(tmp_path, lambda d: d["population_floors"].update({"piloted_families": 0})),
        "must be >= 1",
    )


def test_clause10_a_dimension_claiming_to_be_a_gate_is_red(tmp_path):
    _assert_red(
        _plant(tmp_path, lambda d: d["coverage_dimensions"][0].update({"is_a_gate": True})),
        "must be present and exactly `false`",
    )


def test_clause10_documented_not_emitted_needs_a_named_family(tmp_path):
    _assert_red(
        _plant(tmp_path, lambda d: d["documented_not_emitted"][0].update({"named_in": []})),
        "hypothetical after all",
    )


def test_unparseable_enum_fails_rather_than_crashes(tmp_path):
    """A validator that RAISES is not a validator that FAILS: preland.sh prints `FAIL <label>`
    identically for both, so the distinction is invisible exactly when it matters."""
    p = tmp_path / ENUM.name
    p.write_text("enum_id: [unclosed\n")
    r = V.validate_enum(p, FAMILIES, CONCORDANCE)  # must not raise
    _assert_red(r.errors, "could not be read as YAML")


# ==================================================================================================
# ADDITIVITY (clause 11)
# ==================================================================================================
def test_additivity_rejects_an_unresolvable_ref(tmp_path):
    r = V.check_additivity(ENUM, "definitely-not-a-ref-8f3a")
    _assert_red(r.errors, "does not resolve", "refusing to report green on an unrun clause")


def test_additivity_against_head_is_green_when_nothing_changed():
    """HEAD contains this file as committed, so the working copy is trivially additive against it. On the
    PR that introduces the file, `_git_show` returns None (new file) and the clause is a no-op — which is
    correct, not a skip: there is nothing to be additive against."""
    r = V.check_additivity(ENUM, "HEAD")
    assert r.ok, r.errors


def test_additivity_runs_on_a_RELATIVE_enum_path(monkeypatch):
    """preland.sh and CI pass a RELATIVE path from cwd contracts/. `relative_to` needs both sides
    absolute, so without the resolve() in check_additivity this CRASHES instead of running — the bug 0a
    shipped. Nothing is patched but the cwd."""
    monkeypatch.chdir(CONTRACTS)
    r = V.check_additivity(Path("vocabularies") / ENUM.name, "HEAD")
    assert r.ok, r.errors


def test_gate_invocation_matches_preland_argv():
    """Invoke the validator EXACTLY as preland.sh does — cwd contracts/, the literal relative argv,
    nothing patched. Session 1 of this arc had four teeth pass while the real invocation was broken
    because they patched the layer underneath and passed absolute paths."""
    proc = subprocess.run(
        [
            sys.executable,
            "validators/validate_comparability_state.py",
            "--enum",
            "vocabularies/comparability_state.enum.yaml",
            "--families",
            "vocabularies/property_catalog/integrated_families.yaml",
            "--concordance-enum",
            "vocabularies/concordance_class.enum.yaml",
        ],
        cwd=CONTRACTS,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, f"gate argv failed:\nstdout={proc.stdout}\nstderr={proc.stderr}"
    assert "1 piloted (recurrence)" in proc.stdout, proc.stdout


def test_gate_invocation_with_additive_against_matches_preland_argv():
    proc = subprocess.run(
        [
            sys.executable,
            "validators/validate_comparability_state.py",
            "--enum",
            "vocabularies/comparability_state.enum.yaml",
            "--families",
            "vocabularies/property_catalog/integrated_families.yaml",
            "--concordance-enum",
            "vocabularies/concordance_class.enum.yaml",
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
    """The gap in the habit, closed. The two tests above hardcode the argv they believe the gate uses —
    so if someone edits `preland.sh` they keep passing while testing an invocation that no longer exists,
    which is the very thing "invoke it exactly as the gate does" was meant to prevent. This reads the
    script and pins BOTH wired lines to the flags those tests pass. It is deliberately a SUBSTRING check
    on flags, not a whole-line equality: the label column and line continuations are formatting, and
    pinning those would red on a reindent."""
    # Join backslash continuations FIRST. The additivity invocation is wrapped over four lines, so a
    # naive per-line scan finds `--additive-against` nowhere and this test would red on formatting — the
    # first draft of it did exactly that.
    script = (CONTRACTS / "scripts" / "preland.sh").read_text().replace("\\\n", " ")
    wired = [
        " ".join(ln.split())
        for ln in script.splitlines()
        if "validate_comparability_state.py" in ln and not ln.lstrip().startswith("#")
    ]
    assert len(wired) == 2, (
        f"expected the validator wired TWICE in preland.sh (pool shape clauses + additivity), found "
        f"{len(wired)}: {wired}"
    )
    shape, additivity = wired[0], wired[1]
    for flag in (
        "--enum vocabularies/comparability_state.enum.yaml",
        "--families vocabularies/property_catalog/integrated_families.yaml",
        "--concordance-enum vocabularies/concordance_class.enum.yaml",
    ):
        assert flag in shape, f"preland.sh shape line is missing {flag!r}; the gate-argv test is now fiction"
    assert "--additive-against" in additivity, (
        "the second wiring must pass --additive-against, otherwise the token-additivity clause never runs "
        "in the gate and this vocabulary is governed in name only"
    )
    assert "--concordance-enum" in additivity, (
        "the additivity line must ALSO pass --concordance-enum: it validates the shape clauses on the way "
        "through, and a missing path there degrades clause 6 to a reported-but-unrun cross-check"
    )


def test_missing_enum_file_exits_nonzero_rather_than_silently_passing():
    proc = subprocess.run(
        [sys.executable, "validators/validate_comparability_state.py", "--enum", "vocabularies/nope.enum.yaml"],
        cwd=CONTRACTS,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 1, proc.stdout
    assert "does not exist" in proc.stdout


# ==================================================================================================
# DELIBERATE NON-FAILURES — what must stay GREEN, so the teeth cannot ossify legitimate change
# ==================================================================================================
def test_nonfailure_adding_a_state_with_a_version_bump_is_green(tmp_path):
    """Growing the vocabulary is the SUPPORTED change. If this went red the enum would be frozen, and a
    frozen governance file gets worked around rather than updated."""

    def mutate(d):
        d["version"] = "1.1.0"
        d["values"].append(
            {
                "value": "comparable_after_restriction",
                "definition": "x",
                "admits": "y",
                "families": ["abundance"],
            }
        )
        d["families"]["abundance"]["states"].append("comparable_after_restriction")
        d["population_floors"]["distinct_states"] = 4

    assert _plant(tmp_path, mutate) == []


def test_nonfailure_a_declared_only_family_may_omit_the_optional_note(tmp_path):
    assert _plant(tmp_path, lambda d: d["families"]["tumor_presence"].pop("note")) == []


def test_nonfailure_several_families_sharing_one_state_is_green():
    """10 families share `comparable`. The state roster is not a partition of the families and must never
    be validated as one."""
    comparable = [e for e in DOC["values"] if e["value"] == "comparable"][0]
    assert len(comparable["families"]) == 10, comparable["families"]
    assert V.validate_enum(ENUM, FAMILIES, CONCORDANCE).ok


def test_nonfailure_a_family_may_declare_more_than_one_state(tmp_path):
    """4 families declare both `comparable` and `non_comparable`. Comparability is per-case, so a
    multi-state declaration is the normal shape and not a contradiction to be linted away."""
    multi = sorted(f for f, s in DOC["families"].items() if len(s["states"]) > 1)
    assert multi == ["coverage", "normal_liability", "recurrence", "subtype_restriction"], multi
    assert _plant(tmp_path, lambda d: None) == []
