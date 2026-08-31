"""Structural + behavioural guards for the target-signature LANDSCAPE companion (verdict-INERT, DESCRIPTIVE).

These lock the governance contract (no verdict, no hard label, disclaimer present), the vectoriser's
ordinal maps (signal + the fixed low/moderate/high corroboration map), the frozen linear embedding, the
anchored convex phenotype mixture, and companion determinism. They do NOT assert classification accuracy
(deliberately out of scope — this is a descriptive map, not a classifier)."""
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


# ---- vectoriser: signal + fixed corroboration ordinal maps ---------------------------------------
def test_claim_features_ordinal_maps():
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
    # corroboration uses its OWN low/moderate/high vocabulary (the "only-moderate" bug is FIXED)
    assert f["expression::claim::STRONG_CLAIM::corrob"] == 3.0        # high
    assert f["expression::claim::WEAK_CLAIM::corrob"] == 2.0          # moderate
    assert f["expression::claim::ABSENT_CLAIM::corrob"] == 1.0        # low
    assert f["expression::claim::UNMEASURED_CLAIM::corrob"] is None


def test_claim_features_skips_non_dict_and_empty():
    assert claim_features({}) == {}
    assert claim_features({"ax": None}) == {}
    assert claim_features({"ax": {"C": "not-a-dict"}}) == {}


# ---- simplex projection (the membership solver's core op) ----------------------------------------
def test_proj_simplex_normalises_and_clips():
    p = ac._proj_simplex([0.9, 0.2, -0.5])
    assert all(x >= 0 for x in p) and sum(p) == pytest.approx(1.0, abs=1e-9)
    # already-on-simplex vector is preserved
    q = ac._proj_simplex([0.5, 0.5, 0.0])
    assert sum(q) == pytest.approx(1.0, abs=1e-9)


# ---- atlas integrity -----------------------------------------------------------------------------
def test_atlas_shapes_consistent(atlas: Atlas):
    n = len(atlas.targets)
    assert n == len(atlas.labels) == len(atlas.indications) == len(atlas.X) == len(atlas.rule_fingerprints)
    d = len(atlas.feature_order)
    assert len(atlas.mu) == len(atlas.sd) == d
    assert all(len(row) == d for row in atlas.X)
    assert atlas.meta.get("n_targets") == n and atlas.meta.get("n_features") == d
    assert all(s != 0 for s in atlas.sd)


def test_atlas_carries_frozen_embedding(atlas: Atlas):
    m = atlas.meta.get("emb_dim")
    assert m and len(atlas.components) == m                       # m x d loadings
    assert all(len(row) == len(atlas.feature_order) for row in atlas.components)
    assert len(atlas.corpus_emb) == len(atlas.targets)           # n x m coords
    assert all(len(row) == m for row in atlas.corpus_emb)


def test_atlas_carries_anchors(atlas: Atlas):
    assert atlas.anchors and len(atlas.anchors) >= 4
    m = atlas.meta["emb_dim"]
    for a in atlas.anchors:
        assert {"label", "target", "indication", "coord"} <= set(a)
        assert len(a["coord"]) == m
    # anchor labels reuse the archetype vocabulary so the D1 scorecard consumes the mixture unchanged
    assert all(a["label"] in ac.ARCH_W for a in atlas.anchors)


# ---- embedding: offline == runtime (a corpus row projects back onto its frozen coord) -------------
def test_embed_reproduces_corpus_coord(atlas: Atlas):
    feat = {k: v for k, v in zip(atlas.feature_order, atlas.X[0]) if v is not None}
    e = atlas._embed(feat)
    ref = atlas.corpus_emb[0]
    assert all(abs(a - b) < 1e-3 for a, b in zip(e, ref))        # runtime projection matches frozen build


# ---- companion contract --------------------------------------------------------------------------
def test_companion_is_verdict_inert_and_carries_disclaimer(atlas: Atlas):
    feat = {atlas.feature_order[0]: 3.0}
    c = atlas.companion(feat, k=5)
    assert c["verdict"] is None
    assert "disclaimer" in c and "verdict-inert" in c["disclaimer"].lower()
    # NO hard single-label field — the mixture is a soft distribution only
    assert "archetype" not in c and "predicted_label" not in c and "label" not in c
    assert "phenotype_mixture" in c and isinstance(c["phenotype_mixture"], dict)
    assert c["soft_membership"] == c["phenotype_mixture"]        # alias for the D1 consumer


def test_phenotype_mixture_is_convex_and_sorted(atlas: Atlas):
    feat = {k: v for k, v in zip(atlas.feature_order, atlas.X[0]) if v is not None}
    c = atlas.companion(feat, k=6)
    vals = list(c["phenotype_mixture"].values())
    assert vals == sorted(vals, reverse=True)
    assert sum(vals) == pytest.approx(1.0, abs=1e-2)             # convex mixture, per-label rounded 3dp
    assert all(0.0 <= v <= 1.0 for v in vals)
    # every mixture label is an anchor label
    anchor_labels = {a["label"] for a in atlas.anchors}
    assert set(c["phenotype_mixture"]) <= anchor_labels


