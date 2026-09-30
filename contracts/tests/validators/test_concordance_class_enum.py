"""concordance_class enum validator tests — population conformance PLUS mutation teeth.

Same two halves as test_property_catalog.py, and the second is again the load-bearing one:

  * POPULATION — the committed vocabularies/concordance_class.enum.yaml passes every clause, and the
    design decision it records (`contradicts` admitted as declared-but-not-emitted-by-a-family-fold,
    with a named witness) is pinned as a fact rather than left in prose. contracts/tests/ is
    collected wholesale by the `contracts-pytest` job with no path filter, so a regression reds trunk
    here without needing a workflow edit.

  * TEETH — each clause is exercised against a PLANTED defect and asserted RED, with a SPECIFIC error
    substring. A validator nobody has watched fail is not a validator. Every teeth test names the
    real failure it defends against.

Three deliberate anti-patterns are avoided, each because session 1 of arc #2210 paid for it:

  1. A validator that RAISES is not a validator that FAILS — preland.sh prints `FAIL <label>`
     identically for "found a violation" and "crashed on line 1". `test_unparseable_enum_fails_rather
     _than_crashes` pins the difference.
  2. Monkeypatching the layer beneath a clause hides the clause. Four of 0a's additivity teeth passed
     while the real invocation was broken. So `test_gate_invocation_matches_preland_argv` and
     `test_additivity_runs_on_a_RELATIVE_enum_path` invoke the validator EXACTLY as the gate does —
     cwd contracts/, relative paths, the literal argv — with nothing patched.
  3. Per SK#2091, nothing here asserts verdict inertness, and every test below was proven able to
     fail by planting its mutant before it was committed.
"""

from __future__ import annotations

import copy
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[3]
CONTRACTS = Path(__file__).resolve().parents[2]
VALIDATORS = CONTRACTS / "validators"
ENUM = CONTRACTS / "vocabularies" / "concordance_class.enum.yaml"
FAMILIES = CONTRACTS / "vocabularies" / "property_catalog" / "integrated_families.yaml"

# The validator imports its helpers from its sibling, so validators/ must be importable. This mirrors
# what running it as a script does implicitly (sys.path[0] = the script's directory).
if str(VALIDATORS) not in sys.path:
    sys.path.insert(0, str(VALIDATORS))


def _load_validator():
    path = VALIDATORS / "validate_concordance_enum.py"
    spec = importlib.util.spec_from_file_location("validate_concordance_enum", path)
    mod = importlib.util.module_from_spec(spec)
    # Register BEFORE exec: @dataclass resolves its annotations through sys.modules[cls.__module__],
    # and Report is imported from the sibling module, which is itself loaded this way.
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


V = _load_validator()
DOC = yaml.safe_load(ENUM.read_text())


def _pairs(doc) -> set:
    return V._pairs_from_families(doc.get("families") or {}) | V._pairs_from_values(doc.get("values") or [])


def _plant(tmp_path: Path, mutate) -> "list[str]":
    """Deep-copy the real enum, plant EXACTLY ONE defect, validate, return the errors.

    The temp file keeps the real filename: `enum_id` must equal the filename stem, so a renamed temp
    file would red every mutant for the wrong reason and the clean control below would red too.
    """
    doc = copy.deepcopy(DOC)
    mutate(doc)
    path = tmp_path / ENUM.name
    path.write_text(yaml.safe_dump(doc, sort_keys=False))
    return V.validate_enum(path, FAMILIES).errors


def _first_family(doc) -> str:
    return next(iter(doc["families"]))


def _relation(doc, name: str) -> dict:
    return next(e for e in doc["relations"]["values"] if e["relation"] == name)


# --------------------------------------------------------------------------- population


