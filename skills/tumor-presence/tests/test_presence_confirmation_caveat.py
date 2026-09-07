"""Unit tests for the CONSOLIDATED presence-confirmation surface (v1.20.0):
`_presence_confirmation_caveat` + `_presence_provenance` + `_compartment_note`.

These fold the already-computed confirmation signals (presence_state, protein_confirmation_state,
abundance_floor_flag, sc_expression_class / caf_vs_malignant, cell_line_vs_tumor_direction, HPA-IHC)
into ONE consumer-facing malignant-cell-PROTEIN-confirmed-vs-bulk-RNA/cell-line/stromal call. All
VERDICT-INERT (they read only headline fields, feed no rule). The live panel behaviour they encode:
  * FAP/COADREAD    → malignant_compartment_unconfirmed (the stromal/CAF driver)
  * EPCAM/COADREAD  → protein_confirmed_malignant_present (false-demote guard — not flagged)
  * FOLR1/OV        → protein_confirmed_malignant_present (spared despite an overridden abundance floor)
  * GAPDH/COADREAD  → protein_confirmed_malignant_present + ubiquitous-across-compartments residual
  * MLANA/COADREAD  → None (honest negative; conflict handled by presence_headline_conflict)
Plus the two tiers with NO live panel member (unit-only): the sharp RNA-only tier and the
clinically-precedented-without-data-confirmation spare.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from _test_support import load_run_py


@pytest.fixture(scope="module")
def rp():
    return load_run_py(Path(__file__).resolve().parent.parent, "_tp_run_caveat")


# ── minimal headline builders (only the fields the three functions read) ──────────────────────
def _hl(
    present="yes",
    malignant="yes",
    pcs="confirmed",
    scc="malignant_broadly_detected",
    caf="caf_low",
    floor="adequate_abundance",
    cl_dir=None,
    ihc="ihc_detected_high",
    mal_frac=0.9,
    micro_comp="stromal",
    micro_frac=0.05,
    proxy="adequate",
    rna_tumor="strongly_upregulated_in_tumor",
    rna_cl="broadly_high",
):
    return {
        "presence_state": {"present": present, "malignant_intrinsic": malignant},
        "protein_confirmation_state": pcs,
        "sc_expression_class": scc,
        "sc_caf_vs_malignant_class": caf,
        "abundance_floor_flag": floor,
        "cell_line_vs_tumor_direction": cl_dir,
        "hpa_ihc_protein_presence_class": ihc,
        "sc_malignant_detection_fraction": mal_frac,
        "sc_top_microenvironment_compartment": micro_comp,
        "sc_top_microenvironment_detection_fraction": micro_frac,
        "bulk_rna_proxy_quality": proxy,
        "presence_verdict_by_modality": {
            "bulk_rna/tumor": {"evidence_state": "measured", "verdict": rna_tumor},
            "bulk_rna/cell_line": {"evidence_state": "measured", "verdict": rna_cl},
        },
    }


# ── TIER 1 — malignant compartment unconfirmed (the FAP/stromal driver) ───────────────────────
def test_fap_stromal_compartment_unconfirmed(rp):
    """The DRIVER: bulk protein CONFIRMED but single-cell resolves it to the stroma → the compartment
    tier OUTRANKS the protein-confirmed guard (stromal protein is still protein)."""
    hl = _hl(
        malignant="stroma",
        scc="microenvironment_dominant",
        caf="caf_dominant",
        pcs="confirmed",
        ihc="ihc_detected_high",
        mal_frac=0.0076,
        micro_frac=0.29,
    )
    cav = rp._presence_confirmation_caveat(hl, target="FAP")
    assert cav and cav["reason"] == "malignant_compartment_unconfirmed"
    assert cav["tier"] == "compartment"
    assert "microenvironment" in cav["detail"].lower()


def test_compartment_tier_fires_on_any_of_the_three_signals(rp):
    for kw in ({"malignant": "stroma"}, {"scc": "microenvironment_dominant"}, {"caf": "caf_dominant"}):
        hl = _hl(**kw)
        cav = rp._presence_confirmation_caveat(hl, target="FAP")
        assert cav["reason"] == "malignant_compartment_unconfirmed", kw


# ── TIER 3 — protein-confirmed / clinically-precedented (false-demote guard) ──────────────────
def test_epcam_protein_confirmed_not_flagged(rp):
    hl = _hl(pcs="confirmed", ihc="ihc_detected_high", scc="malignant_broadly_detected")
    cav = rp._presence_confirmation_caveat(hl, target="EPCAM")
    assert cav["reason"] == "protein_confirmed_malignant_present"
    assert cav["tier"] == "confirmed"
    assert "not an over-call" in cav["detail"].lower()


def test_folr1_spared_despite_overridden_abundance_floor(rp):
    """FOLR1: a lone Gygi bottom-decile (single-lens, ProCan-recovered) MUST NOT sharp-caveat a
    protein-confirmed, clinically-precedented antigen — the abundance-floor false-demote guard."""
    hl = _hl(
        pcs="confirmed",
        ihc="data_unavailable",
        floor="present_low_abundance_single_lens",
        scc="malignant_broadly_detected",
    )
    cav = rp._presence_confirmation_caveat(hl, target="FOLR1")
    assert cav["reason"] == "protein_confirmed_malignant_present"
    assert "single-lens" in cav["detail"].lower()


def test_gapdh_confirmed_with_ubiquitous_residual(rp):
    hl = _hl(pcs="confirmed", caf="shared_caf_malignant", scc="malignant_broadly_detected", mal_frac=0.98)
    cav = rp._presence_confirmation_caveat(hl, target="GAPDH")
    assert cav["reason"] == "protein_confirmed_malignant_present"
    assert "ubiquitous" in cav["detail"].lower()


def test_clinically_precedented_without_data_confirmation(rp):
    """A validated antigen whose protein is NOT directly confirmed here (no CPTAC/IHC) is rescued by
    the precedent crosswalk to the MILDER tier — never the sharp RNA-only tier (unit-only; no live
    panel member reads this)."""
    hl = _hl(
        present="rna_only",
        pcs="untested",
        ihc="data_unavailable",
        scc="malignant_subset_detected",
        floor="adequate_abundance",
    )
    cav = rp._presence_confirmation_caveat(hl, target="MSLN")  # in the crosswalk
    assert cav["reason"] == "clinically_precedented_antigen_present"
    assert "precedent" in cav["detail"].lower()


# ── TIER 2 — sharp RNA/cell-line present but malignant protein unconfirmed (unit-only) ─────────
def test_rna_only_uncredentialed_target_sharp_caveat(rp):
    """The RNA-proxy inflation: RNA present, protein untested, NOT a precedented antigen, NOT stromal
    → the sharp `rna_or_cellline_present_protein_unconfirmed`. No live panel member reads this."""
    hl = _hl(
        present="rna_only",
        malignant="untested",
        pcs="untested",
        ihc="data_unavailable",
        scc="data_unavailable",
        floor="adequate_abundance",
    )
    cav = rp._presence_confirmation_caveat(hl, target="NOVELGENE1")
    assert cav["reason"] == "rna_or_cellline_present_protein_unconfirmed"
    assert cav["tier"] == "confirmation"
    assert "untested" in cav["detail"].lower()


def test_hard_abundance_floor_uncredentialed_is_sharp(rp):
    hl = _hl(
        present="rna_only",
        malignant="untested",
        pcs="untested",
        ihc="data_unavailable",
        scc="data_unavailable",
        floor="present_low_abundance",
    )  # HARD (quorum) floor
    cav = rp._presence_confirmation_caveat(hl, target="NOVELGENE2")
    assert cav["reason"] == "rna_or_cellline_present_protein_unconfirmed"
    assert "bottom-decile" in cav["detail"].lower()


def test_cell_line_overstates_tumor_is_sharp(rp):
    hl = _hl(
        present="rna_only",
        malignant="untested",
        pcs="untested",
        ihc="data_unavailable",
        scc="data_unavailable",
        cl_dir="cell_line_overstates_tumor",
    )
    cav = rp._presence_confirmation_caveat(hl, target="NOVELGENE3")
    assert cav["reason"] == "rna_or_cellline_present_protein_unconfirmed"
    assert "over-states" in cav["detail"].lower()


def test_cellline_protein_only_tumor_unconfirmed_is_sharp(rp):
    hl = _hl(
        present="protein_only",
        malignant="untested",
        pcs="confirmed_cell_line_only",
        ihc="data_unavailable",
        scc="data_unavailable",
    )
    cav = rp._presence_confirmation_caveat(hl, target="NOVELGENE4")
    assert cav["reason"] == "rna_or_cellline_present_protein_unconfirmed"
    assert "cell line" in cav["detail"].lower()


# ── None on non-positive / conflicted / untested reads ────────────────────────────────────────
@pytest.mark.parametrize("present", ["no", "untested", "rna_only_protein_absent", "protein_only_rna_absent"])
def test_none_on_nonpositive(rp, present):
    hl = _hl(present=present, malignant="no")
    assert rp._presence_confirmation_caveat(hl, target="MLANA") is None


def test_mlana_honest_negative_none(rp):
    hl = _hl(
        present="protein_only_rna_absent",
        malignant="no",
        pcs="confirmed_cell_line_only",
        scc="broadly_low",
        ihc="ihc_not_detected",
    )
    assert rp._presence_confirmation_caveat(hl, target="MLANA") is None


# ── presence_provenance ───────────────────────────────────────────────────────────────────────
def test_provenance_malignant_confirmed_true_for_epcam(rp):
    prov = rp._presence_provenance(
        _hl(pcs="confirmed", ihc="ihc_detected_high", scc="malignant_broadly_detected", malignant="yes")
    )
    assert prov["malignant_protein_confirmed"] is True
    assert "sc_rna/tumor(malignant)" in prov["corroborating_layers"]
    assert "bulk_protein_ms" in prov["corroborating_layers"]


def test_provenance_malignant_confirmed_false_for_stromal_protein(rp):
    """FAP: bulk protein confirmed but the malignant compartment is stromal → malignant_protein_confirmed
    must be FALSE (a bulk protein signal on a stromal antigen is NOT malignant-cell confirmation)."""
    prov = rp._presence_provenance(
        _hl(pcs="confirmed", ihc="ihc_detected_high", scc="microenvironment_dominant", malignant="stroma")
    )
    assert prov["malignant_protein_confirmed"] is False


def test_provenance_false_when_protein_untested(rp):
    prov = rp._presence_provenance(
        _hl(pcs="untested", ihc="data_unavailable", scc="malignant_broadly_detected", malignant="rna_only")
    )
    assert prov["malignant_protein_confirmed"] is False


# ── compartment_note ──────────────────────────────────────────────────────────────────────────
def test_compartment_note_reattributes_stroma(rp):
    note = rp._compartment_note(_hl(scc="microenvironment_dominant", mal_frac=0.0076))
    assert "re-attributes" in note.lower() and "microenvironment" in note.lower()


def test_compartment_note_confirms_malignant(rp):
    note = rp._compartment_note(_hl(scc="malignant_broadly_detected", mal_frac=0.89))
    assert "confirms malignant" in note.lower()


def test_compartment_note_ubiquitous(rp):
    note = rp._compartment_note(_hl(scc="malignant_broadly_detected", caf="shared_caf_malignant"))
    assert "ubiquitous" in note.lower()


def test_compartment_note_none_when_sc_unavailable(rp):
    assert rp._compartment_note(_hl(scc="data_unavailable")) is None
    assert rp._compartment_note(_hl(scc=None)) is None


# ── verdict-inertness: the functions read no presence_verdict ─────────────────────────────────
def test_functions_do_not_read_presence_verdict(rp):
    """A hl WITHOUT presence_verdict must still produce the caveat/provenance/note — proving they
    never key on the verdict spine (the byte-stability contract)."""
    hl = _hl(malignant="stroma", scc="microenvironment_dominant")
    assert "presence_verdict" not in hl
    assert rp._presence_confirmation_caveat(hl, target="FAP")["reason"] == "malignant_compartment_unconfirmed"
    assert rp._presence_provenance(hl)["malignant_protein_confirmed"] is False
    assert rp._compartment_note(hl) is not None