def test_novelty_has_hull_residual_and_flags(atlas: Atlas):
    feat = {k: v for k, v in zip(atlas.feature_order, atlas.X[0]) if v is not None}
    nov = atlas.companion(feat, k=5)["novelty"]
    assert "hull_residual" in nov and "inconsistent_flag" in nov
    assert "nearest_neighbour_distance" in nov and "local_density_flag" in nov
    assert isinstance(nov["inconsistent_flag"], bool) and isinstance(nov["local_density_flag"], bool)


def test_nearest_analogs_sorted_by_distance(atlas: Atlas):
    feat = {k: v for k, v in zip(atlas.feature_order, atlas.X[0]) if v is not None}
    c = atlas.companion(feat, k=6)
    dists = [a["distance"] for a in c["nearest_analogs"]]
    assert dists == sorted(dists)
    for a in c["nearest_analogs"]:
        assert {"target", "indication", "archetype_label", "distance"} <= set(a)


def test_self_query_excludes_self(atlas: Atlas):
    # querying an exact atlas row must not return THAT SAME (target,indication) at zero distance.
    # (near-zero distances to OTHER targets are legitimate — e.g. housekeeping controls cluster tightly.)
    t0, i0 = atlas.targets[0], atlas.indications[0]
    feat = {k: v for k, v in zip(atlas.feature_order, atlas.X[0]) if v is not None}
    c = atlas.companion(feat, k=5, exclude_self=True)
    assert not any(a["target"] == t0 and a["indication"] == i0 and a["distance"] < 1e-6
                   for a in c["nearest_analogs"])


def test_companion_is_deterministic(atlas: Atlas):
    feat = {k: v for k, v in zip(atlas.feature_order, atlas.X[3]) if v is not None}
    a1 = atlas.companion(feat, k=7, query_rules={"r1", "r2"})
    a2 = atlas.companion(feat, k=7, query_rules={"r1", "r2"})
    assert json.dumps(a1, sort_keys=True) == json.dumps(a2, sort_keys=True)


def test_missingness_reports_unmeasured_axes(atlas: Atlas):
    feat = {atlas.feature_order[0]: 2.0}
    c = atlas.companion(feat, k=3)
    assert c["missingness"]["n_features_measured"] == 1
    assert c["missingness"]["n_features_total"] == len(atlas.feature_order)
    assert len(c["missingness"]["unmeasured_axes"]) >= 1


# ---- in-process path: the target-profile reduction-stage hook (sub_results -> companion) -----------
def _fake_sub_results() -> dict:
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
        "no_facet": {"fired": []},
    }


def test_vector_from_sub_results_reads_synthesis_facet_claim_vector():
    sr = _fake_sub_results()
    feat = ac.vector_from_sub_results(sr)
    assert feat["expression::claim::TUMOR_PRESENT::signal"] == 3.0
    assert feat["expression::claim::TUMOR_PRESENT::corrob"] == 3.0        # high -> 3 (fixed map)
    assert feat["safety::claim::LOF_CONSTRAINT::signal"] == 0.0
    assert feat["safety::claim::LOF_CONSTRAINT::corrob"] == 1.0           # low -> 1 (fixed map)
    cvs = {s: r["synthesis_facet"]["claim_vector"] for s, r in sr.items() if r.get("synthesis_facet")}
    assert feat == claim_features(cvs)


def test_fired_rule_ids_from_sub_results_drops_none():
    assert ac.fired_rule_ids_from_sub_results(_fake_sub_results()) == {"expr.present.strong", "safety.tolerant"}


def _sub_results_from_atlas_row(atlas: Atlas, i: int) -> dict:
    """Reconstruct an in-process `sub_results` from atlas row i (signal + corrob tiers) so the query lands
    on REAL atlas coordinates and the in-process path is exercised end-to-end."""
    inv_sig = {3.0: "strong", 2.0: "moderate", 1.0: "weak", 0.0: "absent"}
    inv_cor = {3.0: "high", 2.0: "moderate", 1.0: "low", 0.0: "absent"}
    facets: dict = {}
    for key, val in zip(atlas.feature_order, atlas.X[i]):
        if val is None:
            continue
        if key.endswith("::signal"):
            short, _, claim = key[:-len("::signal")].split("::", 2)
            facets.setdefault(short, {}).setdefault(claim, {})["signal"] = inv_sig.get(val, "moderate")
        elif key.endswith("::corrob"):
            short, _, claim = key[:-len("::corrob")].split("::", 2)
            facets.setdefault(short, {}).setdefault(claim, {})["corroboration"] = inv_cor.get(val, "moderate")
    return {short: {"synthesis_facet": {"claim_vector": cv},
                    "fired": [{"rule_id": f"{short}.r1"}]} for short, cv in facets.items()}


