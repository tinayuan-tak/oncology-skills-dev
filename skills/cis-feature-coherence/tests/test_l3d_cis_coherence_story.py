"""Guards for the cis-feature-coherence L3d "cis-regulatory coherence biology story" (SK#1981).

The L3d object is a WITHIN-DOMAIN, deterministic, claim-ID-traceable synthesis over the cis L2b
concordance islands. These tests pin the properties the architecture requires (mirroring the
tumor-presence reference L3d guards, SK#1940):
  * DETERMINISTIC / byte-stable (no LLM), key OMITTED when no island resolves.
  * every chapter cites the L2b claim ID it rests on and names the vector it reconstructs from —
    exercised against a REAL claim vector RE-DERIVED in-test from representative raw cards (never a
    stored derived fixture).
  * WITHIN-DOMAIN only — cross_domain_claims is an always-empty machine-checkable floor (a governance
    pin), and every chapter aspect is inside the cis-coherence semantic scope.
  * the readable L3d layer is declared in evidence_frame.reference_emitted_layers at the
    DOMAIN_INTERPRETATION layer, in lockstep with the emitted key.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import yaml

SKILL_DIR = Path(__file__).resolve().parent.parent
SKILLS_ROOT = SKILL_DIR.parent
SCRIPTS = SKILL_DIR / "scripts"
for p in (str(SKILLS_ROOT), str(SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

from _skills_common.cis_coherence_claims import cis_coherence_claim_vector  # noqa: E402
from cis_coherence_l3d_story import (  # noqa: E402
    L3D_STORY_PROPERTY_ID,
    build_cis_coherence_biology_story,
)

FIXTURE_DIR = SKILL_DIR / "tests" / "fixtures"

# The three cis L2b islands the story packages, all keyed on the SINGLE cis claim vector.
_EXPECTED_ASPECTS = {"cis_dosage", "methylation_silencing", "expression_dependency"}
_CLAIM_IDS = {
    "cis_dosage_concordance",
    "methylation_silencing_concordance",
    "expression_dependency_concordance",
}


def _real_claim_vector(fixture_name: str = "replay_coherent_cis_driver.yaml") -> dict:
    """RE-DERIVE a real cis claim vector in-test from a replay fixture's RAW card summaries — never a
    stored derived value (#1780 discipline). The ERBB2/BRCA fixture resolves all three concordance
    islands (cis-dosage coupled cross-grain, silencing single-grain, expression->dependency cross-modality)."""
    fx = yaml.safe_load((FIXTURE_DIR / fixture_name).read_text()) or {}
    cards = [{"card_id": cid, "summary": summary} for cid, summary in fx["cards"].items()]
    return cis_coherence_claim_vector({}, cards)


def _mk_island(concordance_class, corroboration="high", boundary_sensitive=False, caveat=None):
    """A minimal L2b-shaped island: only the fields the L3d traversal reads."""
    isl = {
        "concordance_class": concordance_class,
        "corroboration": corroboration,
        "boundary_sensitive": boundary_sensitive,
        "positive_signal": {"statement": f"positive read for {concordance_class}", "source": "s"},
        "informs": "the within-domain property",
    }
    if caveat is not None:
        isl["qualifying_signal"] = {"statement": caveat, "source": "s"}
    return isl


# ── determinism / omission ────────────────────────────────────────────────────────────────────────
def test_no_island_resolves_omits_the_story_byte_stable():
    """No L2b island on the vector -> None (key omitted -> byte-stable), matching the atom discipline."""
    assert build_cis_coherence_biology_story({}) is None
    assert build_cis_coherence_biology_story(None) is None
    # A vector carrying only the leg axes (no concordance island) still yields no story.
    assert build_cis_coherence_biology_story({"CIS_DOSAGE": {"signal": "strong"}}) is None


def test_story_is_deterministic_byte_stable():
    """Two builds over the same (deep-copied) real inputs are byte-identical — golden-snapshottable, no LLM."""
    cv = _real_claim_vector()
    a = build_cis_coherence_biology_story(copy.deepcopy(cv))
    b = build_cis_coherence_biology_story(copy.deepcopy(cv))
    assert a is not None
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    assert a["integration_method"] == "deterministic_template_traversal"
    assert a["layer"] == "L3d"
    assert a["domain"] == "cis_feature_coherence"


# ── claim-ID traceability (against a REAL re-derived claim vector) ──────────────────────────────────
def test_every_chapter_cites_a_claim_id_present_on_the_real_vector():
    """The downward-reconstruction contract: each chapter's claim_id must actually resolve on the cis
    claim vector it names — so a consumer can index straight back into the L2 claims."""
    cv = _real_claim_vector()
    story = build_cis_coherence_biology_story(cv)
    assert story is not None and story["chapters"]
    for ch in story["chapters"]:
        assert ch["aspect"] in _EXPECTED_ASPECTS
        assert ch["reconstructable_from"] == "cis_claim_vector"
        assert ch["claim_id"] in _CLAIM_IDS
        # the cited claim_id is a real key on the re-derived vector
        assert ch["claim_id"] in cv, f"chapter {ch['aspect']} cites {ch['claim_id']} not present on the cis vector"
        # the chapter re-uses the island's OWN deterministic prose (not re-authored)
        assert ch["reads"] == (cv[ch["claim_id"]].get("positive_signal") or {}).get("statement")
    # provenance mirrors the chapters' (claim_id, vector) pairs — no cited id the chapters don't carry
    prov = {(p["claim_id"], p["vector"]) for p in story["provenance"]["claim_ids"]}
    chap = {(ch["claim_id"], ch["reconstructable_from"]) for ch in story["chapters"]}
    assert prov == chap


def test_erbb2_packages_the_three_cis_islands_in_canonical_order():
    cv = _real_claim_vector()
    story = build_cis_coherence_biology_story(cv)
    aspects = [ch["aspect"] for ch in story["chapters"]]
    # ERBB2/BRCA resolves all three concordance families; order is the stable canonical order.
    assert aspects == ["cis_dosage", "methylation_silencing", "expression_dependency"]
    # headline leads with the first resolved island's OWN prose (cis-dosage, present here)
    assert story["headline"] == story["chapters"][0]["reads"]


# ── within-domain floor (L3d, not L3f) ──────────────────────────────────────────────────────────────
def test_story_makes_no_cross_domain_claim():
    """L3d must never conclude what needs another domain's evidence — cross_domain_claims is an
    always-empty machine-checkable floor, and the scope explicitly excludes the other domains."""
    cv = _real_claim_vector()
    story = build_cis_coherence_biology_story(cv)
    assert story["cross_domain_claims"] == []
    assert story["domain"] == "cis_feature_coherence"
    assert story["layer"] == "L3d"
    excl = set(story["scope"]["excludes"])
    assert {"tumor_selectivity", "on_target_safety", "tractability"} <= excl
    # every chapter aspect is inside the cis-coherence semantic scope (no leaked foreign aspect)
    assert {ch["aspect"] for ch in story["chapters"]} <= _EXPECTED_ASPECTS


def test_cross_domain_claims_empty_across_every_island_subset():
    """Governance pin: cross_domain_claims is [] for EVERY combination of resolved islands, never
    populated by any traversal path (the machine-checkable within-domain floor)."""
    islands = {
        "cis_dosage_concordance": _mk_island("cis_dosage_concordant_coupled"),
        "methylation_silencing_concordance": _mk_island("methylation_silencing_grain_discordant", "low", True),
        "expression_dependency_concordance": _mk_island("expression_dependency_single_modality_only", "single_arm"),
    }
    keys = list(islands)
    for mask in range(1, 1 << len(keys)):
        cv = {keys[i]: islands[keys[i]] for i in range(len(keys)) if mask & (1 << i)}
        story = build_cis_coherence_biology_story(cv)
        assert story is not None
        assert story["cross_domain_claims"] == []
        assert {ch["aspect"] for ch in story["chapters"]} <= _EXPECTED_ASPECTS


# ── coherence derivation (deterministic synthesis token, NOT a verdict) ─────────────────────────────
def test_coherence_flags_a_cross_arm_discordance():
    cv = {
        "cis_dosage_concordance": _mk_island("cis_dosage_concordant_coupled"),
        "methylation_silencing_concordance": _mk_island("methylation_silencing_grain_discordant", "low", True),
    }
    story = build_cis_coherence_biology_story(cv)
    assert story["coherence"] == "within_domain_discordant"


def test_coherence_multi_axis_vs_single_axis():
    two = {
        "cis_dosage_concordance": _mk_island("cis_dosage_concordant_coupled"),
        "expression_dependency_concordance": _mk_island("expression_dependency_concordant_coupled"),
    }
    assert build_cis_coherence_biology_story(two)["coherence"] == "cross_axis_corroborated"
    two_boundary = {
        "cis_dosage_concordance": _mk_island("cis_dosage_concordant_coupled", "single_arm", True),
        "expression_dependency_concordance": _mk_island("expression_dependency_concordant_coupled"),
    }
    assert build_cis_coherence_biology_story(two_boundary)["coherence"] == "cross_axis_corroborated_boundary_sensitive"
    one = {"cis_dosage_concordance": _mk_island("cis_dosage_single_grain_only", "single_arm", True)}
    assert build_cis_coherence_biology_story(one)["coherence"] == "single_axis_boundary_sensitive"
    one_hard = {"expression_dependency_concordance": _mk_island("expression_dependency_concordant_coupled")}
    assert build_cis_coherence_biology_story(one_hard)["coherence"] == "single_axis_read"


def test_caveats_are_aggregated_and_claim_id_tagged():
    cv = {
        "cis_dosage_concordance": _mk_island(
            "cis_dosage_single_grain_only", "single_arm", True, caveat="a dosage caveat"
        ),
    }
    story = build_cis_coherence_biology_story(cv)
    assert any(
        c["claim_id"] == "cis_dosage_concordance" and c["aspect"] == "cis_dosage" and c["caveat"] == "a dosage caveat"
        for c in story["caveats"]
    )


# ── readable-layer declaration lockstep ─────────────────────────────────────────────────────────────
def test_l3d_layer_declared_in_reference_emitted_layers_at_domain_interpretation():
    import _skills_common.evidence_frame as ef

    layers = ef.reference_emitted_layers()
    # lockstep: the emitted key equals the evidence_frame constant, declared at the L3d layer
    assert L3D_STORY_PROPERTY_ID == ef.CIS_COHERENCE_BIOLOGY_STORY_L3D
    assert layers[L3D_STORY_PROPERTY_ID] == ef.ClaimType.DOMAIN_INTERPRETATION
    # L3d sits STRICTLY between L2b (integrated_property) and L3f (decision_frame)
    lyr = ef.CLAIM_TYPE_LAYER
    assert (
        lyr[ef.ClaimType.INTEGRATED_PROPERTY]
        < lyr[ef.ClaimType.DOMAIN_INTERPRETATION]
        < lyr[ef.ClaimType.DECISION_FRAME]
    )
    # the story is NOT registered as a frame (L3d is not L3f)
    assert L3D_STORY_PROPERTY_ID not in {f.frame_id for f in ef.FRAME_REGISTRY}
    # declaring the readable layer does not break acyclicity
    ef.assert_acyclic(ef.FRAME_REGISTRY, layers)
