"""CI staleness guard for the frozen atlas (embedding integrity + provenance + vocabulary-drift primitive)."""

import importlib.util
import json
import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parents[2]
if str(SKILLS_DIR) not in sys.path:
    sys.path.insert(0, str(SKILLS_DIR))
from _skills_common.archetype_core import Atlas, claim_features, vocabulary_drift  # noqa: E402

ATLAS = Path(__file__).resolve().parents[1] / "atlas" / "atlas.json"
HEALTH = Path(__file__).resolve().parents[1] / "scripts" / "atlas_health.py"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "mini_evidence_package"


def _known_short_claim(atlas):
    """A (short, claim) pair guaranteed present in the frozen feature_order. Selects the first ORDINAL
    `short::claim::NAME::signal` key — NOT feature_order[0], which since the v2 substrate re-freeze can be a
    `::num::` metered-numeric key (they sort ahead of `::claim::` alphabetically) whose middle token is a
    measurement field, not a claim name."""
    for k in atlas.feature_order:
        parts = k.split("::")
        if len(parts) >= 4 and parts[1] == "claim" and parts[3] == "signal":
            return parts[0], parts[2]
    raise AssertionError("no ordinal claim::*::signal key in feature_order")


def _write_evidence_package(tmp_path, claim_vectors: dict):
    """Write a CURRENT-layout run dir: evidence_package.json → synthesis.claim_vectors[short].claim_vector."""
    body = {"synthesis": {"claim_vectors": {s: {"claim_vector": cv} for s, cv in claim_vectors.items()}}}
    (tmp_path / "evidence_package.json").write_text(json.dumps(body))
    return tmp_path


def _mod():
    spec = importlib.util.spec_from_file_location("atlas_health", HEALTH)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_shipped_atlas_passes_health():
    """The committed atlas must be internally consistent (offline==runtime for every row) + provenanced.
    A stale/corrupted/hand-edited atlas fails this — the re-freeze tripwire."""
    m = _mod()
    results, ok = m.check(Atlas.load(ATLAS))
    assert ok, {r["check"]: r["detail"] for r in results if r["status"] != "PASS"}
    checks = {r["check"] for r in results}
    assert {"embedding_integrity", "provenance"} <= checks


def test_vocabulary_drift_detects_new_claim_key():
    atlas = Atlas.load(ATLAS)
    # a live vector using ONLY existing claims → no drift
    short, claim = _known_short_claim(atlas)
    ok_vec = {short: {claim: {"signal": "strong", "corroboration": "high"}}}
    assert vocabulary_drift(atlas, ok_vec)["covered"] is True
    # a live vector introducing a NEW claim key (future substrate) → flagged, axis surfaced
    drift = vocabulary_drift(atlas, {short: {"A_BRAND_NEW_SPLICE_CLASS": {"signal": "strong"}}})
    assert drift["covered"] is False
    assert any("A_BRAND_NEW_SPLICE_CLASS" in k for k in drift["missing_keys"])
    assert short in drift["missing_axes"]


def test_vocabulary_drift_ignores_unmeasured_only():
    # claim_features emits None for unmeasured tiers; those still produce keys, so an unmeasured NEW claim
    # is still surfaced (the key exists in feature space) — guard the primitive's key extraction.
    atlas = Atlas.load(ATLAS)
    f = claim_features({"genomic_alteration": {"SNV": {"signal": "strong", "corroboration": "high"}}})
    assert all(k in set(atlas.feature_order) for k in f)  # SNV is a known genomic claim


def test_check_fails_closed_on_empty_harvest(tmp_path):
    """FAIL-CLOSED regression: a --package-dir with no subskills/*/package.json harvests an empty live
    set, for which vocabulary_drift's `missing = live - frozen` is {} and `covered` is a VACUOUS True.
    check() must FAIL it (guard cannot run) rather than vacuously PASS — the fail-open hole that let a
    package-layout drift silently disable the atlas staleness guard."""
    m = _mod()
    (tmp_path / "subskills").mkdir()  # dir present but empty → _read_claim_vectors harvests {}
    results, ok = m.check(Atlas.load(ATLAS), package_dir=tmp_path)
    assert not ok
    vd = [r for r in results if r["check"] == "vocabulary_drift"]
    assert vd and vd[0]["status"] == "FAIL"
    assert "empty harvest" in vd[0]["detail"]


