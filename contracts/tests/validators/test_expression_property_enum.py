"""expression_property.enum.yaml validator tests — population conformance PLUS mutation teeth.
Issue #2233; epic #1507.

Two halves, and the second is the load-bearing one:

  * POPULATION — the committed vocabularies/expression_property.enum.yaml passes every clause.
    This is also the CI gate: contracts/tests/ is collected wholesale by the `contracts-pytest`
    job with no path filter, so a validator regression reds trunk here without needing a workflow
    edit.

  * TEETH — each clause is exercised against a PLANTED defect and asserted RED, via `_plant`, which
    deep-copies the real doc, mutates exactly one thing, and writes it under the REAL filename
    (`enum_id` must equal the stem, or every mutant reds for the wrong reason) alongside a CLEAN
    unmutated control. The load-bearing case is `test_bad_resolves_from_field_is_red` — planting a
    `resolves_from.measurements` name no card declares, exactly the historical defect (issue #2233:
    `control_target_percentile`, which no card declares) that motivated this validator. A clause
    nobody has watched fail is not a validator.

The teeth tests call the SAME function the population test calls (`validate_file`), never a
re-implementation — otherwise a green population could coexist with an inert checker.
"""

from __future__ import annotations

import copy
import importlib.util
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[3]
CONTRACTS = Path(__file__).resolve().parents[2]
VALIDATORS = CONTRACTS / "validators"
CARDS = CONTRACTS / "cards"
ENUM_PATH = CONTRACTS / "vocabularies" / "expression_property.enum.yaml"

# validate_expression_property_enum.py does `from validate_property_catalog import ...` as a
# sibling import — what running it as a script does implicitly (sys.path[0] = the script's
# directory). Loading it by path (below) does not get that for free, so insert it explicitly,
# mirroring test_comparability_state_enum.py / test_concordance_class_enum.py.
if str(VALIDATORS) not in sys.path:
    sys.path.insert(0, str(VALIDATORS))


