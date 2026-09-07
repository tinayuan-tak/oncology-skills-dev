"""Unit tests for the VERDICT-INERT intrinsic_confirmation_caveat + intrinsic_provenance (v1.6.0).

Pure-function tests over run.py's caveat builder (no S3 / no dispatcher): the experimental-vs-predicted
trap adjudication, the pan-target false-demote GUARD (crosswalk + experimental_ligandable), the SHARP
prediction/homology over-call, the annotation/meta-score tier, the None byte-stable path, and the
DUAL-PATH contract (both _headline and the self-contained _synthesis_facet must declare target/indication
and carry the two new fields — the facet dict is target-intrinsic's fan-out carrier).
"""
from __future__ import annotations

import inspect
from pathlib import Path

from _test_support import load_run_py

SKILL_DIR = Path(__file__).resolve().parent.parent

RUN = load_run_py(SKILL_DIR, "ti_run_under_test")


def _cards(**by_card):
    """Build a cards list from {card_id: {field: value}} — the shape resolve_cards emits."""
    return [{"card_id": cid, "summary": summary} for cid, summary in by_card.items()]


# ── the caveat builder (pure) ────────────────────────────────────────────────────────────────────

def test_guard_experimental_ligandable_is_not_demoted():
    """experimental_ligandable (co-crystal) → MILDER experimentally_confirmed_intrinsic_property guard —
    NOT flagged as inflated (the BRAF/EGFR/KRAS-G12C class)."""
    f = {"structural_ligandability_class": "experimental_ligandable", "has_experimental_cocrystal": True,
         "ot_prioritisation_status": "scored", "ot_genetic_band": "unfavorable"}
    cav = RUN._intrinsic_confirmation_caveat("CTNNB1", f)   # NOT in crosswalk → guard via experimental only
    assert cav["reason"] == "experimentally_confirmed_intrinsic_property"
    # the OT double-count is surfaced as an orientation residual, never escalated
    assert "double-count" in cav["note"].lower()


def test_guard_crosswalk_is_data_blind_tolerant():
    """The post-land-sweep requirement: a validated symbol (BRAF/EGFR/KRAS-G12C) stays GUARDED even if the
    structure lane reads it thin / predicted / absent (the #1042 presence-keyed lesson)."""
    for sym in ("BRAF", "EGFR", "KRAS", "DLL3"):
        # structure DELIBERATELY thin/predicted — the crosswalk must still spare it
        f = {"structural_ligandability_class": "predicted_ligandable", "has_experimental_cocrystal": False}
        cav = RUN._intrinsic_confirmation_caveat(sym, f)
        assert cav["reason"] == "experimentally_confirmed_intrinsic_property", (
            f"{sym} demoted despite the validated-property crosswalk (data-blind guard failed): {cav}")


def test_sharp_predicted_ligandable_is_the_driver_over_call():
    """predicted_ligandable / annotation_ligandable with NO co-crystal → SHARP
    predicted_structure_or_homology_annotated_unconfirmed (the MYC / TRIB1 driver)."""
    for tok in ("predicted_ligandable", "annotation_ligandable"):
        f = {"structural_ligandability_class": tok, "has_experimental_cocrystal": False,
             "alphafold_confidence_class": "low", "ligandability_disorder_class": "highly_disordered"}
        cav = RUN._intrinsic_confirmation_caveat("MYC", f)
        assert cav["reason"] == "predicted_structure_or_homology_annotated_unconfirmed", (tok, cav)
        assert "co-crystal" in cav["note"].lower()


def test_sharp_predicted_surface_over_call():
    """is_surface_protein=True with NO experimental HPA plasma-membrane (SURFY/IUPHAR homology) → SHARP."""
    f = {"structural_ligandability_class": "no_ligandability_signal", "is_surface_protein": True,
         "source_hpa_plasma_membrane": False, "surface_protein_family": "kinase_surface"}
    cav = RUN._intrinsic_confirmation_caveat("SOMEGENE", f)
    assert cav["reason"] == "predicted_structure_or_homology_annotated_unconfirmed"
    assert "surface" in cav["note"].lower() or "topology" in cav["note"].lower()


def test_annotation_score_tier_double_count_and_significance():
    """No structural actionability signal, but meta-scores / annotation density present → the
    annotation_score_or_double_counted orientation tier (significance ≠ actionability)."""
    f = {"structural_ligandability_class": "no_ligandability_signal",
         "ot_prioritisation_status": "scored", "ot_genetic_band": "unfavorable",
         "gnomad_constraint_class": "highly_constrained", "go_annotation_class": "well_annotated",
         "tdl_class": "Tbio"}
    cav = RUN._intrinsic_confirmation_caveat("SOMEGENE", f)
    assert cav["reason"] == "annotation_score_or_double_counted"
    assert "double-count" in cav["note"].lower() and "actionability" in cav["note"].lower()