def test_companion_from_sub_results_is_verdict_inert(atlas: Atlas):
    sr = _sub_results_from_atlas_row(atlas, 0)
    c = ac.companion_from_sub_results(sr, atlas, k=5)
    assert c["verdict"] is None
    assert sum(c["phenotype_mixture"].values()) == pytest.approx(1.0, abs=1e-2)
    assert c["nearest_analogs"]
    dists = [a["distance"] for a in c["nearest_analogs"]]
    assert dists == sorted(dists)                         # near-zero to tightly-clustered controls is legit
    assert "rule_precedent" in c


def test_rule_precedent_overlay_present_only_when_rules_given(atlas: Atlas):
    feat = {k: v for k, v in zip(atlas.feature_order, atlas.X[0]) if v is not None}
    assert "rule_precedent" not in atlas.companion(feat, k=3)
    real = set(next(rf for rf in atlas.rule_fingerprints if rf))
    c = atlas.companion(feat, k=3, query_rules=real)
    assert "rule_precedent" in c
    assert all(0.0 < p["jaccard"] <= 1.0 for p in c["rule_precedent"])


# ---- D1 nomination scorecard (interpretable, phenotype-conditioned, verdict-inert) ----------------
def test_atlas_carries_axis_ref(atlas: Atlas):
    assert atlas.axis_ref and all({"mean", "std"} <= set(v) for v in atlas.axis_ref.values())
    assert all(v["std"] != 0 for v in atlas.axis_ref.values())


def test_scorecard_is_verdict_inert_and_bounded(atlas: Atlas):
    feat = {k: v for k, v in zip(atlas.feature_order, atlas.X[0]) if v is not None}
    m = atlas.companion(feat, k=6)["soft_membership"]
    sc = ac.nomination_scorecard(feat, m, atlas)
    assert sc["verdict"] is None
    assert 0.0 <= sc["score"] <= 1.0 and 0.0 <= sc["coverage"] <= 1.0
    assert "recommendation" not in sc
    assert sc["driving_axes"] and sc["limiting_axis"]
    assert "verdict-inert" in sc["disclaimer"].lower()


def test_scorecard_counterfactual_is_route_conditioned(atlas: Atlas):
    feat = {k: v for k, v in zip(atlas.feature_order, atlas.X[0]) if v is not None}
    m = atlas.companion(feat, k=6)["soft_membership"]
    sc = ac.nomination_scorecard(feat, m, atlas)
    cf = sc["counterfactual_gap"]
    assert cf is not None and cf["route_conditioned"] is True and cf["limiting_axis"] in ac.SCORECARD_AXES


def test_scorecard_weights_are_archetype_conditioned():
    surf = ac.ARCH_W["expression_surface"]
    assert surf["surface_modality"] > surf["genomic_alteration"]
    assert surf["expression"] > surf["dependency"]
    snv = ac.ARCH_W["snv_driver"]
    assert snv["genomic_alteration"] > snv["surface_modality"]


def test_scorecard_from_sub_results_reuses_companion(atlas: Atlas):
    sr = _sub_results_from_atlas_row(atlas, 3)
    comp = ac.companion_from_sub_results(sr, atlas, k=6)
    sc = ac.scorecard_from_sub_results(sr, atlas, companion=comp)
    assert sc["verdict"] is None and sc["score"] is not None
    assert sc["dominant_archetype_soft"] == max(comp["soft_membership"], key=comp["soft_membership"].get)


# ---- retirement guard: the outcome/approval-propensity (D2/D3) score is GONE ----------------------
def test_predictive_score_retired():
    assert not hasattr(ac, "predictive_score")
    assert not hasattr(ac, "predictive_score_from_sub_results")


def test_anchors_are_multiexemplar_centroids(atlas: Atlas):
    # each anchor is now the CENTROID of an exemplar SET (>=1 member), not a single point — robustness fix
    for a in atlas.anchors:
        assert a.get("n_members", 1) >= 1
        assert len(a.get("members", [[a["target"], a["indication"]]])) == a.get("n_members", 1)
    # the driver/surface/dependency corners must be genuinely multi-member (not n=1)
    by = {a["label"]: a.get("n_members", 1) for a in atlas.anchors}
    for lab in ("snv_driver", "tsg_loss", "amp_driver", "expression_surface", "dependency_essential"):
        assert by[lab] >= 3, f"{lab} anchor should be a multi-exemplar centroid, got n={by[lab]}"


def test_soft_labels_fill_unlabeled_analogs(atlas: Atlas):
    # every corpus target has a data-derived soft label (anchored-mixture dominant)
    assert len(atlas.soft_labels) == len(atlas.targets)
    anchor_labels = {a["label"] for a in atlas.anchors}
    assert all(sl in anchor_labels for sl in atlas.soft_labels)
    # an analog whose curated label is "?" must display the soft label with a trailing "~" + a derived flag;
    # a curated analog must not be marked derived
    feat = {k: v for k, v in zip(atlas.feature_order, atlas.X[0]) if v is not None}
    for a in atlas.companion(feat, k=12)["nearest_analogs"]:
        if a["label_is_derived"]:
            assert a["archetype_label"].endswith("~")
        else:
            assert not a["archetype_label"].endswith("~")
