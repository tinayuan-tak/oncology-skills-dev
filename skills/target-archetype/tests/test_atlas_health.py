"""CI staleness guard for the frozen atlas (embedding integrity + provenance + vocabulary-drift primitive)."""

import importlib.util
import json
import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parents[2]
if str(SKILLS_DIR) not in sys.path:
    sys.path.insert(0, str(SKILLS_DIR))
from _skills_common.archetype_core import Atlas, vocabulary_drift, claim_features  # noqa: E402

ATLAS = Path(__file__).resolve().parents[1] / "atlas" / "atlas.json"
HEALTH = Path(__file__).resolve().parents[1] / "scripts" / "atlas_health.py"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "mini_evidence_package"


def _known_short_claim(atlas):
    """A (short, claim) pair guaranteed present in the frozen feature_order."""
    parts = atlas.feature_order[0].split("::")  # e.g. ['cis_coherence','claim','CIS_DOSAGE','signal']
    return parts[0], parts[2]


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
    existing = atlas.feature_order[0].split("::")  # e.g. ['cis_coherence','claim','CIS_DOSAGE','signal']
    short, claim = existing[0], existing[2]
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
    parts = atlas.feature_order[0].split("::")  # e.g. ['cis_coherence','claim','CIS_DOSAGE','signal']
    short, claim = parts[0], parts[2]
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
