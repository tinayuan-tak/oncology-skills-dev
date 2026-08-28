"""Structural + behavioural guards for the target-archetype companion (verdict-INERT, DESCRIPTIVE).

These lock the governance contract (no verdict, no hard label, disclaimer present), the vectoriser's
ported ordinal map, the NaN-aware distance (A2 mask), and companion determinism. They do NOT assert
classification accuracy — that is the pending blind-label gate (P3), deliberately out of scope here."""
import json
import math
import sys
from pathlib import Path

import pytest

SKILLS_DIR = Path(__file__).resolve().parents[2]        # .../skills
if str(SKILLS_DIR) not in sys.path:
    sys.path.insert(0, str(SKILLS_DIR))

from _skills_common import archetype_core as ac                    # noqa: E402
from _skills_common.archetype_core import Atlas, claim_features     # noqa: E402

ATLAS_PATH = Path(__file__).resolve().parents[1] / "atlas" / "atlas.json"


@pytest.fixture(scope="module")
def atlas() -> Atlas:
    return Atlas.load(ATLAS_PATH)


# ---- vectoriser: the ordinal map is ported VERBATIM from the validated harvest -------------------
def test_claim_features_ordinal_map_matches_validated_harvest():
    cv = {"expression": {
        "STRONG_CLAIM": {"signal": "strong", "corroboration": "high"},
        "WEAK_CLAIM": {"signal": "weak", "corroboration": "moderate"},
        "ABSENT_CLAIM": {"signal": "absent", "corroboration": "low"},
        "UNMEASURED_CLAIM": {"signal": "unmeasured", "corroboration": "unmeasured"},
    }}
    f = claim_features(cv)
    assert f["expression::claim::STRONG_CLAIM::signal"] == 3.0
    assert f["expression::claim::WEAK_CLAIM::signal"] == 1.0
    assert f["expression::claim::ABSENT_CLAIM::signal"] == 0.0        # absent is a REAL 0, not missing
    assert f["expression::claim::UNMEASURED_CLAIM::signal"] is None   # unmeasured is None (gap != absent)
    # corroboration QUIRK preserved: only 'moderate' maps to a value; high/low -> None (see module docstring)
    assert f["expression::claim::WEAK_CLAIM::corrob"] == 2.0
    assert f["expression::claim::STRONG_CLAIM::corrob"] is None
    assert f["expression::claim::ABSENT_CLAIM::corrob"] is None


def test_claim_features_skips_non_dict_and_empty():
    assert claim_features({}) == {}
    assert claim_features({"ax": None}) == {}
    assert claim_features({"ax": {"C": "not-a-dict"}}) == {}


# ---- NaN-aware distance (the A2 mask): co-measured dims only, rescaled by dimensionality ----------
def test_nan_euclidean_ignores_missing_and_rescales():
    # identical on all present dims -> distance 0 regardless of missingness
    assert ac._nan_euclidean([1.0, None, 2.0], [[1.0, 5.0, 2.0]])[0] == pytest.approx(0.0)
    # one differing dim of 3, one dim missing in query: rescale factor d/cnt = 3/2
    d = ac._nan_euclidean([0.0, 1.0, None], [[0.0, 0.0, 9.0]])[0]
    assert d == pytest.approx(math.sqrt(1.0 * 3 / 2))
    # no co-measured dims -> infinite distance (never spuriously 'close')
    assert ac._nan_euclidean([1.0, None], [[None, 2.0]])[0] == math.inf


# ---- atlas integrity -----------------------------------------------------------------------------
def test_atlas_shapes_consistent(atlas: Atlas):
    n = len(atlas.targets)
    assert n == len(atlas.labels) == len(atlas.indications) == len(atlas.X) == len(atlas.rule_fingerprints)
    d = len(atlas.feature_order)
    assert len(atlas.mu) == len(atlas.sd) == d
    assert all(len(row) == d for row in atlas.X)
    assert atlas.meta.get("n_targets") == n and atlas.meta.get("n_features") == d
    assert all(s != 0 for s in atlas.sd)                 # zero-std guarded to 1.0 at build/load


# ---- companion contract --------------------------------------------------------------------------
def test_companion_is_verdict_inert_and_carries_disclaimer(atlas: Atlas):
    feat = {atlas.feature_order[0]: 3.0}
    c = atlas.companion(feat, k=5)
    assert c["verdict"] is None
    assert "disclaimer" in c and "verdict-inert" in c["disclaimer"].lower()
    # NO hard single-label field — membership is a soft distribution only
    assert "archetype" not in c and "predicted_label" not in c and "label" not in c
    assert "soft_membership" in c and isinstance(c["soft_membership"], dict)


def test_soft_membership_normalised_and_sorted(atlas: Atlas):
    feat = {k: v for k, v in zip(atlas.feature_order, atlas.X[0]) if v is not None}
    c = atlas.companion(feat, k=6)
    vals = list(c["soft_membership"].values())
    assert vals == sorted(vals, reverse=True)            # descending
    assert sum(vals) == pytest.approx(1.0, abs=1e-2)  # per-class rounded to 3dp


def test_nearest_analogs_sorted_by_distance(atlas: Atlas):
    feat = {k: v for k, v in zip(atlas.feature_order, atlas.X[0]) if v is not None}
    c = atlas.companion(feat, k=6)
    dists = [a["distance"] for a in c["nearest_analogs"]]
    assert dists == sorted(dists)
    for a in c["nearest_analogs"]:
        assert {"target", "indication", "archetype_label", "distance"} <= set(a)