def test_enum_population_is_not_vacuous():
    """Anti-vacuity floor. Without it, a file that lost its `values` block would make the mutation
    tests below plant defects into nothing and the module would pass while checking nothing."""
    assert len(DOC["families"]) == 13, f"expected 13 families, found {sorted(DOC['families'])}"
    assert len(DOC["values"]) >= 40, f"expected >= 40 tokens, found {len(DOC['values'])}"
    assert len(_pairs(DOC)) >= 40, f"expected >= 40 (family, token) pairs, found {len(_pairs(DOC))}"
    assert V.VALID_RELATIONS, "the relation vocabulary did not import — clause 3 would be inert"


def test_committed_enum_validates():
    r = V.validate_enum(ENUM, FAMILIES)
    assert r.ok, "committed enum:\n  " + "\n  ".join(r.errors)


def test_clean_roundtrip_is_green(tmp_path):
    """Control for every mutation test below: the unmutated deep-copy must be silent, or their REDs
    would not be attributable to the defect each one planted."""
    assert _plant(tmp_path, lambda doc: None) == []


def test_gate_invocation_matches_preland_argv(monkeypatch, capsys):
    """Invoke the validator EXACTLY as contracts/scripts/preland.sh does — cwd contracts/, RELATIVE
    paths, the literal argv — with nothing monkeypatched.

    0a shipped four additivity teeth that all passed while the real invocation crashed, because they
    patched the layer beneath the clause and passed an absolute module constant. Relative-vs-absolute
    path arithmetic is invisible to a test that never uses a relative path.
    """
    monkeypatch.chdir(CONTRACTS)
    rc = V._main(
        [
            "--enum",
            "vocabularies/concordance_class.enum.yaml",
            "--families",
            "vocabularies/property_catalog/integrated_families.yaml",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0, out
    # And it must have actually examined the population, not short-circuited into a green.
    assert "13 famil(ies)" in out, out
    assert "48 (family, token) pair(s)" in out, out


def test_gate_invocation_via_subprocess_matches_preland_argv():
    """The A test in the STRICT arc-§2.6 sense: shell the validator out as a SUBPROCESS with the
    literal relative argv from cwd contracts/, nothing patched. The `_main(...)` test above proves the
    argv PARSES and the clauses run under a relative cwd, but NOT the `__main__` entrypoint / process
    boundary the gate actually crosses (`python validators/validate_concordance_enum.py …`) — and a
    test that calls the checker in-process is not an A test (arc trap §2.6, quoted by #2244). #2247's
    roster reconciliation requires this subprocess form; without it concordance is the one wired
    validator whose argv coverage is weaker than its four siblings'."""
    proc = subprocess.run(
        [
            sys.executable,
            "validators/validate_concordance_enum.py",
            "--enum",
            "vocabularies/concordance_class.enum.yaml",
            "--families",
            "vocabularies/property_catalog/integrated_families.yaml",
        ],
        cwd=CONTRACTS,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, f"gate argv failed:\nstdout={proc.stdout}\nstderr={proc.stderr}"


def test_additivity_runs_on_a_RELATIVE_enum_path(monkeypatch):
    """The additivity clause resolves the enum path against the REPO root while the argument arrives
    relative to contracts/. Without `resolve()` before `relative_to()` this raises ValueError and the
    clause is UNRUN while preland.sh still prints FAIL — indistinguishable from a real violation."""
    monkeypatch.chdir(CONTRACTS)
    r = V.check_token_additivity(Path("vocabularies/concordance_class.enum.yaml"), "HEAD")
    assert not any("resolves outside the repo root" in e for e in r.errors), r.errors
    # Nor may it have taken the anti-fail-open exit: HEAD resolves in any git checkout, so a
    # "does not resolve" here would mean the clause silently declined to compare.
    assert not any("does not resolve" in e for e in r.errors), r.errors


def test_the_two_gate_argv_tests_match_what_preland_sh_ACTUALLY_RUNS():
    """Backfill of the 0c habit (test_comparability_state_enum.py). The two tests above — this file's
    `test_gate_invocation_matches_preland_argv` and `test_additivity_runs_on_a_RELATIVE_enum_path` —
    hardcode the argv they believe the gate uses. If someone edits preland.sh, they keep passing while
    testing an invocation that no longer exists: green for the wrong reason. This reads the script and
    pins BOTH wired lines to the flags those tests assume. Deliberately a SUBSTRING check on flags, not
    whole-line equality — the label column and line continuations are formatting.
    """
    # Join backslash continuations FIRST, or this reds on formatting rather than a real drift.
    script = (CONTRACTS / "scripts" / "preland.sh").read_text().replace("\\\n", " ")
    wired = [
        " ".join(ln.split())
        for ln in script.splitlines()
        if "validate_concordance_enum.py" in ln and not ln.lstrip().startswith("#")
    ]
    assert len(wired) == 2, (
        f"expected the validator wired TWICE in preland.sh (pool shape clause + additivity), found "
        f"{len(wired)}: {wired}"
    )
    shape, additivity = wired[0], wired[1]
    for flag in (
        "--enum vocabularies/concordance_class.enum.yaml",
        "--families vocabularies/property_catalog/integrated_families.yaml",
    ):
        assert flag in shape, (
            f"preland.sh shape line is missing {flag!r}; test_gate_invocation_matches_preland_argv is now fiction"
        )
    assert "--additive-against" in additivity, (
        "the second wiring must pass --additive-against, otherwise the token-additivity clause never runs "
        "in the gate and this vocabulary is governed in name only"
    )


def test_relation_block_names_the_whole_dependence_vocabulary():
    """Clause 3 as a population fact. A subset would let a relation be dropped from the enum while
    dependence_edges.py still emits it — a coverage gap that reads as a clean file."""
    named = {e["relation"] for e in DOC["relations"]["values"]}
    assert named == set(V.VALID_RELATIONS), f"enum names {sorted(named)}, code declares {sorted(V.VALID_RELATIONS)}"


def test_contradicts_is_admitted_as_unemitted_with_a_live_witness():
    """The arc #2210 Wave-0b design decision, pinned.

    `contradicts` is reachable in landed production code but NOT from any L2b family fold. The prior
    recorded premise ("no landed builder emits contradicts") was false as stated; the scoping is what
    makes it true. This test pins BOTH halves, because an absence-assertion whose scope is unwritten
    is the one that goes vacuous: the witness must keep naming a function that exists, so the day a
    family legitimately gains an opposed arm, this reds and forces the decision to be re-made rather
    than silently inherited.
    """
    entry = _relation(DOC, "contradicts")
    assert entry["emitted_by_family_folds"] is False
    assert entry["dispositions"] == []
    witness = entry["emitted_outside_family_folds_by"]
    assert witness["builder"] == "skills/_skills_common/presence_claims.py"
    assert witness["builder_function"] == "_provider_call_corroboration"
    assert witness["emits_field"] == "concordance", "the witness emits `concordance`, NOT `concordance_class`"
    # The witness is only worth having if it still exists. This is the half that rots.
    defs = V._toplevel_defs(REPO / witness["builder"])
    assert defs is not None and witness["builder_function"] in defs, witness


def test_no_coverage_dimension_is_a_gate():
    """A dimension is a count emitted as data. The moment one becomes a gate it starts asserting an
    absence, and an absence-assertion that goes vacuous reads as a pass."""
    for dim in DOC["coverage_dimensions"]:
        assert dim["is_a_gate"] is False, dim["dimension"]
        assert dim.get("rationale", "").strip(), f"{dim['dimension']}: a non-gate needs its reason recorded"


def test_every_token_resolves_to_a_declared_disposition_and_relation():
    """Population form of clause 4's inverse check: each token's disposition maps to exactly one
    dependence relation, and that relation is one the code declares."""
    disp_relation = {d["disposition"]: d["dependence_relation"] for d in DOC["dispositions"]}
    for entry in DOC["values"]:
        rel = disp_relation[entry["disposition"]]
        assert rel in V.VALID_RELATIONS, (entry["value"], rel)


# --------------------------------------------------------------------------- teeth: shape


def test_teeth_unknown_key_is_red(tmp_path):
    """Strict keys. A misspelled `dispostion:` would otherwise be silently ignored — a fail-open on
    the one discipline this file carries."""
    errs = _plant(tmp_path, lambda doc: doc["values"][0].update({"dispostion": "concordant"}))
    assert any("unknown key `dispostion`" in e for e in errs), errs


def test_teeth_enum_id_not_matching_filename_is_red(tmp_path):
    errs = _plant(tmp_path, lambda doc: doc.update({"enum_id": "something_else"}))
    assert any("but the filename stem is" in e for e in errs), errs


def test_teeth_non_semver_version_is_red(tmp_path):
    errs = _plant(tmp_path, lambda doc: doc.update({"version": "1.0"}))
    assert any("must be semver" in e for e in errs), errs


def test_teeth_empty_governance_clause_is_red(tmp_path):
    errs = _plant(tmp_path, lambda doc: doc["governance"].update({"change_discipline": "   "}))
    assert any("`change_discipline` must be a non-empty string" in e for e in errs), errs


def test_teeth_unparseable_enum_fails_rather_than_crashes(tmp_path):
    """A validator that RAISES is not a validator that FAILS. preland.sh cannot tell the difference,
    so the difference has to be pinned here."""
    path = tmp_path / ENUM.name
    path.write_text("values: [\n  - broken: {: :\n")
    r = V.validate_enum(path, FAMILIES)  # must not raise
    assert not r.ok
    assert any("could not be read as YAML" in e for e in r.errors), r.errors


# --------------------------------------------------------------------------- teeth: the two indexes


def test_teeth_index_disagreement_is_red(tmp_path):
    """The single most likely way this file goes wrong: a token added to one view and forgotten in
    the other. Invisible to every other clause."""

    def mutate(doc):
        doc["families"][_first_family(doc)]["tokens"].pop()

    errs = _plant(tmp_path, mutate)
    assert any("the two (family, token) indexes disagree" in e for e in errs), errs


def test_teeth_index_disagreement_is_red_in_the_other_direction(tmp_path):
    """Both directions, because a one-way check would let a family silently gain a token.

    The mutation APPENDS a family the token is not listed under, rather than reassigning the list:
    the first attempt at this test set `values[1]["families"]` to `_first_family(doc)`, which is the
    family it already belonged to — an inert mutant, and a test that could not fail.
    """

    def mutate(doc):
        entry = next(e for e in doc["values"] if e["value"] == "recurrence_concordant")
        assert "coverage" not in entry["families"], "mutation would be inert"
        entry["families"].append("coverage")

    errs = _plant(tmp_path, mutate)
    assert any("the two (family, token) indexes disagree" in e for e in errs), errs


def test_teeth_duplicate_token_in_values_is_red(tmp_path):
    def mutate(doc):
        doc["values"].append(copy.deepcopy(doc["values"][0]))

    errs = _plant(tmp_path, mutate)
    assert any("duplicate token" in e for e in errs), errs


# --------------------------------------------------------------------------- teeth: the design decision


def test_teeth_dropping_a_relation_from_the_vocabulary_is_red(tmp_path):
    """Clause 3 is EQUALITY, not subset: dropping `contradicts` here while the code still declares it
    is exactly the coverage gap that reads as a clean file."""

    def mutate(doc):
        doc["relations"]["values"] = [e for e in doc["relations"]["values"] if e["relation"] != "contradicts"]

    errs = _plant(tmp_path, mutate)
    assert any("must name EXACTLY the closed" in e for e in errs), errs


def test_teeth_claiming_contradicts_is_emitted_is_red(tmp_path):
    """Flipping the design decision's flag without doing the work must not be free."""

    def mutate(doc):
        _relation(doc, "contradicts")["emitted_by_family_folds"] = True

    errs = _plant(tmp_path, mutate)
    assert any("maps to NO disposition" in e for e in errs), errs


def test_teeth_unwitnessed_absence_is_red(tmp_path):
    """The heart of the decision. A relation recorded as not-emitted with no witness is an
    unscoped absence-assertion — the shape that goes vacuous without anyone noticing."""

    def mutate(doc):
        _relation(doc, "contradicts").pop("emitted_outside_family_folds_by")

    errs = _plant(tmp_path, mutate)
    assert any("an unwitnessed absence" in e for e in errs), errs


def test_teeth_witness_naming_a_missing_function_is_red(tmp_path):
    """A witness that no longer resolves is worse than no witness: it reads as verified."""

    def mutate(doc):
        _relation(doc, "contradicts")["emitted_outside_family_folds_by"]["builder_function"] = "_gone"

    errs = _plant(tmp_path, mutate)
    assert any("is not a top-level def in" in e for e in errs), errs


def test_teeth_disposition_relation_inverse_mismatch_is_red(tmp_path):
    """The dispositions block and the relations block are inverses. Editing one alone would leave the
    file self-contradictory while each half looked fine."""

    def mutate(doc):
        next(d for d in doc["dispositions"] if d["disposition"] == "concordant")["dependence_relation"] = "qualifies"

    errs = _plant(tmp_path, mutate)
    assert any("the relations block files it under" in e for e in errs), errs


def test_teeth_dead_disposition_is_red(tmp_path):
    """A taxonomy richer than the vocabulary it classifies overstates what is measured."""

    def mutate(doc):
        doc["dispositions"].append(
            {"disposition": "aspirational", "definition": "nothing emits this", "dependence_relation": "qualifies"}
        )
        _relation(doc, "qualifies")["dispositions"].append("aspirational")

    errs = _plant(tmp_path, mutate)
    assert any("is declared but no token uses it" in e for e in errs), errs


def test_teeth_promoting_a_dimension_to_a_gate_is_red(tmp_path):
    """The way a measured gap silently becomes an absence-assertion is somebody turning the count
    into a threshold."""

    def mutate(doc):
        doc["coverage_dimensions"][0]["is_a_gate"] = True

    errs = _plant(tmp_path, mutate)
    assert any("must be explicitly `false`" in e for e in errs), errs


# --------------------------------------------------------------------------- teeth: roster consistency


def test_teeth_family_absent_from_the_catalog_is_red(tmp_path):
    """This enum may not introduce a family — families belong to their owning epics, and a family
    registered here but absent there is a false claim of coverage."""

    def mutate(doc):
        doc["families"]["invented_family"] = {
            "island_key": "invented_concordance",
            "builder": "skills/_skills_common/presence_claims.py",
            "builder_function": "_tumor_presence_concordance_claim",
            "tokens": ["invented_concordant"],
        }
        doc["values"].append(
            {
                "value": "invented_concordant",
                "disposition": "concordant",
                "definition": "x",
                "families": ["invented_family"],
            }
        )

    errs = _plant(tmp_path, mutate)
    assert any("family keys must equal integrated_families.yaml's exactly" in e for e in errs), errs


def test_teeth_island_key_drift_is_red(tmp_path):
    """Two registers describing the same family must agree. `island_key` is an emitted claim-vector
    key that consumers string-match, so a drift here misdirects every reader of either file."""

    def mutate(doc):
        doc["families"][_first_family(doc)]["island_key"] = "renamed_concordance"

    errs = _plant(tmp_path, mutate)
    assert any("integrated_families.yaml says" in e for e in errs), errs


def test_teeth_missing_builder_is_red(tmp_path):
    def mutate(doc):
        doc["families"][_first_family(doc)]["builder"] = "skills/_skills_common/no_such_module.py"

    errs = _plant(tmp_path, mutate)
    assert any("does not exist on disk" in e for e in errs), errs


def test_teeth_roster_crosscheck_cannot_be_skipped(tmp_path):
    """The load-bearing clause must RED when its input is missing, never silently pass. A validator
    that drops its only cross-check on a missing file makes a green run meaningless."""
    r = V.validate_enum(ENUM, tmp_path / "absent.yaml")
    assert not r.ok
    assert any("could not be read" in e and "must not be skipped" in e for e in r.errors), r.errors


# --------------------------------------------------------------------------- teeth: floors and tails


def test_teeth_floor_above_the_measured_population_is_red(tmp_path):
    def mutate(doc):
        doc["population_floors"]["family_token_pairs"] = 999

    errs = _plant(tmp_path, mutate)
    assert any("BELOW the floor" in e for e in errs), errs


def test_teeth_family_count_drift_is_red(tmp_path):
    """`families` is exact, not a floor — the backstop for the roster clause."""

    def mutate(doc):
        doc["population_floors"]["families"] = 12

    errs = _plant(tmp_path, mutate)
    assert any("is exact, not a floor" in e for e in errs), errs


def test_teeth_token_both_emitted_and_documented_not_emitted_is_red(tmp_path):
    def mutate(doc):
        doc["documented_not_emitted"][0]["token"] = doc["values"][0]["value"]

    errs = _plant(tmp_path, mutate)
    assert any("it cannot be both" in e for e in errs), errs


def test_teeth_governed_field_in_the_ungoverned_register_is_red(tmp_path):
    def mutate(doc):
        doc["related_ungoverned_vocabularies"][0]["field"] = "concordance_class"

    errs = _plant(tmp_path, mutate)
    assert any("is the field this enum GOVERNS" in e for e in errs), errs


# --------------------------------------------------------------------------- teeth: additivity


def _additivity_against_synthetic(monkeypatch, mutate_prior) -> "list[str]":
    """Run check_token_additivity against a SYNTHETIC prior built from the live file, so the clause is
    exercised on real content without depending on what happens to be on a git ref.

    Paired deliberately with `test_additivity_runs_on_a_RELATIVE_enum_path`, which runs the same
    clause with NOTHING patched: these tests can only speak to the comparison logic, and 0a proved
    that a green here is compatible with a broken invocation.
    """
    monkeypatch.setattr(
        V,
        "subprocess",
        type(
            "S",
            (),
            {"run": staticmethod(lambda *a, **k: type("P", (), {"returncode": 0, "stdout": "", "stderr": ""})())},
        ),
    )

    def fake_show(ref, rel_path):
        doc = yaml.safe_load((V.REPO_ROOT / rel_path).read_text())
        mutate_prior(doc)
        return yaml.safe_dump(doc, sort_keys=False)

    monkeypatch.setattr(V, "_git_show", fake_show)
    return V.check_token_additivity(ENUM, "synthetic-prior").errors


def test_teeth_additivity_identical_prior_is_green(monkeypatch):
    """Control for the four cases below."""
    assert _additivity_against_synthetic(monkeypatch, lambda doc: None) == []


def test_teeth_additivity_token_removal_is_red(monkeypatch):
    """Tokens are published wire names matched as bare strings by consumers that fail OPEN when a
    match stops happening. A removal must be a MAJOR bump, never a quiet delete."""

    def mutate(doc):
        doc["values"].append({"value": "ghost_token_that_was_removed", "disposition": "concordant", "families": []})

    errs = _additivity_against_synthetic(monkeypatch, mutate)
    assert any("tokens removed vs" in e for e in errs), errs


def test_teeth_additivity_disposition_change_is_red(monkeypatch):
    """The disposition is what the token MEANS, and it selects the dependence relation. Editing it in
    place silently redefines every downstream reading of that token."""

    def mutate(doc):
        doc["values"][0]["disposition"] = (
            "single_arm" if doc["values"][0]["disposition"] != "single_arm" else "concordant"
        )

    errs = _additivity_against_synthetic(monkeypatch, mutate)
    assert any("`disposition` changed vs" in e for e in errs), errs


def test_teeth_additivity_pair_removal_is_red(monkeypatch):
    """A family losing a token it still emits is a coverage gap that reads as a clean file — and it
    is invisible to the token-level removal check, because the token still exists."""

    def mutate(doc):
        doc["families"]["coverage"]["tokens"].append("tumor_presence_concordant")
        for entry in doc["values"]:
            if entry["value"] == "tumor_presence_concordant":
                entry["families"].append("coverage")

    errs = _additivity_against_synthetic(monkeypatch, mutate)
    assert any("pairs removed vs" in e for e in errs), errs


def test_teeth_additivity_addition_without_version_bump_is_red(monkeypatch):
    def mutate(doc):
        doc["values"] = [e for e in doc["values"] if e["value"] != "isoform_splice_concordant_simple"]
        doc["families"]["isoform_splice"]["tokens"].remove("isoform_splice_concordant_simple")

    errs = _additivity_against_synthetic(monkeypatch, mutate)
    assert any("without bumping `version`" in e for e in errs), errs


# --------------------------------------------------------------------------- deliberate NON-failures
#
# Documented cases that must stay GREEN. Each one is a plausible future edit, and a validator that
# reds on it would make additive growth cost a fight — which is how governance files get abandoned.


def test_nonfailure_adding_a_token_with_a_version_bump_is_green(tmp_path, monkeypatch):
    """The whole point of an additive-only vocabulary: a new token, registered in BOTH indexes, with
    a MINOR bump, must pass every clause. If this ever reds, the file has become a ratchet."""

    def mutate(doc):
        doc["version"] = "1.1.0"
        doc["families"]["tumor_presence"]["tokens"].append("tumor_presence_newly_measured")
        doc["values"].append(
            {
                "value": "tumor_presence_newly_measured",
                "disposition": "discordant",
                "definition": "A hypothetical future token, present only in this test.\n",
                "families": ["tumor_presence"],
            }
        )

    assert _plant(tmp_path, mutate) == []
    monkeypatch.setattr(
        V,
        "subprocess",
        type(
            "S",
            (),
            {"run": staticmethod(lambda *a, **k: type("P", (), {"returncode": 0, "stdout": "", "stderr": ""})())},
        ),
    )
    # ... and it must be additive-clean too: the prior is the UNMUTATED live file, the current is the
    # mutated one, so this is an addition WITH a bump.
    monkeypatch.setattr(V, "_git_show", lambda ref, rel: ENUM.read_text())
    doc = copy.deepcopy(DOC)
    mutate(doc)
    path = tmp_path / "bumped" / ENUM.name
    path.parent.mkdir()
    path.write_text(yaml.safe_dump(doc, sort_keys=False))
    monkeypatch.setattr(V, "REPO_ROOT", path.parent)
    assert V.check_token_additivity(path, "synthetic-prior").errors == []


def test_nonfailure_optional_family_note_may_be_absent(tmp_path):
    """`note` is optional on a family. Two of the 13 carry one (coverage and abundance, both
    recording an absence that is by construction); the other 11 must not be required to invent one."""

    def mutate(doc):
        doc["families"]["coverage"].pop("note")

    assert _plant(tmp_path, mutate) == []


def test_nonfailure_a_token_shared_by_several_families_is_green():
    """`single_source_only` is emitted by 5 families. The per-family token lists are allowed to
    overlap — `values` is keyed by TOKEN and carries the family list, and only duplication WITHIN one
    of the two indexes is an error."""
    shared = [e for e in DOC["values"] if len(e["families"]) > 1]
    assert shared, "no shared token in the population — this test would be vacuous"
    assert V.validate_enum(ENUM, FAMILIES).ok


@pytest.mark.parametrize("relation", sorted(V.VALID_RELATIONS))
def test_every_declared_relation_is_recorded_exactly_once(relation):
    """Parametrized over the CODE's vocabulary, not the file's, so a relation the code adds and the
    file has never heard of fails here rather than being quietly uncovered."""
    matches = [e for e in DOC["relations"]["values"] if e["relation"] == relation]
    assert len(matches) == 1, f"{relation}: {len(matches)} entries"
