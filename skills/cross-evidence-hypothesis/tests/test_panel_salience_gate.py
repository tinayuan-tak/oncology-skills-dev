"""Salience gate for the claim-vector panel (_render_claim_vectors): keep decision-relevant atoms
PRIMARY (full citable values) — including LOW-TIER-but-notable atoms (the BRAF/SKCM case) — and collapse
truly-uninformative claims to one-line tiers, so the panel scales legibly as atom fan-in grows toward
13 axes. Pure / offline."""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(SCRIPTS.parent.parent))   # skills/ for _skills_common

import run as R  # noqa: E402


def _cvs(**axes):
    return {"dependency": {"claim_vector": {**axes, "_disclaimer": "x"},
                           "key_signals": {"headline": "Selective dependency."}}}


def _claim(signal, values=None, conflict=None, cite="pan-cancer-crispr-dependency-distribution"):
    atom = {"read": signal, "values": values or {}, "cite": {"card_id": cite}} if values is not None else None
    return {"signal": signal, "corroboration": "high", "conflict": conflict, "evidence_atom": atom}


def test_informative_tier_is_primary_with_full_values():
    txt = R._render_claim_vectors(_cvs(DEP=_claim("strong", {"bimodality_coefficient": 0.70})))
    prim = txt.split("SECONDARY (tier-only):")[0]
    assert "[dependency.DEP]" in prim
    assert "bimodality_coefficient" in prim and "0.7" in prim
    assert "pan-cancer-crispr-dependency-distribution" in prim   # card_id stays citable


def test_notable_low_tier_atom_stays_primary_BRAF_case():
    # tier=unmeasured (non_dependent_underpowered) BUT a nonzero responder fraction + bimodality reveal a
    # hidden subpopulation → MUST stay PRIMARY (the exact atom that drove the BRAF/SKCM win).
    txt = R._render_claim_vectors(_cvs(DEP=_claim("unmeasured",
                                   {"fraction_strongly_dependent": 0.039, "bimodality_coefficient": 0.62})))
    prim = txt.split("SECONDARY (tier-only):")[0]
    assert "[dependency.DEP]" in prim and "fraction_strongly_dependent" in prim   # full values kept


def test_uninformative_claim_collapses_to_secondary_tier_only():
    txt = R._render_claim_vectors(_cvs(COND=_claim("unmeasured",
                                   {"partner_stratification_class": "no_partner_mapped"})))
    assert "SECONDARY (tier-only):" in txt
    sec = txt.split("SECONDARY (tier-only):")[1]
    assert "[dependency.COND]" in sec              # present…
    assert "no_partner_mapped" not in sec          # …but its (non-notable) value is dropped


def test_conflict_forces_primary():
    txt = R._render_claim_vectors(_cvs(CHEM=_claim("weak", {"n_compounds_evaluated": 9},
                                                   conflict="compound kill likely off-target")))
    prim = txt.split("SECONDARY (tier-only):")[0]
    assert "conflict" in prim and "off-target" in prim


def test_empty_claim_vectors_render_nothing():
    assert R._render_claim_vectors({}) == ""
