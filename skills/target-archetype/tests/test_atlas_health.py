"""CI staleness guard for the frozen atlas (embedding integrity + provenance + vocabulary-drift primitive)."""
import importlib.util
import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parents[2]
if str(SKILLS_DIR) not in sys.path:
    sys.path.insert(0, str(SKILLS_DIR))
from _skills_common.archetype_core import Atlas, vocabulary_drift, claim_features  # noqa: E402

ATLAS = Path(__file__).resolve().parents[1] / "atlas" / "atlas.json"
HEALTH = Path(__file__).resolve().parents[1] / "scripts" / "atlas_health.py"


def _mod():
    spec = importlib.util.spec_from_file_location("atlas_health", HEALTH)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
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
    existing = atlas.feature_order[0].split("::")            # e.g. ['cis_coherence','claim','CIS_DOSAGE','signal']
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
    assert all(k in set(atlas.feature_order) for k in f)     # SNV is a known genomic claim
