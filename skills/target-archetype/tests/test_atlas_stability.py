"""FREEZE STABILITY of the shipped atlas (skills #1243) — the flagship byte-stability check.

WHY this is not covered by test_atlas_health.py. `test_shipped_atlas_passes_health` asserts a DIFFERENT
property: that the frozen embedding reproduces the runtime transform (offline == runtime) and that the
provenance fields are present. Both survive a self-consistent mutation — rewrite `X` and recompute
`embedding.corpus` from it, and health is green while every cohort_percentile in the fleet has moved. The
artifact is 1.2MB of single-line JSON that at least one script (`amend_atlas_feature_corr.py`) rewrites IN
PLACE, so "did the numbers we measure everything against change without a re-freeze?" needs its own answer.

The pin is per-field and per-`meta`-key so a red test NAMES what moved. Every mutation test below asserts the
guard FIRES and names the field, because a digest comparison that can only ever say "the file changed" is
worth little at review time.
"""

import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ATLAS = ROOT / "atlas" / "atlas.json"
MANIFEST = ROOT / "atlas" / "atlas_freeze.json"
SCRIPT = ROOT / "scripts" / "atlas_stability.py"


@pytest.fixture(scope="module")
def st():
    spec = importlib.util.spec_from_file_location("atlas_stability", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["atlas_stability"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def doc():
    return json.loads(ATLAS.read_text())


@pytest.fixture(scope="module")
def pinned():
    return json.loads(MANIFEST.read_text())


# --- the live gate -----------------------------------------------------------


def test_the_shipped_atlas_matches_its_pin(st, pinned, doc):
    """THE check. A red here means either the artifact changed without a re-freeze (investigate — do NOT
    re-run --write to make it green) or a re-freeze landed without re-pinning."""
    problems = st.compare_manifest(pinned, doc)
    assert not problems, "shipped atlas diverged from atlas_freeze.json:\n  " + "\n  ".join(problems)


def test_the_pin_names_the_build_it_describes(st, pinned, doc):
    """Identity echo: a manifest whose digests belong to some other build is not a pin. This is also what
    makes a re-pin a legible diff — corpus/sha/shape move visibly at the top of the file."""
    identity = pinned["identity"]
    assert identity["corpus"] == doc["meta"]["corpus"]
    assert identity["build_git_sha"] == doc["meta"]["build_git_sha"]
    assert identity["n_targets"] == doc["meta"]["n_targets"] == len(doc["targets"])
    assert identity["n_features"] == doc["meta"]["n_features"] == len(doc["feature_order"])


def test_the_pin_covers_every_field_the_artifact_ships(st, pinned, doc):
    """Population derived from the ARTIFACT, not a hardcoded list: a re-freeze that adds a top-level field or
    a meta key must pin it, or this fails. A pinned list would leave the new field — quite possibly the whole
    point of the re-freeze — silently unguarded."""
    assert set(pinned["fields"]) == set(doc), (
        f"unpinned fields: {sorted(set(doc) - set(pinned['fields']))}; "
        f"stale pins: {sorted(set(pinned['fields']) - set(doc))}"
    )
    assert set(pinned["meta_fields"]) == set(doc["meta"]), (
        f"unpinned meta keys: {sorted(set(doc['meta']) - set(pinned['meta_fields']))}; "
        f"stale pins: {sorted(set(pinned['meta_fields']) - set(doc['meta']))}"
    )
    # the load-bearing blocks specifically — every read in the skill is measured against these four
    assert {"mu", "sd", "X", "embedding", "anchors", "feature_order"} <= set(pinned["fields"])


# --- anti-vacuity: the guard must actually fire ------------------------------


def test_a_self_consistent_mutation_of_X_is_caught(st, pinned, doc):
    """★ The case atlas_health CANNOT see. `X` is the cohort-percentile population; mutating one cell moves
    every percentile read against that column, and a matching embedding recompute leaves the health check
    green. The pin catches it because it hashes the shipped VALUES, not their internal consistency."""
    m = copy.deepcopy(doc)
    row = next(i for i, r in enumerate(m["X"]) if any(v is not None for v in r))
    col = next(j for j, v in enumerate(m["X"][row]) if v is not None)
    m["X"][row][col] = (m["X"][row][col] or 0) + 1
    problems = st.compare_manifest(pinned, m)
    assert any("'X'" in p and "CHANGED" in p for p in problems), problems


def test_a_moved_anchor_coord_is_caught(st, pinned, doc):
    """Anchors are the phenotype corners every mixture is expressed in; a nudged coord re-weights every
    membership payload in the fleet with no other symptom."""
    m = copy.deepcopy(doc)
    m["anchors"][0]["coord"][0] += 1e-6
    problems = st.compare_manifest(pinned, m)
    assert any("'anchors'" in p and "CHANGED" in p for p in problems), problems


def test_a_changed_meta_key_is_named_not_just_meta(st, pinned, doc):
    """Meta-key grain. `anchor_phenotypes_skipped` is the artifact-side record of the DEFERRED_ANCHORS guard
    (see test_deferred_anchors.py) — a diff that reported only "meta changed" would not tell a reviewer that
    a deferral had been activated."""
    m = copy.deepcopy(doc)
    m["meta"]["anchor_phenotypes_skipped"] = []
    problems = st.compare_manifest(pinned, m)
    assert any("'anchor_phenotypes_skipped'" in p for p in problems), problems


def test_a_new_unpinned_field_is_reported_as_unpinned(st, pinned, doc):
    """Not merely "changed": a field the artifact gained is a distinct, actionable state — pin it in the
    re-freeze that introduced it."""
    m = copy.deepcopy(doc)
    m["some_new_block"] = [1, 2, 3]
    problems = st.compare_manifest(pinned, m)
    assert any("some_new_block" in p and "UNPINNED" in p for p in problems), problems


def test_a_dropped_field_is_reported_as_missing(st, pinned, doc):
    """The other direction — a build that stops emitting a block readers depend on."""
    m = copy.deepcopy(doc)
    del m["soft_labels"]
    problems = st.compare_manifest(pinned, m)
    assert any("soft_labels" in p and "MISSING" in p for p in problems), problems


def test_an_emptied_manifest_does_not_pass_vacuously(st, doc):
    """A pin with no digests is the failure mode of every checksum guard: it compares nothing and reports
    success. Both scopes must complain."""
    problems = st.compare_manifest({"schema": st.SCHEMA, "identity": {}, "fields": {}, "meta_fields": {}}, doc)
    assert sum("pins NO" in p for p in problems) == 2, problems


def test_the_unmutated_document_produces_no_problems(st, pinned, doc):
    """Both poles: the mutation tests above would be meaningless if compare_manifest complained about
    everything. (Same assertion as the live gate, stated as the control for this section.)"""
    assert st.compare_manifest(pinned, copy.deepcopy(doc)) == []


# --- the rebuild comparator (--verify-rebuild) --------------------------------
# MEASURED 2026-09-13: a build over target-archetype-corpus-20260911 + panel_297.tsv reproduced all 16
# substantive top-level fields byte-identically; only meta.build_git_sha and meta.feature_corr_provenance
# differed. These tests pin the COMPARATOR's semantics — the rebuild itself cannot run in CI (build_atlas
# imports sklearn, which is not in the pixi env, and the corpus lives outside the repo), so it is a
# re-freeze checklist step rather than a test that would skip to green.


def test_only_declared_volatile_fields_are_waived(st, doc):
    a = copy.deepcopy(doc)
    b = copy.deepcopy(doc)
    b["meta"]["build_git_sha"] = "deadbeef"
    substantive, waived = st.diff_docs(a, b)
    assert substantive == []
    assert waived == ["meta.build_git_sha"]


def test_the_waiver_does_not_extend_to_the_rest_of_meta(st, doc):
    """The subtraction is at META-KEY grain. If it were at the `meta` grain, one changed sha would excuse
    n_targets, classes, anchor_phenotypes — the whole provenance block — in a re-freeze review."""
    a = copy.deepcopy(doc)
    b = copy.deepcopy(doc)
    b["meta"]["build_git_sha"] = "deadbeef"
    b["meta"]["n_targets"] = 1
    substantive, waived = st.diff_docs(a, b)
    assert substantive == ["meta.n_targets"]
    assert waived == ["meta.build_git_sha"]


def test_a_changed_numeric_block_is_never_waived(st, doc):
    a = copy.deepcopy(doc)
    for field in ("mu", "sd", "X", "embedding", "anchors", "feature_corr", "labels", "soft_labels"):
        b = copy.deepcopy(doc)
        b[field] = "mutated"
        substantive, _waived = st.diff_docs(a, b)
        assert substantive == [field], f"{field} was not reported as a substantive rebuild difference"


def test_the_volatile_allowlist_stays_provenance_only(st, doc):
    """★ An allowlist is the one place this guard can be defeated WITHOUT touching a digest: adding `mu` to
    it would silently waive the z-reference. Pinned BY NAME (iterating the declaration would be green under
    any substitution), and structurally constrained: nothing outside `meta` may ever be waivable."""
    assert set(st.VOLATILE_ON_REBUILD) == {
        "meta.build_date",
        "meta.build_git_sha",
        "meta.feature_corr_provenance",
    }, "the rebuild waiver list changed — every addition waives a real difference and needs its own evidence"
    for path, reason in st.VOLATILE_ON_REBUILD.items():
        assert path.startswith("meta."), f"{path} is outside meta — corpus-derived numbers are never volatile"
        assert path.split(".", 1)[1] in doc["meta"], f"{path} does not exist in the shipped atlas (stale waiver)"
        assert len(reason) > 40, f"{path} is waived without a stated reason"


def test_the_load_bearing_meta_keys_are_not_waivable(st, doc):
    """Derived coverage rather than a second hardcoded list: every meta key the readers act on must be
    compared. n_features/classes/anchor_phenotypes* change the geometry or the vocabulary."""
    waived = {p.split(".", 1)[1] for p in st.VOLATILE_ON_REBUILD}
    load_bearing = {
        k
        for k in doc["meta"]
        if k not in ("build_date", "build_git_sha", "note", "vectoriser", "feature_corr_provenance")
    }
    assert load_bearing, "meta carries no load-bearing keys — this check has stopped covering anything"
    assert not (load_bearing & waived), sorted(load_bearing & waived)


# --- the script surface ------------------------------------------------------


def test_the_check_mode_exits_zero_on_the_shipped_tree():
    """The CLI is what a re-freeze runs by hand; exercise its exit code, not just the library."""
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--check"], capture_output=True, text=True, cwd=str(ROOT / "scripts")
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout


def test_the_check_mode_exits_nonzero_on_a_mutated_atlas(doc, tmp_path):
    """...and the failing pole, or the gate above proves only that the script can print PASS."""
    m = copy.deepcopy(doc)
    m["mu"][0] = (m["mu"][0] or 0) + 1.0
    bad = tmp_path / "atlas.json"
    bad.write_text(json.dumps(m))
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--check", "--atlas", str(bad), "--manifest", str(MANIFEST)],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 1
    assert "'mu' CHANGED" in r.stdout, r.stdout