def test_check_passes_on_nonempty_harvest_of_known_claims(tmp_path):
    """A live package whose claim vectors use only KNOWN atlas keys yields a real (non-vacuous) PASS —
    the guard did run and found no drift."""
    m = _mod()
    atlas = Atlas.load(ATLAS)
    short, claim = _known_short_claim(atlas)
    pkg = tmp_path / "subskills" / short
    pkg.mkdir(parents=True)
    (pkg / "package.json").write_text(
        json.dumps({"sub_skill": short, "claim_vector": {claim: {"signal": "strong", "corroboration": "high"}}})
    )
    results, ok = m.check(atlas, package_dir=tmp_path)
    vd = [r for r in results if r["check"] == "vocabulary_drift"]
    assert vd and vd[0]["status"] == "PASS", vd
    assert "covered" in vd[0]["detail"]


def test_reads_current_evidence_package_layout(tmp_path):
    """Repoint regression: a CURRENT-layout run (evidence_package.json → synthesis.claim_vectors) whose
    claims are all known must harvest non-empty and PASS. Pre-repoint the guard globbed ONLY the legacy
    subskills/*/package.json layout, so a current run harvested {} → could not see live drift."""
    m = _mod()
    atlas = Atlas.load(ATLAS)
    short, claim = _known_short_claim(atlas)
    run = _write_evidence_package(tmp_path, {short: {claim: {"signal": "strong", "corroboration": "high"}}})
    results, _ok = m.check(atlas, package_dir=run)
    vd = [r for r in results if r["check"] == "vocabulary_drift"][0]
    assert vd["status"] == "PASS", vd
    assert "covered" in vd["detail"]


def test_committed_fixture_passes_and_exercises_allowlist():
    """The CI fixture (current layout, known claims + one excluded-by-decision axis) PASSES, and the
    excluded key is filtered rather than flagged as drift — this is exactly the CI vocab-drift step."""
    m = _mod()
    results, _ok = m.check(Atlas.load(ATLAS), package_dir=FIXTURE)
    vd = [r for r in results if r["check"] == "vocabulary_drift"][0]
    assert vd["status"] == "PASS", vd
    assert "excluded-by-decision" in vd["detail"], vd


def test_excluded_namespace_key_is_not_drift(tmp_path):
    """A live key under an atlas_excluded_namespaces prefix (e.g. literature_context) is GREEN-by-decision,
    not a re-freeze trigger — it must be filtered out of the drift set."""
    m = _mod()
    atlas = Atlas.load(ATLAS)
    short, claim = _known_short_claim(atlas)
    run = _write_evidence_package(
        tmp_path,
        {
            short: {claim: {"signal": "strong", "corroboration": "high"}},
            "literature_context": {"VOLUME": {"signal": "strong", "corroboration": "moderate"}},
        },
    )
    results, _ok = m.check(atlas, package_dir=run)
    vd = [r for r in results if r["check"] == "vocabulary_drift"][0]
    assert vd["status"] == "PASS", vd
    assert "excluded-by-decision" in vd["detail"], vd


# ── the ::num:: half of the drift guard (2026-09-12) ───────────────────────────────────────────────────


def test_numeric_drift_is_reported_and_is_independent_of_the_claim_verdict():
    """`covered` is claim-only ON PURPOSE and `numeric_covered` is its ::num:: twin. Pinned together because
    the whole point of the split is that they can DISAGREE: a live claim key with no frozen column is a break
    (the substrate says something the geometry cannot hear), whereas an unfrozen numeric is additive and
    self-gating (the runtime drops the key; the cohort_percentile ruler that reads the column self-drops).
    Collapsing the two would either red-fail every card-ruler PR or blind the claim gate."""
    atlas = Atlas.load(ATLAS)
    short, claim = _known_short_claim(atlas)
    drift = vocabulary_drift(atlas, {short: {claim: {"signal": "strong", "corroboration": "high"}}})
    assert drift["covered"] is True  # claims all known
    assert drift["claim_covered"] is True
    # TODAY'S STATE, not a permanent invariant: SALIENCE_SPECS declares more numerics than the atlas froze
    # (the 2026-09-12 card-ruler additions). Flip to `is True` in the re-freeze commit that lands them.
    assert drift["numeric_covered"] is False, "a re-freeze landed → update this pin and the WARN test below"
    assert drift["missing_numeric_keys"], "numeric_covered False must name the keys"
    assert all("::num::" in k for k in drift["missing_numeric_keys"])
    assert drift["n_declared_numeric"] >= len(drift["missing_numeric_keys"])


