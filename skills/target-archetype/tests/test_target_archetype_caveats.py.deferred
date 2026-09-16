"""Hermetic tests for the v0.6.0 archetype confidence surface (literature-and-claims arc, FIRST non-fan-out).

Covers the VERDICT-INERT enrichment added over the CARDLESS phenotype-landscape companion:
  - archetype_confidence_caveat   (3 tiers + false-demote guard + precedence + None path)
  - scorecard_confidence_caveat   (illustrative-not-learned; fires when a score exists; None otherwise)
  - archetype_provenance          (quorum fields; empty→None)
  - companion_from_sub_results + nomination_scorecard carry the caveats (composed == standalone)
  - the TARGET_ARCHETYPE lens (registry, descriptive, 5 axis_labels) + the bespoke run.py decision builder

Pure caveat/provenance tests use synthetic companion/scorecard dicts (no atlas / no data / no LLM). The
carry + decision-builder tests use the real frozen atlas + a synthetic sub_results row. SET literals, not
2-string tuples (reference-drift guard). Asserts the calibration the DETERMINISTIC panel showed live."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

SKILL_DIR = Path(__file__).resolve().parent.parent
SKILLS_DIR = SKILL_DIR.parent
if str(SKILLS_DIR) not in sys.path:
    sys.path.insert(0, str(SKILLS_DIR))

from _skills_common import archetype_core as ac  # noqa: E402
from _skills_common.archetype_core import Atlas  # noqa: E402
from _skills_common.narrator_lenses import LENSES, TARGET_ARCHETYPE  # noqa: E402

ATLAS_PATH = SKILL_DIR / "atlas" / "atlas.json"


@pytest.fixture(scope="module")
def atlas() -> Atlas:
    return Atlas.load(ATLAS_PATH)


def _run_module():
    spec = importlib.util.spec_from_file_location("ta_run_caveats", SKILL_DIR / "scripts" / "run.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# ── synthetic companion builder (only the fields the caveats read) ──────────────────────────────────
def _companion(
    dominant="snv_driver",
    dom_mass=0.6,
    stability=0.82,
    n_meas=22,
    n_tot=30,
    unmeasured=("combination_vulnerability",),
    analog_derived=False,
    analog_target="NRAS",
    analog_label="snv_driver",
    inconsistent=False,
    multimodal=False,
):
    _filler = "control_absent" if dominant != "control_absent" else "dependency_essential"
    mix = {dominant: dom_mass, _filler: round(1.0 - dom_mass, 3)}
    return {
        "soft_membership": mix,
        "phenotype_mixture": mix,
        "mixture_uncertainty": {"stability": stability},
        "missingness": {"n_features_measured": n_meas, "n_features_total": n_tot, "unmeasured_axes": list(unmeasured)},
        "nearest_analogs": [
            {
                "target": analog_target,
                "archetype_label": analog_label,
                "label_is_derived": analog_derived,
                "distance": 3.1,
            }
        ],
        "novelty": {
            "inconsistent_flag": inconsistent,
            "multimodal": multimodal,
            "mixture_entropy": 0.67,
            "hull_residual_relative": 0.4,
        },
        "anchors": [{"label": lb, "target": "X", "indication": "Y"} for lb in ac._CANONICAL_ESTABLISHED_ANCHORS],
    }


# ── TIER (iii) MILDER — validated_canonical_anchor false-demote guard ───────────────────────────────
def test_validated_canonical_anchor_guard_fires():
    c = ac.archetype_confidence_caveat(_companion(dominant="amp_driver", dom_mass=0.7, stability=0.8, n_meas=24))
    assert c["reason"] == "validated_canonical_anchor"
    assert c["tier"] == "milder" and c["false_demote_guarded"] is True
    assert c["dominant_anchor"] == "amp_driver"


def test_guard_wins_over_derived_analog():
    # canonical + robust + well-measured BUT the top analog is data-derived: the guard still wins (a robust
    # canonical read is not demoted for a circular analog) — precedence check.
    c = ac.archetype_confidence_caveat(
        _companion(dominant="tsg_loss", dom_mass=0.65, stability=0.75, analog_derived=True)
    )
    assert c["reason"] == "validated_canonical_anchor"


# ── TIER (i) SHARP — low stability OR missingness-distorted (the EGFR amp-because-SNV-0 mode) ────────
def test_low_stability_fires_sharp():
    c = ac.archetype_confidence_caveat(_companion(dominant="amp_driver", dom_mass=0.7, stability=0.45))
    assert c["reason"] == "phenotype_mixture_low_stability_or_missingness_distorted"
    assert c["tier"] == "sharp" and c["false_demote_guarded"] is False
    assert "UNSTABLE" in c["detail"]


def test_missingness_distorted_fires_sharp_even_for_canonical():
    # canonical dominant + HIGH stability but only 30% of the atlas measured → guard blocked (frac<0.5) →
    # missingness-distorted sharp tier (the documented EGFR failure mode).
    c = ac.archetype_confidence_caveat(
        _companion(dominant="amp_driver", dom_mass=0.8, stability=0.85, n_meas=9, n_tot=30)
    )
    assert c["reason"] == "phenotype_mixture_low_stability_or_missingness_distorted"
    assert "EGFR" in c["detail"] and "silently" in c["detail"]


# ── TIER (ii) SHARP — analog / label circular (non-canonical dominant, derived analog label) ────────
def test_analog_label_circular_fires_sharp():
    c = ac.archetype_confidence_caveat(
        _companion(
            dominant="control_housekeeping", dom_mass=0.5, stability=0.8, analog_derived=True, analog_target="ZZZ3"
        )
    )
    assert c["reason"] == "analog_or_label_circular"
    assert c["tier"] == "sharp" and c["top_analog"] == "ZZZ3"
    assert "22479173" in c["detail"]  # Gillis & Pavlidis 2012 (guilt-by-association circularity)


# ── None path — robust, adequately-measured, curated-label, non-canonical signature → no over-call ──
def test_robust_noncanonical_curated_returns_none():
    assert (
        ac.archetype_confidence_caveat(
            _companion(dominant="control_housekeeping", dom_mass=0.5, stability=0.8, analog_derived=False)
        )
        is None
    )


def test_empty_companion_returns_none():
    assert ac.archetype_confidence_caveat({}) is None
    assert ac.archetype_provenance({}) is None


# ── scorecard_confidence_caveat — illustrative-not-learned, cites RETIRED D2/D3 ─────────────────────
def test_scorecard_confidence_caveat_fires_and_cites_retired_score():
    cc = ac._scorecard_confidence_caveat(0.42)
    assert cc["reason"] == "illustrative_not_learned_orients_not_nominates"
    assert "ORIENTS" in cc["detail"] and "D2/D3" in cc["detail"]
    assert "30226837" in cc["detail"]  # Stoeger 2018 (maturity/study-depth confound)
    assert ac._scorecard_confidence_caveat(None) is None


# ── archetype_provenance quorum ─────────────────────────────────────────────────────────────────────
def test_provenance_quorum_fields():
    p = ac.archetype_provenance(_companion(dominant="snv_driver", dom_mass=0.6, stability=0.82, n_meas=22, n_tot=30))
    assert p["dominant_anchor"] == "snv_driver" and p["dominant_mass"] == 0.6
    assert (
        p["n_measured_axes"] == 22 and p["n_total_axes"] == 30 and p["frac_measured"] == pytest.approx(0.733, abs=1e-2)
    )
    assert p["mixture_stability"] == 0.82
    assert "fusion_driver" in p["anchor_provenance_note"] and "DEFERRED" in p["anchor_provenance_note"]
    assert p["n_unmeasured_subskill_axes"] == 1


# ── DRIFT GUARD: the canonical-anchor container is a SET, never a 2-string tuple ────────────────────
def test_canonical_anchor_container_is_a_set():
    assert isinstance(ac._CANONICAL_ESTABLISHED_ANCHORS, set)
    assert ac._CANONICAL_ESTABLISHED_ANCHORS == {
        "snv_driver",
        "tsg_loss",
        "amp_driver",
        "expression_surface",
        "dependency_essential",
    }
    # every guarded label is a real archetype-weight route (so soft_membership can dominate on it)
    assert ac._CANONICAL_ESTABLISHED_ANCHORS <= set(ac.ARCH_W)


# ── nomination_scorecard carries the scorecard_confidence_caveat (single chokepoint) ────────────────
def test_scorecard_carries_confidence_caveat(atlas: Atlas):
    feat = {k: v for k, v in zip(atlas.feature_order, atlas.X[0]) if v is not None}
    m = atlas.companion(feat, k=6)["soft_membership"]
    sc = ac.nomination_scorecard(feat, m, atlas)
    assert "scorecard_confidence_caveat" in sc
    assert sc["scorecard_confidence_caveat"]["reason"] == "illustrative_not_learned_orients_not_nominates"
    assert sc["verdict"] is None  # still verdict-INERT


def test_scorecard_no_axis_ref_caveat_none():
    class _NoRef:
        axis_ref = {}

    sc = ac.nomination_scorecard({}, {}, _NoRef())
    assert sc["score"] is None and sc["scorecard_confidence_caveat"] is None


# ── companion_from_sub_results attaches the confidence surface (composed == standalone) ─────────────
def _sub_results_from_atlas_row(atlas: Atlas, i: int) -> dict:
    inv_sig = {3.0: "strong", 2.0: "moderate", 1.0: "weak", 0.0: "absent"}
    inv_cor = {3.0: "high", 2.0: "moderate", 1.0: "low", 0.0: "absent"}
    facets: dict = {}
    for key, val in zip(atlas.feature_order, atlas.X[i]):
        if val is None:
            continue
        if key.endswith("::signal"):
            short, _, claim = key[: -len("::signal")].split("::", 2)
            facets.setdefault(short, {}).setdefault(claim, {})["signal"] = inv_sig.get(val, "moderate")
        elif key.endswith("::corrob"):
            short, _, claim = key[: -len("::corrob")].split("::", 2)
            facets.setdefault(short, {}).setdefault(claim, {})["corroboration"] = inv_cor.get(val, "moderate")
    return {
        short: {"synthesis_facet": {"claim_vector": cv}, "fired": [{"rule_id": f"{short}.r1"}]}
        for short, cv in facets.items()
    }


def test_composed_companion_carries_caveats(atlas: Atlas):
    sr = _sub_results_from_atlas_row(atlas, 0)
    c = ac.companion_from_sub_results(sr, atlas, k=5)
    assert "archetype_confidence_caveat" in c  # key present (value may be None on a robust read)
    assert c["archetype_provenance"] is not None and "dominant_anchor" in c["archetype_provenance"]
    assert c["verdict"] is None  # mixture numbers unchanged / still verdict-INERT
    assert sum(c["phenotype_mixture"].values()) == pytest.approx(1.0, abs=1e-2)


# ── the TARGET_ARCHETYPE lens (registry + descriptive + axis_labels) ────────────────────────────────
def test_target_archetype_lens_registered_descriptive():
    assert "target-archetype" in LENSES and LENSES["target-archetype"] is TARGET_ARCHETYPE
    assert TARGET_ARCHETYPE.mode == "descriptive"
    assert TARGET_ARCHETYPE.verdict_key is None  # TOKENLESS descriptive (like combination/target-intrinsic)
    assert set(TARGET_ARCHETYPE.axis_labels) == {"PHENOTYPE", "ANALOG", "PRECEDENT", "NOVELTY", "READINESS"}


def test_target_archetype_query_terms_and_cap():
    from _skills_common.literature_retrieval import _LENS_MAX_TERMS, _LENS_QUERY_TERMS, _lens_terms

    assert "target-archetype" in _LENS_QUERY_TERMS
    assert _LENS_MAX_TERMS["target-archetype"] == 10
    terms = _lens_terms(TARGET_ARCHETYPE)
    # the 5 axis_labels + the front-loaded curated discriminators both survive the bumped cap
    assert "drug target class" in terms and "cell surface antigen" in terms


# ── the bespoke run.py decision builder → 5-axis claim_vector + caveats surfaced as conflicts ───────
def test_decision_builder_claim_vector_axes_and_conflicts():
    run = _run_module()
    comp = _companion(dominant="amp_driver", dom_mass=0.7, stability=0.45)  # low-stability sharp
    comp["archetype_confidence_caveat"] = ac.archetype_confidence_caveat(comp)
    sc = {
        "score": 0.4,
        "coverage": 0.6,
        "dominant_archetype_soft": "amp_driver",
        "driving_axes": [{"axis": "genomic_alteration"}],
        "counterfactual_gap": {"limiting_axis": "safety"},
        "scorecard_confidence_caveat": ac._scorecard_confidence_caveat(0.4),
    }
    cv = run._archetype_claim_vector(comp, sc)
    assert set(cv) == {"PHENOTYPE", "ANALOG", "PRECEDENT", "NOVELTY", "READINESS"}
    assert all("signal" in cv[a] for a in cv)
    # the low-stability caveat surfaces as a CONFLICT flag on PHENOTYPE; the illustrative-weight caveat on READINESS
    assert cv["PHENOTYPE"]["conflict"] and "UNSTABLE" in cv["PHENOTYPE"]["conflict"]
    assert cv["READINESS"]["conflict"]  # always-present illustrative-weight note
    d = run._build_decision(comp, sc, "EGFR", "LUAD")
    assert d["target"] == "EGFR" and d["headline"]["claim_vector"] is not None
    assert d["headline"]["key_signals"]["caveat"]  # primary caveat surfaced to narrator + lit lane
    assert d["cards"] == [] and d["headline"]["evidence_capsules"]["manifest"] == []