def _load_validator():
    path = CONTRACTS / "validators" / "validate_expression_property_enum.py"
    spec = importlib.util.spec_from_file_location("validate_expression_property_enum", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


V = _load_validator()
CARD_INDEX = V.card_field_index(CARDS)
REAL_DOC = yaml.safe_load(ENUM_PATH.read_text())


def _plant(tmp_path: Path, mutate) -> Path:
    """Deep-copy the real doc, apply `mutate` in place, write it under the REAL filename (the
    validator asserts `enum_id` == the filename stem, so a renamed file would red for the wrong
    reason and every mutant test would be meaningless)."""
    doc = copy.deepcopy(REAL_DOC)
    mutate(doc)
    out = tmp_path / ENUM_PATH.name
    out.write_text(yaml.safe_dump(doc, sort_keys=False))
    return out


# --------------------------------------------------------------------------- population


def test_enum_is_not_empty():
    """Anti-vacuity floor. Without this, an empty properties list would make the parametrized
    resolvable-property test below collect zero cases and pass while checking nothing."""
    assert isinstance(REAL_DOC.get("properties"), list) and len(REAL_DOC["properties"]) >= 5, (
        f"expected >= 5 declared properties, got {REAL_DOC.get('properties')}"
    )
    assert CARD_INDEX and len(CARD_INDEX) >= 1, "card index did not load — the referential clause would be inert"


def test_committed_enum_validates():
    r = V.validate_file(ENUM_PATH, CARD_INDEX)
    assert r.ok, "\n  ".join(r.errors)


def test_resolvable_properties_are_examined():
    """Names the population the referential clause actually exercises, so a future edit that
    removes every `resolves_from` (leaving the clause vacuously green) is visible here."""
    resolvable = [p for p in REAL_DOC["properties"] if p.get("status") == "resolvable"]
    with_resolves_from = [p for p in resolvable if p.get("resolves_from")]
    assert len(with_resolves_from) >= 5, (
        f"expected >= 5 resolvable properties with resolves_from, got {len(with_resolves_from)}"
    )


def test_fleet_deferred_properties_carry_no_resolves_from():
    """The declaration-vs-status asymmetry, asserted over the real population: a deferred property
    reserves the name without claiming a measurement path (the file's own SCOPE header comment)."""
    deferred = [p for p in REAL_DOC["properties"] if p.get("status") == "fleet_deferred"]
    assert len(deferred) >= 1, "expected at least one fleet_deferred property in the real population"
    for p in deferred:
        assert "resolves_from" not in p, f"{p['id']}: fleet_deferred property must not carry resolves_from"


# --------------------------------------------------------------------------- teeth


def test_bad_resolves_from_field_is_red(tmp_path):
    """THE load-bearing tooth: a `resolves_from.measurements` name no card declares must turn the
    gate RED. This is issue #2233's exact historical defect (`control_target_percentile`, corrected
    to `allgene_percentile` in the same PR) — planted here so the clause that would have caught it
    is proven wired, not just present."""

    def mutate(doc):
        for p in doc["properties"]:
            if p["id"] == "magnitude":
                p["resolves_from"]["measurements"] = [
                    m if m != "allgene_percentile" else "no_such_field_on_any_card"
                    for m in p["resolves_from"]["measurements"]
                ]

    path = _plant(tmp_path, mutate)
    r = V.validate_file(path, CARD_INDEX)
    assert not r.ok
    assert any("no_such_field_on_any_card" in e for e in r.errors), r.errors


def test_unmutated_control_is_clean(tmp_path):
    """The control every mutant test needs: a byte-for-byte round-trip through `_plant` with no
    mutation must stay green, or every RED above could be an artifact of the copy/write path rather
    than the planted defect."""

    def mutate(doc):
        pass

    path = _plant(tmp_path, mutate)
    r = V.validate_file(path, CARD_INDEX)
    assert r.ok, "\n  ".join(r.errors)


def test_bad_card_reference_is_red(tmp_path):
    """The other half of the referential clause: a `resolves_from.card` naming a card that does not
    exist at all must also be RED, not just a bad field name on a real card."""

    def mutate(doc):
        for p in doc["properties"]:
            if p["id"] == "presence":
                p["resolves_from"]["card"] = "no-such-card-anywhere"

    path = _plant(tmp_path, mutate)
    r = V.validate_file(path, CARD_INDEX)
    assert not r.ok
    assert any("no-such-card-anywhere" in e for e in r.errors), r.errors


def test_resolvable_property_missing_resolves_from_is_red(tmp_path):
    """A `resolvable` property with no `resolves_from` at all claims a measurement path exists
    without naming one — clause 2's positive direction."""

    def mutate(doc):
        for p in doc["properties"]:
            if p["id"] == "prevalence":
                del p["resolves_from"]

    path = _plant(tmp_path, mutate)
    r = V.validate_file(path, CARD_INDEX)
    assert not r.ok
    assert any("prevalence" in e and "resolves_from" in e for e in r.errors), r.errors


def test_fleet_deferred_property_with_resolves_from_is_red(tmp_path):
    """A `fleet_deferred` property may not smuggle in a `resolves_from` — that would claim a
    measurement path the file's own header says does not exist yet for that property."""

    def mutate(doc):
        for p in doc["properties"]:
            if p["id"] == "selectivity":
                p["resolves_from"] = {"card": "cellline-rna-distribution", "measurements": ["fraction_expressed"]}

    path = _plant(tmp_path, mutate)
    r = V.validate_file(path, CARD_INDEX)
    assert not r.ok
    assert any("selectivity" in e and "fleet_deferred" in e for e in r.errors), r.errors


def test_unknown_top_level_key_is_red(tmp_path):
    """Strict-keys clause: a misspelled/unknown top-level key must not be silently ignored."""

    def mutate(doc):
        doc["typo_key"] = "oops"

    path = _plant(tmp_path, mutate)
    r = V.validate_file(path, CARD_INDEX)
    assert not r.ok
    assert any("typo_key" in e for e in r.errors), r.errors


def test_gate_invocation_matches_preland_argv():
    """At least one test must invoke the validator exactly as preland.sh does — literal relative
    argv, cwd contracts/, nothing patched — so a wiring regression (wrong path, wrong flag) is
    caught here rather than discovered on a red PR."""
    import subprocess

    proc = subprocess.run(
        [sys.executable, "validators/validate_expression_property_enum.py"],
        cwd=CONTRACTS,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_preland_sh_invokes_this_validator():
    """Pins the wiring itself: preland.sh must actually run this validator, not just have it exist
    on disk. Joins backslash line continuations first so this does not red on formatting alone."""
    text = (CONTRACTS / "scripts" / "preland.sh").read_text()
    joined = text.replace("\\\n", " ")
    assert "validate_expression_property_enum.py" in joined, (
        "preland.sh does not invoke validate_expression_property_enum.py — the gate exists but is unwired"
    )


def test_the_two_gate_argv_tests_match_what_preland_sh_ACTUALLY_RUNS():
    """#2249: the validator is now wired on TWO `run` lines in preland.sh (pool shape clause +
    synchronous additivity clause, mirroring 0b/0c). `test_gate_invocation_matches_preland_argv`
    above hardcodes the argv it believes the SHAPE line uses; without this test, someone could edit
    preland.sh and both that test and the additivity test below would keep passing against an
    invocation the gate no longer runs — green for the wrong reason (arc trap §2.6). Joins backslash
    continuations first, and is deliberately a substring check on flags, not whole-line equality.
    """
    script = (CONTRACTS / "scripts" / "preland.sh").read_text().replace("\\\n", " ")
    wired = [
        " ".join(ln.split())
        for ln in script.splitlines()
        if "validate_expression_property_enum.py" in ln and not ln.lstrip().startswith("#")
    ]
    assert len(wired) == 2, (
        f"expected the validator wired TWICE in preland.sh (pool shape clause + additivity), found "
        f"{len(wired)}: {wired}"
    )
    shape, additivity = wired[0], wired[1]
    for flag in (
        "--enum vocabularies/expression_property.enum.yaml",
        "--cards cards/",
    ):
        assert flag in shape, (
            f"preland.sh shape line is missing {flag!r}; test_gate_invocation_matches_preland_argv is now fiction"
        )
    assert "--additive-against" in additivity, (
        "the second wiring must pass --additive-against, otherwise the token-additivity clause never "
        "runs in the gate and this vocabulary is governed in name only"
    )


def test_additivity_runs_on_a_RELATIVE_enum_path(monkeypatch):
    """The additivity clause resolves the enum path against the REPO root while the argument arrives
    relative to contracts/ (preland.sh's cwd). Without `resolve()` before `relative_to()` this raises
    ValueError and the clause is UNRUN while preland.sh still prints FAIL — indistinguishable from a
    real violation (arc trap §2.6, the bug PR-0a shipped and caught)."""
    monkeypatch.chdir(CONTRACTS)
    r = V.check_token_additivity(Path("vocabularies/expression_property.enum.yaml"), "HEAD")
    assert not any("resolves outside the repo root" in e for e in r.errors), r.errors
    assert not any("does not resolve" in e for e in r.errors), r.errors


def test_the_enum_EXISTS_at_HEAD_so_the_additivity_teeth_are_not_vacuous():
    """#2228 correction, applied here: `--additive-against` is VACUOUS and reports CLEAN whenever the
    file is ABSENT at the comparison ref (`check_token_additivity` short-circuits when `_git_show`
    returns None). This turns that silent-pass condition into a loud, explained RED instead — proving
    the teeth below are comparing against a ref where the file actually exists, not testing nothing.
    """
    rel = ENUM_PATH.resolve().relative_to(REPO).as_posix()
    prior_text = V._git_show("HEAD", rel)
    assert prior_text is not None, (
        f"{rel} does not exist at HEAD — every additivity clause below would be vacuously green "
        f"(#2228's trap: an --additive-against clause reports CLEAN when its file is absent at the "
        f"comparison ref). Commit the enum file before trusting any additivity test in this module."
    )


def _with_mutated_enum_in_place(mutate):
    """`check_token_additivity` resolves its `enum_path` against the real REPO_ROOT (to build the
    `git show <ref>:<rel>` path), so a mutant written under `tmp_path` fails `relative_to()` before
    the clause ever runs (proven while writing this test — the mutants below reproduced the "resolves
    outside the repo root" error, not their intended one). The only faithful way to exercise the
    real function's real path arithmetic is to mutate the REAL committed file in place and restore
    it byte-for-byte in `finally`, exactly mirroring the git-diff-population workaround the arc's own
    traps already required elsewhere."""
    original = ENUM_PATH.read_bytes()
    try:
        doc = copy.deepcopy(REAL_DOC)
        mutate(doc)
        ENUM_PATH.write_text(yaml.safe_dump(doc, sort_keys=False))
        return V.check_token_additivity(ENUM_PATH, "HEAD")
    finally:
        ENUM_PATH.write_bytes(original)


def test_additivity_removed_property_is_red():
    """Mutation tooth, removal direction: a `property.id` present at HEAD but absent from the
    mutant must be RED — this is the exact rename/removal failure #2249 exists to catch."""
    r = _with_mutated_enum_in_place(
        lambda doc: doc["properties"].__setitem__(
            slice(None), [p for p in doc["properties"] if p.get("id") != "magnitude"]
        )
    )
    assert not r.ok
    assert any("magnitude" in e and "removed" in e for e in r.errors), r.errors


def test_additivity_status_changed_is_red():
    """Mutation tooth: changing a surviving property's `status` vs HEAD must be RED — status selects
    whether the property claims a measurement path at all, so a silent flip is a behavioural change
    dressed up as a no-op."""

    def mutate(doc):
        for p in doc["properties"]:
            if p["id"] == "selectivity" and p.get("status") == "fleet_deferred":
                p["status"] = "resolvable"
                p["resolves_from"] = {"card": "cellline-rna-distribution", "measurements": ["fraction_expressed"]}
                return
        raise AssertionError("expected a fleet_deferred property named 'selectivity' in the real population")

    r = _with_mutated_enum_in_place(mutate)
    assert not r.ok
    assert any("selectivity" in e and "status" in e for e in r.errors), r.errors


def test_additivity_new_property_without_version_bump_is_red():
    """Mutation tooth: adding a new property id without bumping `version` must be RED — an addition
    is at least a MINOR bump, or the wire contract silently changed shape."""

    def mutate(doc):
        doc["properties"].append(
            {
                "id": "brand_new_property_2249",
                "label": "Brand New",
                "status": "fleet_deferred",
                "polarity": "neutral",
                "description": "planted for the additivity mutation tooth",
                "values": ["placeholder"],
            }
        )

    r = _with_mutated_enum_in_place(mutate)
    assert not r.ok
    assert any("brand_new_property_2249" in e and "version" in e for e in r.errors), r.errors


def test_additivity_new_property_WITH_version_bump_is_green():
    """The documented deliberate non-failure (arc §3): additive growth accompanied by a version bump
    must stay GREEN, or the teeth would ossify legitimate evolution of the vocabulary."""

    def mutate(doc):
        doc["properties"].append(
            {
                "id": "brand_new_property_2249",
                "label": "Brand New",
                "status": "fleet_deferred",
                "polarity": "neutral",
                "description": "planted for the additivity mutation tooth",
                "values": ["placeholder"],
            }
        )
        major, minor, _patch = (int(x) for x in doc["version"].split("."))
        doc["version"] = f"{major}.{minor + 1}.0"

    r = _with_mutated_enum_in_place(mutate)
    assert r.ok, "\n  ".join(r.errors)


def test_additivity_unresolvable_ref_is_red():
    """Fail-closed on a bad ref: the caller explicitly asked for the clause via --additive-against,
    so an unresolvable ref must be an ERROR, never a silent skip that reports green on an unrun
    clause."""
    r = V.check_token_additivity(ENUM_PATH, "no-such-ref-anywhere-2249")
    assert not r.ok
    assert any("does not resolve" in e for e in r.errors), r.errors


def test_additivity_clean_control_is_green():
    """Control for every mutation tooth above: comparing the real, unmutated file against HEAD (its
    own last-committed state at the time of the compare) must be silent, or the REDs above could not
    be attributed to their planted defects."""
    r = V.check_token_additivity(ENUM_PATH, "HEAD")
    assert r.ok, "\n  ".join(r.errors)
