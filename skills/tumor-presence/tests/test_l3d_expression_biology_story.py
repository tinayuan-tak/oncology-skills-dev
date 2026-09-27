"""Guards for the tumor-presence L3d "tumor-expression biology story" (SK#1940).

The L3d object is a WITHIN-DOMAIN, deterministic, claim-ID-traceable synthesis over the presence L2b
islands. These tests pin the properties the architecture requires:
  * DETERMINISTIC / byte-stable (no LLM), key OMITTED when no island resolves.
  * every chapter cites the L2b claim ID it rests on and names the vector it reconstructs from.
  * WITHIN-DOMAIN only — cross_domain_claims is an always-empty machine-checkable floor, and every
    chapter aspect is inside the presence semantic scope.
  * the readable L3d layer is declared in evidence_frame.reference_emitted_layers at the
    DOMAIN_INTERPRETATION layer, in lockstep with the emitted key.
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

from presence_l3d_story import (  # noqa: E402
    L3D_STORY_PROPERTY_ID,
    build_tumor_expression_biology_story,
)

GOLDEN = SKILL_DIR / "tests" / "fixtures" / "epcam_coadread_decision.json"

# The five presence L2b islands the story packages, and the vector each is keyed on.
_EXPECTED_ASPECTS = {"tumor_presence", "coverage", "abundance", "protein_presence", "subtype_restriction"}
_POOLED_CLAIM_IDS = {
    "tumor_presence_concordance",
    "bulk_vs_singlecell_coverage_concordance",
    "abundance_concordance",
    "protein_presence_concordance",
}
_BY_SUBTYPE_CLAIM_ID = "subtype_restriction_concordance"


def _epcam_vectors():
    d = json.loads(GOLDEN.read_text())
    h = d["headline"]
    return h.get("claim_vector") or {}, h.get("claim_vector_by_subtype")


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
    assert build_tumor_expression_biology_story({}, None) is None
    assert build_tumor_expression_biology_story(None, None) is None
    # A vector carrying only A/B/C/D (no concordance island) still yields no story.
    assert build_tumor_expression_biology_story({"A": {"signal": "strong"}}, None) is None


def test_story_is_deterministic_byte_stable():
    """Two builds over the same (deep-copied) inputs are byte-identical — golden-snapshottable, no LLM."""
    cv, cvbs = _epcam_vectors()
    a = build_tumor_expression_biology_story(copy.deepcopy(cv), copy.deepcopy(cvbs))
    b = build_tumor_expression_biology_story(copy.deepcopy(cv), copy.deepcopy(cvbs))
    assert a is not None
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    assert a["integration_method"] == "deterministic_template_traversal"


# ── claim-ID traceability ───────────────────────────────────────────────────────────────────────
def test_every_chapter_cites_a_claim_id_present_on_its_named_vector():
    """The downward-reconstruction contract: each chapter's claim_id must actually resolve on the vector
    it names — so a consumer can index straight back into the L2 claims."""
    cv, cvbs = _epcam_vectors()
    story = build_tumor_expression_biology_story(cv, cvbs)
    assert story is not None and story["chapters"]
    vectors = {"pooled_claim_vector": cv, "by_subtype_claim_vector": cvbs or {}}
    for ch in story["chapters"]:
        assert ch["aspect"] in _EXPECTED_ASPECTS
        assert ch["reconstructable_from"] in vectors
        # the cited claim_id is a real key on the named vector
        assert ch["claim_id"] in vectors[ch["reconstructable_from"]], (
            f"chapter {ch['aspect']} cites {ch['claim_id']} not present on {ch['reconstructable_from']}"
        )
    # provenance mirrors the chapters' (claim_id, vector) pairs — no cited id the chapters don't carry
    prov = {(p["claim_id"], p["vector"]) for p in story["provenance"]["claim_ids"]}
    chap = {(ch["claim_id"], ch["reconstructable_from"]) for ch in story["chapters"]}
    assert prov == chap


def test_epcam_packages_the_pooled_islands_with_a_corroborated_central_node():
    cv, cvbs = _epcam_vectors()
    story = build_tumor_expression_biology_story(cv, cvbs)
    aspects = {ch["aspect"] for ch in story["chapters"]}
    # EPCAM/COADREAD resolves the central node + the three pooled modality-pair concordances.
    assert {"tumor_presence", "coverage", "abundance", "protein_presence"} <= aspects
    assert story["coherence"] in {"cross_source_corroborated", "cross_source_corroborated_boundary_sensitive"}
    central = next(ch for ch in story["chapters"] if ch["aspect"] == "tumor_presence")
    assert central["claim_id"] == "tumor_presence_concordance"
    assert story["headline"] == central["reads"]  # headline leads with the central node's own prose


# ── within-domain floor (L3d, not L3f) ────────────────────────────────────────────────────────────
def test_story_makes_no_cross_domain_claim():
    """L3d must never conclude what needs another domain's evidence — cross_domain_claims is an
    always-empty machine-checkable floor, and the scope explicitly excludes the other domains."""
    cv, cvbs = _epcam_vectors()
    story = build_tumor_expression_biology_story(cv, cvbs)
    assert story["cross_domain_claims"] == []
    assert story["domain"] == "tumor_presence"
    assert story["layer"] == "L3d"
    excl = set(story["scope"]["excludes"])
    assert {"tumor_selectivity", "on_target_safety", "tractability"} <= excl
    # every chapter aspect is inside the presence semantic scope (no leaked foreign aspect)
    assert {ch["aspect"] for ch in story["chapters"]} <= _EXPECTED_ASPECTS


# ── coherence derivation (deterministic synthesis token, NOT a verdict) ─────────────────────────────
def test_coherence_anchors_on_the_central_node_concordance_class():
    cases = {
        ("tumor_presence_concordant", "high", False): "cross_source_corroborated",
        ("tumor_presence_concordant", "low", True): "cross_source_corroborated_boundary_sensitive",
        ("tumor_presence_discordant", "low", True): "cross_source_discordant",
        ("single_source_only", "single_arm", True): "single_source_read",
    }
    for (cls, corr, boundary), expected in cases.items():
        cv = {"tumor_presence_concordance": _mk_island(cls, corr, boundary)}
        story = build_tumor_expression_biology_story(cv, None)
        assert story["coherence"] == expected, f"{cls}/{corr}/boundary={boundary} -> {story['coherence']}"


def test_peripheral_islands_only_when_no_central_node():
    """Central node absent but a peripheral island resolves -> the story names it rests on peripherals."""
    cv = {"abundance_concordance": _mk_island("abundance_concordant")}
    story = build_tumor_expression_biology_story(cv, None)
    assert story is not None
    assert story["coherence"] == "peripheral_islands_only"
    assert [ch["aspect"] for ch in story["chapters"]] == ["abundance"]


def test_subtype_restriction_chapter_is_sourced_from_the_by_subtype_vector():
    cv = {"tumor_presence_concordance": _mk_island("tumor_presence_concordant")}
    cvbs = {"subtype_restriction_concordance": _mk_island("no_subtype_restriction", caveat="a restriction caveat")}
    story = build_tumor_expression_biology_story(cv, cvbs)
    sub = next(ch for ch in story["chapters"] if ch["aspect"] == "subtype_restriction")
    assert sub["reconstructable_from"] == "by_subtype_claim_vector"
    assert sub["claim_id"] == _BY_SUBTYPE_CLAIM_ID
    # its caveat is aggregated into the story-level caveats, tagged with the claim id
    assert any(c["claim_id"] == _BY_SUBTYPE_CLAIM_ID and c["aspect"] == "subtype_restriction" for c in story["caveats"])


# ── readable-layer declaration lockstep ─────────────────────────────────────────────────────────────
def test_l3d_layer_declared_in_reference_emitted_layers_at_domain_interpretation():
    import _skills_common.evidence_frame as ef

    layers = ef.reference_emitted_layers()
    # lockstep: the emitted key equals the evidence_frame constant, declared at the L3d layer
    assert L3D_STORY_PROPERTY_ID == ef.TUMOR_EXPRESSION_BIOLOGY_STORY_L3D
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