def test_none_path_is_byte_stable():
    """Nothing to adjudicate (all data_unavailable / honest negative) → None (no field escalated)."""
    f = {"structural_ligandability_class": "data_unavailable"}
    assert RUN._intrinsic_confirmation_caveat("SOMEGENE", f) is None
    # empty facet-style fields → None as well
    assert RUN._intrinsic_confirmation_caveat(None, {}) is None


def test_disordered_low_is_not_an_over_call():
    """disordered_low is a MEASURED negative (not predicted actionability) — not the sharp tier; with no
    other annotation it degrades to None, not a false over-call flag."""
    f = {"structural_ligandability_class": "disordered_low"}
    assert RUN._intrinsic_confirmation_caveat("SOMEGENE", f) is None


def test_provenance_double_count_and_confirmed_flag():
    f = {"structural_ligandability_class": "experimental_ligandable",
         "ot_prioritisation_status": "scored", "ot_mouse_ko_band": "unfavorable"}
    prov = RUN._intrinsic_provenance("BRAF", f)
    assert prov["ot_composite_double_counts_dedicated_cards"] is True
    assert prov["experimentally_confirmed_actionable_property"] is True
    assert prov["validated_intrinsic_property_crosswalk_hit"] is True
    # a non-crosswalk predicted target → not confirmed
    prov2 = RUN._intrinsic_provenance("MYC", {"structural_ligandability_class": "predicted_ligandable"})
    assert prov2["experimentally_confirmed_actionable_property"] is False


def test_crosswalk_is_a_set_literal_not_tuple():
    """SET literals, not 2-tuples (a 2-string tuple is misread as a (rule_id, verdict) precedence pair by
    the reference-drift guard)."""
    assert isinstance(RUN._VALIDATED_INTRINSIC_PROPERTY, set)
    assert isinstance(RUN._PREDICTED_LIGANDABILITY, set)


# ── the DUAL-PATH contract (headline + self-contained facet) ───────────────────────────────────────

def test_headline_and_facet_declare_target_and_indication():
    """Both readers must declare target + indication so the dispatcher (headline_fn) and tp_fanout
    (_synthesis_facet) signature-introspection passes the symbol for the crosswalk guard."""
    for fn in (RUN._headline, RUN._synthesis_facet):
        params = inspect.signature(fn).parameters
        assert "target" in params, f"{fn.__name__} missing target param"
        assert "indication" in params, f"{fn.__name__} missing indication param"


def test_tolerant_reader_does_not_raise_on_absent_card():
    """The composed facet resolves only 8 cards; the caveat's field reader must tolerate the absent
    structure/surfaceome/safety cards (get_card_field would otherwise raise KeyError)."""
    cards = _cards(**{"target-development-level": {"tdl_class": "Tchem"},
                      "gene-ontology-annotation": {"annotation_class": "well_annotated"}})
    f = RUN._intrinsic_actionability_fields(cards)
    assert f["structural_ligandability_class"] is None      # absent card → None, not a raise
    assert f["tdl_class"] == "Tchem" and f["go_annotation_class"] == "well_annotated"


def test_facet_carries_caveat_and_provenance_and_guard_survives_thin_composed_cards():
    """The self-contained _synthesis_facet (target-intrinsic's fan-out carrier) must attach both fields,
    and a validated symbol must stay GUARDED even on the thin 8-card composed subset (structure absent)."""
    cards = _cards(**{"domain-modality-relevance": {"modality_implication_class": "inhibitor_sufficient"},
                      "target-development-level": {"tdl_class": "Tclin"},
                      "gene-ontology-annotation": {"annotation_class": "well_annotated"},
                      "ppi-interactome": {"interactome_class": "hub"},
                      "measured-potency-tractability": {"measured_bioactivity_class": "potent_measured_ligand"}})
    facet = RUN._synthesis_facet(cards, [], None, target="BRAF", indication="COADREAD")
    assert "intrinsic_confirmation_caveat" in facet and "intrinsic_provenance" in facet
    assert facet["intrinsic_confirmation_caveat"]["reason"] == "experimentally_confirmed_intrinsic_property"
    # a non-crosswalk target on the same thin subset degrades to the annotation tier (not a false sharp call)
    facet2 = RUN._synthesis_facet(cards, [], None, target="MYC", indication="COADREAD")
    assert facet2["intrinsic_confirmation_caveat"]["reason"] == "annotation_score_or_double_counted"