def test_self_query_excludes_self(atlas: Atlas):
    # querying with an exact atlas row must NOT return that same row (zero distance dropped)
    row = atlas.X[0]
    feat = {k: v for k, v in zip(atlas.feature_order, row) if v is not None}
    c = atlas.companion(feat, k=5, exclude_self=True)
    assert all(a["distance"] > 1e-9 for a in c["nearest_analogs"])


def test_companion_is_deterministic(atlas: Atlas):
    feat = {k: v for k, v in zip(atlas.feature_order, atlas.X[3]) if v is not None}
    a1 = atlas.companion(feat, k=7, query_rules={"r1", "r2"})
    a2 = atlas.companion(feat, k=7, query_rules={"r1", "r2"})
    assert json.dumps(a1, sort_keys=True) == json.dumps(a2, sort_keys=True)


def test_missingness_reports_unmeasured_axes(atlas: Atlas):
    # a feature dict measuring exactly ONE feature -> most axes flagged fully unmeasured
    feat = {atlas.feature_order[0]: 2.0}
    c = atlas.companion(feat, k=3)
    assert c["missingness"]["n_features_measured"] == 1
    assert c["missingness"]["n_features_total"] == len(atlas.feature_order)
    assert len(c["missingness"]["unmeasured_axes"]) >= 1


# ---- in-process path: the target-profile reduction-stage hook (sub_results -> companion) -----------
def _fake_sub_results() -> dict:
    """Mimic the in-process fan-out `sub_results` shape: {short: {synthesis_facet:{claim_vector}, fired}}.
    The claim_vector nested shape is EXACTLY what tp_manifest serialises into package.json."""
    return {
        "expression": {
            "synthesis_facet": {"claim_vector": {
                "TUMOR_PRESENT": {"signal": "strong", "corroboration": "high"},
                "CELLLINE_RNA": {"signal": "moderate", "corroboration": "moderate"},
            }},
            "fired": [{"rule_id": "expr.present.strong"}, {"rule_id": None}],
        },
        "safety": {
            "synthesis_facet": {"claim_vector": {
                "LOF_CONSTRAINT": {"signal": "absent", "corroboration": "low"},
            }},
            "fired": [{"rule_id": "safety.tolerant"}],
        },
        "no_facet": {"fired": []},                       # a sub-skill with no facet is tolerated
    }


def test_vector_from_sub_results_reads_synthesis_facet_claim_vector():
    sr = _fake_sub_results()
    feat = ac.vector_from_sub_results(sr)
    assert feat["expression::claim::TUMOR_PRESENT::signal"] == 3.0
    assert feat["expression::claim::CELLLINE_RNA::signal"] == 2.0
    assert feat["safety::claim::LOF_CONSTRAINT::signal"] == 0.0
    # equivalence with the package-dir path: same vectoriser, same keys
    cvs = {s: r["synthesis_facet"]["claim_vector"] for s, r in sr.items() if r.get("synthesis_facet")}
    assert feat == claim_features(cvs)


def test_fired_rule_ids_from_sub_results_drops_none():
    assert ac.fired_rule_ids_from_sub_results(_fake_sub_results()) == {"expr.present.strong", "safety.tolerant"}


def _sub_results_from_atlas_row(atlas: Atlas, i: int) -> dict:
    """Reconstruct an in-process `sub_results` dict from atlas row i by inverting real feature keys
    ({short}::claim::{CLAIM}::{signal|corrob}) back into synthesis_facet.claim_vector — so the query
    lands on REAL atlas coordinates and the in-process path is exercised end-to-end."""
    inv = {3.0: "strong", 2.0: "moderate", 1.0: "weak", 0.0: "absent"}
    facets: dict = {}
    for key, val in zip(atlas.feature_order, atlas.X[i]):
        if val is None or not key.endswith("::signal"):
            continue
        short, _, claim = key[:-len("::signal")].split("::", 2)
        facets.setdefault(short, {})[claim] = {"signal": inv.get(val, "moderate")}
    return {short: {"synthesis_facet": {"claim_vector": cv},
                    "fired": [{"rule_id": f"{short}.r1"}]} for short, cv in facets.items()}


def test_companion_from_sub_results_is_verdict_inert(atlas: Atlas):
    sr = _sub_results_from_atlas_row(atlas, 0)
    c = ac.companion_from_sub_results(sr, atlas, k=5)
    assert c["verdict"] is None
    assert "soft_membership" in c and sum(c["soft_membership"].values()) == pytest.approx(1.0, abs=1e-2)  # per-class rounded to 3dp
    assert c["nearest_analogs"] and all(a["distance"] > 0 for a in c["nearest_analogs"])
    assert "rule_precedent" in c                          # fired rules present -> overlay computed


def test_rule_precedent_overlay_present_only_when_rules_given(atlas: Atlas):
    feat = {k: v for k, v in zip(atlas.feature_order, atlas.X[0]) if v is not None}
    assert "rule_precedent" not in atlas.companion(feat, k=3)
    # feed a real fingerprint from the atlas -> should retrieve overlapping precedent
    real = set(next(rf for rf in atlas.rule_fingerprints if rf))
    c = atlas.companion(feat, k=3, query_rules=real)
    assert "rule_precedent" in c
    assert all(0.0 < p["jaccard"] <= 1.0 for p in c["rule_precedent"])
