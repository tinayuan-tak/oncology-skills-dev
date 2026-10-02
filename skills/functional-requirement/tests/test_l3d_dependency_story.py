"""Guards for the functional-requirement (dependency) L3d "dependency biology story" (SK#2488).

The L3d object is a WITHIN-DOMAIN, deterministic, claim-ID-traceable synthesis over the dependency L2b
concordance islands. These tests pin the properties the architecture requires (mirroring the
tumor-presence / cis-feature-coherence reference L3d guards, SK#1940/#1981):
  * DETERMINISTIC / byte-stable (no LLM), key OMITTED when no island resolves.
  * every chapter cites the L2b claim ID it rests on and names the vector it reconstructs from —
    exercised against a REAL claim vector RE-DERIVED in-test from representative raw cards (never a
    stored derived fixture).
  * WITHIN-DOMAIN only — cross_domain_claims is an always-empty machine-checkable floor (a governance
    pin), and every chapter aspect is inside the dependency semantic scope.
  * the readable L3d layer is declared in evidence_frame.reference_emitted_layers at the
    DOMAIN_INTERPRETATION layer, in lockstep with the emitted key.
  * the forward-declared aspects (expression_dependency / chemical_genetic_concordance) never resolve
    today (dependency_claims.py carries no such island) — a chapter appears ONLY for an island actually
    present on the vector.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
SKILLS_ROOT = SKILL_DIR.parent
SCRIPTS = SKILL_DIR / "scripts"
for p in (str(SKILLS_ROOT), str(SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

from _skills_common.dependency_claims import dependency_claim_vector  # noqa: E402
from dependency_l3d_story import (  # noqa: E402
    L3D_STORY_PROPERTY_ID,
    build_dependency_biology_story,
)

# The one dependency L2b island that actually resolves today, plus the two forward-declared aspects
# that never resolve on this vector yet (no card populates them).
_EXPECTED_ASPECTS = {"essentiality_concordance", "expression_dependency", "chemical_genetic_concordance"}
_RESOLVING_CLAIM_ID = "crispr_rnai_essentiality_concordance"


def _kras_headline():
    """Minimal KRAS/COADREAD-shaped headline — only the DEP/SEL/COND/CHEM axis fields the four claim
    axes read; the essentiality-concordance claim reads the CARDS directly, not this headline."""
    return {
        "crispr_call": "strongly_selective",
        "rnai_call": "strongly_selective",
        "concordance_call": "moderately_concordant_non_dependent",
        "lineage_selectivity": "lineage_selective",
        "n_lineages_evaluated": 26,
        "cross_consortium_class": "concordant_dependent",
        "predictability_class": "own_omics_driven",
        "partner_conditional_class": "no_partner_mapped",
        "partner_stratification_q": None,
        "n_partner_deficient": None,
        "prism_concordance_class": "triangulated_target_engaged",
        "n_compounds_evaluated": 21,
    }


def _ess_cards(crispr="common_essential", rnai="common_essential"):
    """Card set carrying the two orthogonal-assay essentiality tokens that resolve
    `crispr_rnai_essentiality_concordance` (mirrors test_dependency_claims.py's `_ess_cards`)."""
    crispr_summary = {"bimodality_coefficient": 0.70, "distribution_shape": "bimodal_selective"}
    if crispr is not None:
        crispr_summary["dependency_class"] = crispr
    rnai_summary = {}
    if rnai is not None:
        rnai_summary["rnai_dependency_class"] = rnai
    return [
        {"card_id": "pan-cancer-crispr-dependency-distribution", "summary": crispr_summary},
        {"card_id": "pan-cancer-rnai-dependency-distribution", "summary": rnai_summary},
    ]


def _real_claim_vector(crispr="common_essential", rnai="broadly_dependent"):
    """RE-DERIVE a real dependency claim vector in-test from raw card summaries — never a stored derived
    value. Resolves the essentiality-concordance island (both assays agree -> concordant_dependent)."""
    return dependency_claim_vector(_kras_headline(), _ess_cards(crispr=crispr, rnai=rnai))


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
    assert build_dependency_biology_story({}) is None
    assert build_dependency_biology_story(None) is None
    # A vector carrying only the leg axes (no concordance island) still yields no story.
    assert build_dependency_biology_story({"DEP": {"signal": "strong"}}) is None


def test_story_is_deterministic_byte_stable():
    """Two builds over the same (deep-copied) real inputs are byte-identical — golden-snapshottable, no LLM."""
    cv = _real_claim_vector()
    a = build_dependency_biology_story(copy.deepcopy(cv))
    b = build_dependency_biology_story(copy.deepcopy(cv))
    assert a is not None
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    assert a["integration_method"] == "deterministic_template_traversal"
    assert a["layer"] == "L3d"
    assert a["domain"] == "dependency"


# ── claim-ID traceability (against a REAL re-derived claim vector) ──────────────────────────────────
def test_every_chapter_cites_a_claim_id_present_on_the_real_vector():
    """The downward-reconstruction contract: each chapter's claim_id must actually resolve on the
    dependency claim vector it names — so a consumer can index straight back into the L2 claims."""
    cv = _real_claim_vector()
    story = build_dependency_biology_story(cv)
    assert story is not None and story["chapters"]
    for ch in story["chapters"]:
        assert ch["aspect"] in _EXPECTED_ASPECTS
        assert ch["reconstructable_from"] == "claim_vector"
        assert ch["claim_id"] in cv, f"chapter {ch['aspect']} cites {ch['claim_id']} not present on the vector"
        # the chapter re-uses the island's OWN deterministic prose (not re-authored)
        assert ch["reads"] == (cv[ch["claim_id"]].get("positive_signal") or {}).get("statement")
    # provenance mirrors the chapters' (claim_id, vector) pairs — no cited id the chapters don't carry
    prov = {(p["claim_id"], p["vector"]) for p in story["provenance"]["claim_ids"]}
    chap = {(ch["claim_id"], ch["reconstructable_from"]) for ch in story["chapters"]}
    assert prov == chap


def test_kras_packages_only_the_resolving_island_today():
    cv = _real_claim_vector()
    story = build_dependency_biology_story(cv)
    aspects = [ch["aspect"] for ch in story["chapters"]]
    # today ONLY the essentiality-concordance island resolves on a real card-derived vector; the two
    # forward-declared aspects (expression_dependency / chemical_genetic_concordance) have no card.
    assert aspects == ["essentiality_concordance"]
    assert story["headline"] == story["chapters"][0]["reads"]
    assert story["chapters"][0]["claim_id"] == _RESOLVING_CLAIM_ID


# ── within-domain floor (L3d, not L3f) ──────────────────────────────────────────────────────────────
def test_story_makes_no_cross_domain_claim():
    """L3d must never conclude what needs another domain's evidence — cross_domain_claims is an
    always-empty machine-checkable floor, and the scope explicitly excludes the other domains."""
    cv = _real_claim_vector()
    story = build_dependency_biology_story(cv)
    assert story["cross_domain_claims"] == []
    assert story["domain"] == "dependency"
    assert story["layer"] == "L3d"
    excl = set(story["scope"]["excludes"])
    assert {"tumor_selectivity", "on_target_safety", "tractability"} <= excl
    # every chapter aspect is inside the dependency semantic scope (no leaked foreign aspect)
    assert {ch["aspect"] for ch in story["chapters"]} <= _EXPECTED_ASPECTS


def test_cross_domain_claims_empty_across_every_island_subset():
    """Governance pin: cross_domain_claims is [] for EVERY combination of resolved islands, never
    populated by any traversal path (the machine-checkable within-domain floor)."""
    islands = {
        "crispr_rnai_essentiality_concordance": _mk_island("essentiality_concordant_dependent"),
        "expression_dependency_concordance": _mk_island("expression_dependency_single_modality_only", "single_arm"),
        "prism_crispr_concordance": _mk_island("some_future_class", "low", True),
    }
    keys = list(islands)
    for mask in range(1, 1 << len(keys)):
        cv = {keys[i]: islands[keys[i]] for i in range(len(keys)) if mask & (1 << i)}
        story = build_dependency_biology_story(cv)
        assert story is not None
        assert story["cross_domain_claims"] == []
        assert {ch["aspect"] for ch in story["chapters"]} <= _EXPECTED_ASPECTS


# ── coherence derivation (deterministic synthesis token, NOT a verdict) ─────────────────────────────
def test_coherence_anchors_on_the_central_essentiality_node():
    concordant = {"crispr_rnai_essentiality_concordance": _mk_island("essentiality_concordant_dependent")}
    assert build_dependency_biology_story(concordant)["coherence"] == "cross_assay_corroborated"

    concordant_boundary = {
        "crispr_rnai_essentiality_concordance": _mk_island("essentiality_concordant_dependent", "single_arm", True)
    }
    assert (
        build_dependency_biology_story(concordant_boundary)["coherence"]
        == "cross_assay_corroborated_boundary_sensitive"
    )

    discordant = {"crispr_rnai_essentiality_concordance": _mk_island("essentiality_assay_discordant", "low", True)}
    assert build_dependency_biology_story(discordant)["coherence"] == "cross_assay_discordant"

    single = {"crispr_rnai_essentiality_concordance": _mk_island("essentiality_single_assay_only", "single_arm", True)}
    assert build_dependency_biology_story(single)["coherence"] == "single_assay_read"


def test_coherence_without_the_central_node_falls_back_to_peripheral():
    # the central island absent, only a forward-declared peripheral island resolves
    peripheral = {"expression_dependency_concordance": _mk_island("expression_dependency_concordant_coupled")}
    assert build_dependency_biology_story(peripheral)["coherence"] == "peripheral_islands_only"


def test_caveats_are_aggregated_and_claim_id_tagged():
    cv = {
        "crispr_rnai_essentiality_concordance": _mk_island(
            "essentiality_single_assay_only", "single_arm", True, caveat="a single-assay caveat"
        ),
    }
    story = build_dependency_biology_story(cv)
    assert any(
        c["claim_id"] == "crispr_rnai_essentiality_concordance"
        and c["aspect"] == "essentiality_concordance"
        and c["caveat"] == "a single-assay caveat"
        for c in story["caveats"]
    )


# ── readable-layer declaration lockstep ─────────────────────────────────────────────────────────────
def test_l3d_layer_declared_in_reference_emitted_layers_at_domain_interpretation():
    import _skills_common.evidence_frame as ef

    layers = ef.reference_emitted_layers()
    # lockstep: the emitted key equals the evidence_frame constant, declared at the L3d layer
    assert L3D_STORY_PROPERTY_ID == ef.DEPENDENCY_BIOLOGY_STORY_L3D
    assert layers[L3D_STORY_PROPERTY_ID] == ef.ClaimType.DOMAIN_INTERPRETATION
    # L3d sits STRICTLY between L2b (integrated_property) and L3f (decision_frame)
    lyr = ef.CLAIM_TYPE_LAYER
    assert (
        lyr[ef.ClaimType.INTEGRATED_PROPERTY]
        < lyr[ef.ClaimType.DOMAIN_INTERPRETATION]
        < lyr[ef.ClaimType.DECISION_FRAME]
    )
    # the story is NOT registered as a frame (L3d is not L3f) — this domain's own L3f reference frame
    # (`corroborated_dependency_priority`, dependency_priority_frame) is untouched by this declaration.
    assert L3D_STORY_PROPERTY_ID not in {f.frame_id for f in ef.FRAME_REGISTRY}
    # declaring the readable layer does not break acyclicity
    ef.assert_acyclic(ef.FRAME_REGISTRY, layers)