def test_numeric_drift_is_empty_when_every_declared_numeric_is_frozen():
    """The other direction — the check CAN say PASS. Uses a stub atlas (vocabulary_drift reads only
    feature_order) whose frozen order contains exactly the declared numeric set."""
    from _skills_common.feature_vectoriser import numeric_feature_specs

    declared = [f"{mt}::num::{f}" for mt, (f, _d) in numeric_feature_specs().items()]

    class _Stub:
        feature_order = declared

    drift = vocabulary_drift(_Stub(), {})
    assert drift["missing_numeric_keys"] == []
    assert drift["numeric_covered"] is True
    assert drift["orphan_mask_keys"] == []  # no masks at all in the stub order


def test_orphan_mask_detected_in_the_shipped_atlas():
    """A frozen `{key}::mask` with no `{key}` value column is a column that can only ever say 'unmeasured' —
    build_atlas dropped the value (measured in <2 targets) and kept the mask. The shipped atlas has one."""
    atlas = Atlas.load(ATLAS)
    orphans = vocabulary_drift(atlas, {})["orphan_mask_keys"]
    assert orphans, "shipped atlas lost its known orphan mask — if build_atlas was fixed, drop this pin"
    assert all(k.endswith("::mask") for k in orphans)
    assert all(k[: -len("::mask")] not in set(atlas.feature_order) for k in orphans)


def test_numeric_drift_check_warns_without_failing_the_gate():
    """atlas_health must SURFACE the numeric gap (the docstring promises a WARN) and must NOT go red for it:
    an unfrozen numeric costs the geometry an axis, it does not corrupt it. Runs with NO --package-dir, since
    the declared numeric set is read from the code, not from a live run."""
    m = _mod()
    results, ok = m.check(Atlas.load(ATLAS))
    nd = [r for r in results if r["check"] == "numeric_vocabulary_drift"]
    assert nd, f"numeric_vocabulary_drift check missing: {[r['check'] for r in results]}"
    assert nd[0]["status"] == "WARN", nd
    assert "re-freeze" in nd[0]["detail"] or "orphan" in nd[0]["detail"], nd
    assert ok, "a WARN must not fail the gate"


def test_numeric_drift_check_passes_when_the_atlas_carries_every_numeric():
    """Falsifies the WARN above: the SAME check reports PASS on an atlas whose frozen order carries every
    declared numeric and no orphan mask, so the WARN is data-driven and not a constant.

    A row-less STUB rather than the real atlas mutated: feature_order cannot simply be EXTENDED, because
    `_embed` z-scores the whole order against the frozen means/stds and then dots against `components` — a
    longer order makes z wider than the loadings and raises IndexError. An empty X is the honest way to
    isolate the vocabulary check from the embedding check."""
    from _skills_common.feature_vectoriser import numeric_feature_specs

    m = _mod()

    class _Stub:
        feature_order = [f"{mt}::num::{f}" for mt, (f, _d) in numeric_feature_specs().items()]
        X: list = []
        corpus_emb: list = []
        meta = dict.fromkeys(m._PROV_FIELDS, "x")

    results, ok = m.check(_Stub())
    nd = [r for r in results if r["check"] == "numeric_vocabulary_drift"][0]
    assert nd["status"] == "PASS", nd
    assert "no orphan masks" in nd["detail"]
    assert ok


def test_genuine_non_excluded_new_key_still_fails(tmp_path):
    """The allowlist must NOT over-suppress: a NEW claim on a MODELLED axis (not an excluded prefix) is
    real drift → FAIL → re-freeze trigger. Guards the allowlist from masking genuine substrate movement."""
    m = _mod()
    atlas = Atlas.load(ATLAS)
    short, claim = _known_short_claim(atlas)
    run = _write_evidence_package(
        tmp_path,
        {
            short: {
                claim: {"signal": "strong", "corroboration": "high"},
                "A_BRAND_NEW_MODELLED_CLAIM": {"signal": "strong", "corroboration": "high"},
            }
        },
    )
    results, ok = m.check(atlas, package_dir=run)
    vd = [r for r in results if r["check"] == "vocabulary_drift"][0]
    assert vd["status"] == "FAIL", vd
    assert "re-freeze" in vd["detail"]
    assert not ok
