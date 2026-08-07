"""pmhc_presentation.classify — peptide-centric HLA-presentation classifier (pure, no S3).

The PEPTIDE-CENTRIC axis (biologics seed-note method A / signaling-node-skepticism angle A): an
intracellular oncoprotein is degraded and its peptides presented on HLA — a TCR-mimetic T-cell engager
targets the peptide-MHC COMPLEX on the surface, reaching "undruggable" intracellular targets
(KRAS-G12V / WT1 / PRAME / MAGE-A4 class). This is the axis surface-antigen presence cannot see.

Substrate: hla-ligand-atlas-presentation-per-protein-v1 — the BENIGN (normal-tissue) immunopeptidome
(HLA Ligand Atlas, PXD019643), per source protein: n_peptides, n_tissues (distinct NORMAL tissues
presenting its peptides), hla_class, strong/weak binder counts.

INTERPRETATION IS INVERTED from a surface-abundance signal. Because this is the NORMAL-tissue atlas,
broad presentation is a SAFETY LIABILITY, not an opportunity: a TCR-mimetic TCE hits every cell
presenting that peptide, so `n_tissues` high = broad on-target/off-tumor risk. Low n_tissues (e.g.
testis-restricted MAGE-A4, n_tissues=1) = the CLEAN peptide-centric target. This card is the
NORMAL-PRESENTATION SAFETY DENOMINATOR; the tumor-restriction call awaits a tumor immunopeptidome
(PCI-DB, Tier-2 acquisition).

MS ASYMMETRY (load-bearing): mass-spec immunopeptidomics tracks abundance×turnover — PRESENCE is
strong evidence, ABSENCE is WEAK. A protein absent from the atlas is `not_observed` (could still be
presented below MS detection), NEVER `not_presented`. A gene not in the atlas is a weak-negative /
tumor-restricted CANDIDATE, not a confirmed non-presenter.

Thresholds anchored to the atlas n_tissues distribution (15,262 proteins; quartiles [3, 8, 19, 25]).
"""
from __future__ import annotations

from typing import Optional

# n_tissues (distinct normal tissues presenting the protein's peptides) — atlas-anchored bands.
RESTRICTED_MAX_TISSUES = 3       # <= atlas Q1 → restricted normal presentation (TCE-favorable / clean)
BROAD_MIN_TISSUES = 19           # >= atlas Q3 → broadly presented on normal tissue (safety liability)


def classify_pmhc_presentation(n_peptides: Optional[int], n_tissues: Optional[int]) -> str:
    """pmhc_presentation_class from benign-atlas presentation breadth.

    restricted_presentation    — presented, but on <= Q1 normal tissues (clean peptide-centric target,
                                  MAGE-A4 archetype). The TCE-favorable class.
    intermediate_presentation  — normal-tissue breadth between Q1 and Q3.
    broadly_presented_normal   — presented on >= Q3 normal tissues — broad on-target/off-tumor SAFETY
                                  LIABILITY for a TCR-mimetic TCE (the peptide is on many normal cells).
    not_observed               — protein absent from the benign atlas. WEAK-negative (MS asymmetry:
                                  absence != not-presented) → a tumor-restricted CANDIDATE to confirm.
    data_unavailable           — atlas product unreadable.
    """
    if n_peptides is None or n_tissues is None:
        return "data_unavailable"
    if n_peptides <= 0:
        return "not_observed"
    if n_tissues <= RESTRICTED_MAX_TISSUES:
        return "restricted_presentation"
    if n_tissues >= BROAD_MIN_TISSUES:
        return "broadly_presented_normal"
    return "intermediate_presentation"


def summarize_pmhc(row: Optional[dict]) -> dict:
    """Build the card summary from an atlas row (or None = not in the atlas = weak-negative).

    `row`: dict with n_peptides, n_tissues, tissues, hla_class, n_strong/weak_binder_peptides — or None."""
    if row is None:
        # absent from the benign atlas — a WEAK negative (MS asymmetry), not data_unavailable.
        return {
            "pmhc_presentation_class": "not_observed",
            "n_presented_peptides": 0,
            "n_normal_tissues_presented": 0,
            "normal_tissues_presented": None,
            "hla_class": None,
            "n_strong_binder_peptides": 0,
            "n_weak_binder_peptides": 0,
            "_note": "not in the HLA Ligand Atlas benign immunopeptidome — a WEAK-negative "
                     "(MS tracks abundance×turnover; absence is not confirmed non-presentation) and "
                     "thus a tumor-restricted peptide-centric CANDIDATE to confirm on a tumor atlas.",
        }
    n_pep = _to_int(row.get("n_peptides"))
    n_tis = _to_int(row.get("n_tissues"))
    return {
        "pmhc_presentation_class": classify_pmhc_presentation(n_pep, n_tis),
        "n_presented_peptides": n_pep,
        "n_normal_tissues_presented": n_tis,
        "normal_tissues_presented": row.get("tissues"),
        "hla_class": row.get("hla_class"),
        "n_strong_binder_peptides": _to_int(row.get("n_strong_binder_peptides")),
        "n_weak_binder_peptides": _to_int(row.get("n_weak_binder_peptides")),
    }


def _to_int(v) -> Optional[int]:
    try:
        if v is None or v != v:
            return None
        return int(v)
    except (TypeError, ValueError):
        return None
