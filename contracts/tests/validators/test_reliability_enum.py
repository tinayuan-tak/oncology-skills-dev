"""reliability enum validator tests — population conformance PLUS mutation teeth.

The same two halves as its 0a/0b/0c/expression_property/claim_axis siblings, and the second is again
the load-bearing one:

  * POPULATION — the committed vocabularies/reliability.enum.yaml passes every clause, and the design
    decisions it records are pinned as FACTS rather than left in prose: exactly five fields with the
    #2306-locked names, the two scalar sets closed at {weak,moderate,strong} / {true,false,unmeasured},
    the flag vocabularies seeded with their pilot tokens, and every coverage dimension a non-gate with
    emitters=0 at birth. contracts/tests/ is collected wholesale by the `contracts-pytest` job with no
    path filter, so a regression reds trunk here without needing a workflow edit.

  * TEETH — each clause is exercised against a PLANTED defect and asserted RED with a SPECIFIC error
    substring. A validator nobody has watched fail is not a validator.

The anti-patterns the arc has already paid for are avoided here too:

  1. A validator that RAISES is not a validator that FAILS — preland.sh prints `FAIL <label>`
     identically for "found a violation" and "crashed on line 1".
     `test_unparseable_enum_fails_rather_than_crashes` pins the difference.
  2. `test_gate_invocation_matches_preland_argv` (+ the additive variant) and
     `test_the_two_gate_argv_tests_match_what_preland_sh_ACTUALLY_RUNS` invoke the validator EXACTLY as
     the gate does — cwd contracts/, relative paths, the literal argv — nothing patched (trap 6). A
     validator wired on TWO run lines (pool + additivity) needs BOTH reconciled.
  3. An --additive-against clause is VACUOUS when the file is ABSENT at the ref, and it reports CLEAN
     (the #2254 lesson). `test_the_enum_EXISTS_at_HEAD_so_the_additivity_teeth_are_not_vacuous` makes
     that vacuity a RED with an explanation — it fails before the file is committed and passes after
     (commit first, then re-probe).
  4. Per SK#2091 nothing here asserts verdict inertness, and every test below was proven able to fail by
     planting its mutant before it was committed.
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
ENUM = CONTRACTS / "vocabularies" / "reliability.enum.yaml"
CATALOG = CONTRACTS / "vocabularies" / "property_catalog"

# The validator imports its helpers from validate_property_catalog, so validators/ must be importable —
# mirrors what running it as a script does implicitly (sys.path[0] = the script's directory).
if str(VALIDATORS) not in sys.path:
    sys.path.insert(0, str(VALIDATORS))


def _load_validator():
    path = VALIDATORS / "validate_reliability_enum.py"
    spec = importlib.util.spec_from_file_location("validate_reliability_enum", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


V = _load_validator()
DOC = yaml.safe_load(ENUM.read_text())


def _fields(doc) -> dict:
    return {f["field"]: f for f in doc["fields"]}


def _plant(tmp_path: Path, mutate) -> "list[str]":
    """Deep-copy the real enum, plant EXACTLY ONE defect, validate against the REAL catalog, return the
    errors. Keeps the real filename (`enum_id` must equal the stem, or every mutant reds for the wrong
    reason — which the clean control below would then also catch)."""
    doc = copy.deepcopy(DOC)
    mutate(doc)
    p = tmp_path / ENUM.name
    p.write_text(yaml.safe_dump(doc, sort_keys=False))
    return V.validate_enum(p, CATALOG).errors


def _plant_catalog(tmp_path: Path, reliability_block) -> "list[str]":
    """Drive the REFERENTIAL clause (clause 8): validate the REAL, unmutated enum against a SYNTHETIC
    catalog directory holding one entry that declares the given `reliability` block. The real catalog
    declares none (the clause is vacuous at birth), so the only way to exercise clause 8 is a planted
    consumer."""
    cat_dir = tmp_path / "property_catalog"
    cat_dir.mkdir()
    doc = {
        "catalog_id": "synthetic",
        "kind": "l2a_property",
        "version": "1.0.0",
        "properties": {"planted_property": {"reliability": reliability_block}},
    }
    (cat_dir / "synthetic.yaml").write_text(yaml.safe_dump(doc, sort_keys=False))
    return V.validate_enum(ENUM, cat_dir).errors


def _assert_red(errors, *substrings):
    assert errors, "the planted defect produced NO error — the clause is inert"
    blob = " | ".join(errors)
    for s in substrings:
        assert s in blob, f"expected {s!r} in the errors, got: {blob[:800]}"


# ==================================================================================================
# POPULATION — the committed file, and the design facts it records
# ==================================================================================================
def test_committed_enum_passes_every_clause():
    r = V.validate_enum(ENUM, CATALOG)
    assert r.ok, f"committed {ENUM.name} has errors: {r.errors}"


def test_control_a_deep_copied_unmutated_doc_is_green(tmp_path):
    """The control for every teeth test below. If the round-trip itself reddened, each mutant would be
    red for the wrong reason and the whole file would prove nothing."""
    assert _plant(tmp_path, lambda d: None) == []


def test_the_five_locked_fields_are_exactly_the_2306_shape():
    """#2306 locks the field SET. Pinned as a fact so a later session cannot quietly add or drop a field
    without this test — and its reviewer — noticing."""
    assert sorted(_fields(DOC)) == sorted(
        ["n_effective", "powered", "detection_strength", "confound_flags", "artifact_flags"]
    ), sorted(_fields(DOC))
    assert len(DOC["fields"]) == 5


def test_the_two_scalar_state_sets_are_closed_as_locked():
    f = _fields(DOC)
    powered = [t["token"] for t in f["powered"]["tokens"]]
    detection = [t["token"] for t in f["detection_strength"]["tokens"]]
    assert sorted(powered) == ["false", "true", "unmeasured"], powered
    assert sorted(detection) == ["moderate", "strong", "weak"], detection
    assert f["powered"]["datum_kind"] == "scalar_state" and f["powered"]["grows"] is False
    assert f["detection_strength"]["datum_kind"] == "scalar_state" and f["detection_strength"]["grows"] is False


def test_the_flag_vocabularies_are_seeded_with_the_pilot_tokens_and_grow():
    f = _fields(DOC)
    confounds = [t["token"] for t in f["confound_flags"]["tokens"]]
    artifacts = [t["token"] for t in f["artifact_flags"]["tokens"]]
    assert "microenvironment_weighted" in confounds and "entity_pooled" in confounds, confounds
    assert artifacts == ["floor_tie_percentile"], artifacts
    assert f["confound_flags"]["datum_kind"] == "flag_vocab" and f["confound_flags"]["grows"] is True
    assert f["artifact_flags"]["datum_kind"] == "flag_vocab" and f["artifact_flags"]["grows"] is True


def test_powered_carries_the_unmeasured_absence_sentinel():
    """The tri-state's `unmeasured` is the absence-discipline sentinel and MUST be a declared state, or
    the absence read strands (governance.honest_degradation)."""
    powered = _fields(DOC)["powered"]
    assert powered["absent_repr"] == "sentinel_token"
    assert powered["absent_token"] == "unmeasured"
    assert "unmeasured" in [t["token"] for t in powered["tokens"]]


def test_detection_strength_is_the_only_optional_omit_field():
    """`detection_strength` is carried CONDITIONALLY (detection/abundance-kind only), absence = omitted
    key — the same byte-stable idiom comparability_state uses for its omitted key."""
    ds = _fields(DOC)["detection_strength"]
    assert ds["optionality"] == "optional" and ds["absent_repr"] == "omit"
    assert ds["carried_on"] == "detection_abundance"


def test_no_coverage_dimension_claims_to_be_a_gate_and_emitters_are_zero_at_birth():
    dims = {d["dimension"]: d for d in DOC["coverage_dimensions"]}
    for d in dims.values():
        assert d["is_a_gate"] is False, f"{d['dimension']}: dimensions are reported, never enforced"
    assert dims["emitting_skills"]["measured"] == 0, "governance layer: NOTHING emits the facet yet"
    assert dims["consuming_sites"]["measured"] == 0, "governance layer: NOTHING consumes the facet yet"


def test_population_floors_match_the_measured_roster():
    floors = DOC["population_floors"]
    assert floors["fields"] == 5
    assert floors["token_bearing_fields"] == 4
    assert floors["scalar_state_tokens"] == 6
    assert floors["flag_vocab_tokens"] == 3
    assert floors["governed_tokens"] == 9


# ==================================================================================================
# TEETH — one planted defect per clause (validate_enum)
# ==================================================================================================
def test_clause1_unknown_top_level_key_is_red(tmp_path):
    _assert_red(_plant(tmp_path, lambda d: d.update({"reliabilty": "typo"})), "unknown key")


def test_clause1_enum_id_must_match_the_filename(tmp_path):
    _assert_red(_plant(tmp_path, lambda d: d.update({"enum_id": "something_else"})), "enum_id")


def test_clause1_non_semver_version_is_red(tmp_path):
    _assert_red(_plant(tmp_path, lambda d: d.update({"version": "1.0"})), "semver")


def test_clause1_empty_criterion_is_red(tmp_path):
    _assert_red(_plant(tmp_path, lambda d: d.update({"criterion": "   "})), "criterion")


def test_clause1_missing_governance_guardrail_clause_is_red(tmp_path):
    """The two GUARDRAIL clauses (derivation_is_a_projection / honest_degradation) are required non-empty
    — they are the prose that fixes the deriver's contract, and a governance block that dropped one would
    ship the facet without its absence-discipline stated."""
    _assert_red(_plant(tmp_path, lambda d: d["governance"].pop("honest_degradation")), "governance")


def test_clause2_unknown_field_key_is_red(tmp_path):
    _assert_red(
        _plant(tmp_path, lambda d: d["fields"][1].update({"datum_kin": "typo"})),
        "unknown key",
    )


def test_clause2_bad_datum_kind_is_red(tmp_path):
    _assert_red(_plant(tmp_path, lambda d: d["fields"][1].update({"datum_kind": "made_up"})), "datum_kind")


def test_clause2_bad_carried_on_is_red(tmp_path):
    _assert_red(_plant(tmp_path, lambda d: d["fields"][1].update({"carried_on": "everywhere"})), "carried_on")


def test_clause2_non_boolean_grows_is_red(tmp_path):
    _assert_red(_plant(tmp_path, lambda d: d["fields"][3].update({"grows": "yes"})), "`grows` must be a boolean")


def test_clause3_integer_anchor_with_tokens_is_red(tmp_path):
    """The n_effective field is an integer_anchor: giving it a token roster claims it is a vocabulary."""

    def mutate(d):
        # Mutate the list entry in place (not an index copy) so the planted defect survives serialisation.
        for entry in d["fields"]:
            if entry["field"] == "n_effective":
                entry["tokens"] = [{"token": "sneaky", "definition": "x"}]

    _assert_red(_plant(tmp_path, mutate), "carries NO `tokens`")


def test_clause3_scalar_state_marked_growing_is_red(tmp_path):
    """A closed scalar set is not grown additively; `grows: true` on `powered` claims otherwise."""

    def mutate(d):
        for entry in d["fields"]:
            if entry["field"] == "powered":
                entry["grows"] = True

    _assert_red(_plant(tmp_path, mutate), "must be `grows: false`")


def test_clause3_flag_vocab_with_wrong_absent_repr_is_red(tmp_path):
    def mutate(d):
        for entry in d["fields"]:
            if entry["field"] == "confound_flags":
                entry["absent_repr"] = "omit"

    _assert_red(_plant(tmp_path, mutate), "empty list")


def test_clause4_sentinel_field_missing_its_absent_token_is_red(tmp_path):
    def mutate(d):
        for entry in d["fields"]:
            if entry["field"] == "powered":
                del entry["absent_token"]

    _assert_red(_plant(tmp_path, mutate), "requires a string `absent_token`")


def test_clause4_absent_token_not_in_the_roster_is_red(tmp_path):
    def mutate(d):
        for entry in d["fields"]:
            if entry["field"] == "powered":
                entry["absent_token"] = "not_a_state"

    _assert_red(_plant(tmp_path, mutate), "is not one of this field's tokens")


def test_clause4_absent_token_on_an_omit_field_is_red(tmp_path):
    """`detection_strength` omits its key on absence; naming an absent_token too would give it two
    conflicting absence representations."""

    def mutate(d):
        for entry in d["fields"]:
            if entry["field"] == "detection_strength":
                entry["absent_token"] = "weak"

    _assert_red(_plant(tmp_path, mutate), "only meaningful with `absent_repr: sentinel_token`")


def test_clause5_a_token_without_a_definition_is_red(tmp_path):
    def mutate(d):
        for entry in d["fields"]:
            if entry["field"] == "confound_flags":
                entry["tokens"][0].pop("definition")

    _assert_red(_plant(tmp_path, mutate), "definition")


def test_clause5_a_duplicate_token_within_a_field_is_red(tmp_path):
    def mutate(d):
        for entry in d["fields"]:
            if entry["field"] == "confound_flags":
                entry["tokens"].append({"token": "microenvironment_weighted", "definition": "dup"})

    _assert_red(_plant(tmp_path, mutate), "duplicate token")


def test_clause6_a_floor_above_the_measured_population_is_red(tmp_path):
    _assert_red(
        _plant(tmp_path, lambda d: d["population_floors"].update({"flag_vocab_tokens": 99})),
        "population SHRANK",
    )


def test_clause6_the_scalar_token_equality_pin_is_red_when_bumped_alone(tmp_path):
    """`scalar_state_tokens` is pinned to EQUALITY — the two scalar sets are locked. Bumping the declared
    floor without adding a state (which additivity would refuse anyway) is drift."""
    _assert_red(
        _plant(tmp_path, lambda d: d["population_floors"].update({"scalar_state_tokens": 7})),
        "pinned to EQUALITY",
    )


def test_clause6_the_field_count_equality_pin_is_red(tmp_path):
    _assert_red(
        _plant(tmp_path, lambda d: d["population_floors"].update({"fields": 4})),
        "pinned to EQUALITY",
    )


def test_clause7_a_dimension_claiming_to_be_a_gate_is_red(tmp_path):
    _assert_red(
        _plant(tmp_path, lambda d: d["coverage_dimensions"][0].update({"is_a_gate": True})),
        "must be present and exactly `false`",
    )


def test_tail_documented_not_emitted_needs_a_named_site(tmp_path):
    _assert_red(
        _plant(tmp_path, lambda d: d["documented_not_emitted"][0].update({"named_in": []})),
        "hypothetical after all",
    )


def test_unparseable_enum_fails_rather_than_crashes(tmp_path):
    p = tmp_path / ENUM.name
    p.write_text("enum_id: [unclosed\n")
    r = V.validate_enum(p, CATALOG)  # must not raise
    _assert_red(r.errors, "could not be read as YAML")


# ==================================================================================================
# REFERENTIAL clause (clause 8) — vacuous at birth, driven by a PLANTED catalog consumer
# ==================================================================================================
def test_referential_a_valid_declared_block_is_green(tmp_path):
    """A catalog entry whose reliability block draws only governed tokens passes — the control for the
    ungoverned-token teeth below."""
    block = {
        "n_effective": 12,
        "powered": True,
        "detection_strength": "weak",
        "confound_flags": ["microenvironment_weighted"],
        "artifact_flags": ["floor_tie_percentile"],
    }
    assert _plant_catalog(tmp_path, block) == []


def test_referential_an_ungoverned_confound_flag_is_red(tmp_path):
    _assert_red(
        _plant_catalog(tmp_path, {"confound_flags": ["batch_effect_unversioned"]}),
        "not in the governed roster",
    )


def test_referential_an_ungoverned_powered_token_is_red(tmp_path):
    _assert_red(
        _plant_catalog(tmp_path, {"powered": "sort_of"}),
        "not in the governed roster",
    )


def test_referential_a_boolean_powered_maps_onto_the_governed_token(tmp_path):
    """The emit shape is a boolean; the referential clause maps `false` -> the `false` token. A green
    here proves the mapping, not an accidental skip."""
    assert _plant_catalog(tmp_path, {"powered": False}) == []


def test_referential_unreadable_catalog_is_red_not_skipped():
    """A cross-file clause that cannot read its counterpart must FAIL, never pass quietly."""
    r = V.validate_enum(ENUM, Path("/no/such/catalog/dir"))
    _assert_red(r.errors, "referential clause must FAIL")


# ==================================================================================================
# ADDITIVITY (clause 9)
# ==================================================================================================
def test_additivity_rejects_an_unresolvable_ref():
    r = V.check_additivity(ENUM, "definitely-not-a-ref-2306")
    _assert_red(r.errors, "does not resolve", "refusing to report green on an unrun clause")


def test_the_enum_EXISTS_at_HEAD_so_the_additivity_teeth_are_not_vacuous():
    """The #2254 lesson, made a RED. An --additive-against clause is VACUOUS when the file is ABSENT at
    the ref (_git_show returns None -> the clause short-circuits CLEAN), which is exactly the state a new
    vocabulary is in before it is committed. This asserts the file EXISTS at HEAD, so the additivity
    teeth below actually compare something. It FAILS before the enum is committed and PASSES after —
    commit first, then re-probe."""
    rel = ENUM.resolve().relative_to(V.REPO_ROOT).as_posix()
    assert V._git_show("HEAD", rel) is not None, (
        f"{rel} does not exist at HEAD — every --additive-against clause is VACUOUS until it is "
        f"committed. Commit the enum, then re-run (trap: #2254)."
    )


def test_additivity_against_head_is_green_when_nothing_changed():
    r = V.check_additivity(ENUM, "HEAD")
    assert r.ok, r.errors


def test_additivity_runs_on_a_RELATIVE_enum_path(monkeypatch):
    """preland.sh and CI pass a RELATIVE path from cwd contracts/. `relative_to` needs both sides
    absolute, so without the resolve() in check_additivity this CRASHES instead of running. Nothing is
    patched but the cwd."""
    monkeypatch.chdir(CONTRACTS)
    r = V.check_additivity(Path("vocabularies") / ENUM.name, "HEAD")
    assert r.ok, r.errors


def _additivity_against_synthetic(monkeypatch, mutate_prior) -> "list[str]":
    """Run check_additivity with a SYNTHETIC prior built from the live enum, so the clause is exercised
    on real content without depending on what happens to be on a git ref."""
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
        doc = copy.deepcopy(DOC)
        mutate_prior(doc)
        return yaml.safe_dump(doc, sort_keys=False)

    monkeypatch.setattr(V, "_git_show", fake_show)
    return V.check_additivity(ENUM, "synthetic-prior").errors


def test_additivity_identical_prior_is_green(monkeypatch):
    """Control for the synthetic-prior teeth: an unchanged prior must be silent, or their REDs would not
    be attributable to the defect each one planted."""
    assert _additivity_against_synthetic(monkeypatch, lambda d: None) == []


def test_additivity_a_removed_field_is_red(monkeypatch):
    """The prior had a field the working tree dropped -> removing a governed field is breaking."""

    def mutate_prior(d):
        d["fields"].append(
            {
                "field": "extra_prior_field",
                "datum_kind": "flag_vocab",
                "optionality": "required",
                "absent_repr": "empty_list",
                "grows": True,
                "carried_on": "all",
                "rationale": "x",
                "tokens": [{"token": "t", "definition": "d"}],
            }
        )

    _assert_red(_additivity_against_synthetic(monkeypatch, mutate_prior), "field(s) REMOVED")


def test_additivity_a_removed_token_is_red(monkeypatch):
    """The prior had a confound token the working tree dropped -> a removed wire name fails OPEN."""

    def mutate_prior(d):
        for entry in d["fields"]:
            if entry["field"] == "confound_flags":
                entry["tokens"].append({"token": "prior_only_flag", "definition": "d"})

    _assert_red(_additivity_against_synthetic(monkeypatch, mutate_prior), "REMOVED from field", "fail OPEN")


def test_additivity_a_flag_token_added_without_a_bump_is_red(monkeypatch):
    """The prior LACKED a confound token the working tree adds, and the version did not move -> a
    flag-vocabulary addition is at least a MINOR bump."""

    def mutate_prior(d):
        for entry in d["fields"]:
            if entry["field"] == "confound_flags":
                entry["tokens"] = [t for t in entry["tokens"] if t["token"] != "entity_pooled"]

    _assert_red(_additivity_against_synthetic(monkeypatch, mutate_prior), "at least a MINOR bump")


def test_additivity_a_scalar_state_addition_is_refused_regardless_of_version(monkeypatch):
    """Widening a LOCKED scalar set is a #2306 shape re-mint, not additive growth — refused even with a
    version bump. The prior lacked a `powered` state AND had an older version."""

    def mutate_prior(d):
        d["version"] = "0.9.0"
        for entry in d["fields"]:
            if entry["field"] == "powered":
                entry["tokens"] = [t for t in entry["tokens"] if t["token"] != "unmeasured"]
                entry["absent_token"] = "false"  # keep the prior internally consistent

    _assert_red(
        _additivity_against_synthetic(monkeypatch, mutate_prior),
        "widening a LOCKED closed set",
        "refused regardless of version",
    )


def test_additivity_a_changed_datum_kind_is_red(monkeypatch):
    def mutate_prior(d):
        for entry in d["fields"]:
            if entry["field"] == "confound_flags":
                entry["datum_kind"] = "scalar_state"

    _assert_red(_additivity_against_synthetic(monkeypatch, mutate_prior), "changed `datum_kind`")


# ==================================================================================================
# GATE-ARGV parity (trap 6): A = the literal preland argv as a subprocess, B = pin the wired flags
# ==================================================================================================
def test_gate_invocation_matches_preland_argv():
    """Invoke the validator EXACTLY as preland.sh's pool step does — cwd contracts/, the literal relative
    argv, nothing patched (NOT an in-process _main call, which proves nothing about the argv)."""
    proc = subprocess.run(
        [
            sys.executable,
            "validators/validate_reliability_enum.py",
            "--enum",
            "vocabularies/reliability.enum.yaml",
            "--catalog",
            "vocabularies/property_catalog",
        ],
        cwd=CONTRACTS,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, f"gate argv failed:\nstdout={proc.stdout}\nstderr={proc.stderr}"
    assert "9 governed token(s)" in proc.stdout, proc.stdout


def test_gate_invocation_with_additive_against_matches_preland_argv():
    proc = subprocess.run(
        [
            sys.executable,
            "validators/validate_reliability_enum.py",
            "--enum",
            "vocabularies/reliability.enum.yaml",
            "--catalog",
            "vocabularies/property_catalog",
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
    """The two tests above hardcode the argv they believe the gate uses — so if someone edits preland.sh
    they keep passing while testing an invocation that no longer exists. This reads the script and pins
    BOTH wired lines to the flags those tests pass. Deliberately a SUBSTRING check on flags, not
    whole-line equality: the label column and line continuations are formatting. Join backslash
    continuations FIRST or the additivity line (wrapped over three lines) is invisible to a per-line scan."""
    script = (CONTRACTS / "scripts" / "preland.sh").read_text().replace("\\\n", " ")
    wired = [
        " ".join(ln.split())
        for ln in script.splitlines()
        if "validate_reliability_enum.py" in ln and not ln.lstrip().startswith("#")
    ]
    assert len(wired) == 2, (
        f"expected the validator wired TWICE in preland.sh (pool shape clauses + additivity), found "
        f"{len(wired)}: {wired}"
    )
    shape, additivity = wired[0], wired[1]
    for flag in (
        "--enum vocabularies/reliability.enum.yaml",
        "--catalog vocabularies/property_catalog",
    ):
        assert flag in shape, f"preland.sh shape line is missing {flag!r}; the gate-argv test is now fiction"
    assert "--additive-against" in additivity, (
        "the second wiring must pass --additive-against, otherwise the token-additivity clause never runs "
        "in the gate and this vocabulary is governed in name only"
    )
    assert "--catalog" in additivity, (
        "the additivity line must ALSO pass --catalog: it validates the referential clause on the way "
        "through, and a missing catalog there degrades clause 8 to a reported-but-unrun cross-check"
    )


def test_missing_enum_file_exits_nonzero_rather_than_silently_passing():
    proc = subprocess.run(
        [sys.executable, "validators/validate_reliability_enum.py", "--enum", "vocabularies/nope.enum.yaml"],
        cwd=CONTRACTS,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 1, proc.stdout
    assert "does not exist" in proc.stdout


# ==================================================================================================
# DELIBERATE NON-FAILURES — what must stay GREEN, so the teeth cannot ossify legitimate growth
# ==================================================================================================
def test_nonfailure_adding_a_confound_flag_token_is_green(tmp_path):
    """Growing a FLAG vocabulary is the SUPPORTED change (validate_enum accepts it; additivity gates the
    version bump separately). If this went red the enum would be frozen and worked around."""

    def mutate(d):
        for entry in d["fields"]:
            if entry["field"] == "confound_flags":
                entry["tokens"].append({"token": "assay_saturated", "definition": "signal above the linear range"})
        d["population_floors"]["flag_vocab_tokens"] = 4
        d["population_floors"]["governed_tokens"] = 10

    assert _plant(tmp_path, mutate) == []


def test_nonfailure_adding_a_flag_token_with_a_version_bump_is_green(monkeypatch):
    """The additivity path for the intended growth: a flag addition WITH a version move must stay GREEN.

    The working tree is the real committed enum (version 1.0.0, all tokens present); the SYNTHETIC prior
    is an OLDER 0.9.0 that LACKS `floor_tie_percentile`. So the working tree both adds the token and moves
    the version forward — exactly the supported flag-vocabulary growth. Using the real ENUM path keeps
    the repo-relative arithmetic honest (a /tmp path would trip check_additivity's `relative_to`)."""

    def mutate_prior(d):
        d["version"] = "0.9.0"
        for entry in d["fields"]:
            if entry["field"] == "artifact_flags":
                entry["tokens"] = [t for t in entry["tokens"] if t["token"] != "floor_tie_percentile"]

    assert _additivity_against_synthetic(monkeypatch, mutate_prior) == []


def test_nonfailure_omitting_the_optional_trailing_blocks_is_green(tmp_path):
    """`coverage_dimensions` / `documented_not_emitted` / `related_ungoverned_vocabularies` are optional
    tail blocks; a file that omits them is still well-formed."""

    def mutate(d):
        d.pop("coverage_dimensions", None)
        d.pop("documented_not_emitted", None)
        d.pop("related_ungoverned_vocabularies", None)

    assert _plant(tmp_path, mutate) == []
