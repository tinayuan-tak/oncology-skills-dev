"""iedb_epitope.classify — per-protein IEDB epitope-evidence classifier (pure, no S3).

The EXPERIMENTALLY-VALIDATED pMHC axis. IEDB (iedb-epitope-mhc-per-protein-v1) rolls the human
source-protein MINORITY of IEDB up to per-UniProt: has the target's peptides been experimentally
observed PRESENTED on human HLA (MHC-ligand elution/binding) and/or RECOGNIZED by T cells, on which
HLA class / how many alleles, in a cancer context. This is pMHC GROUND TRUTH — what has been OBSERVED —
COMPLEMENTING hla-ligand-atlas-presentation-per-protein-v1 (the benign normal-tissue immunopeptidome
breadth). For a TCR-mimetic T-cell engager reaching an intracellular oncoprotein via the peptide-MHC
complex (KRAS-G12V / WT1 / PRAME / MAGE-A4 class), experimentally-validated epitopes + T-cell
recognition are the strongest confirmation the peptide is a real pMHC target.

ASSAY ASYMMETRY (load-bearing, mirrors the immunopeptidomics MS asymmetry): a POSITIVE assay is strong
evidence; ABSENCE is WEAK. A protein absent from IEDB (or with no positive-assay epitope) is
`not_observed` / `no_positive_epitopes` — a candidate NOT yet experimentally characterised, NEVER a
confirmed non-epitope. Presentation/recognition also != expression: this is experimental epitope
evidence, distinct from mRNA/protein abundance and from PREDICTED binding.

VERDICT-INERT: this classifier feeds a DISPLAY card only. It maps no rule and moves no verdict — the
surface_modality fit_class resolves off adc-tce-modality-fit; this card adds narrative pMHC context.
"""

from __future__ import annotations

from typing import Optional


def classify_epitope_evidence(
    n_epitopes: Optional[int],
    has_tcell_positive: Optional[bool],
    has_mhc_ligand_positive: Optional[bool],
) -> str:
    """epitope_evidence_class from the per-protein IEDB rollup.

    tcell_validated                 — >=1 positive epitope AND a positive T-cell assay: the peptide is
                                      experimentally RECOGNIZED by T cells (strongest pMHC ground truth,
                                      the ERBB2 / NY-ESO-1 / MAGE-A3 archetype).
    presented_not_tcell_confirmed   — >=1 positive epitope with MHC-ligand presentation observed but no
                                      recorded positive T-cell assay (presented, recognition uncharacterised).
    no_positive_epitopes            — the protein is in IEDB but has no positive-assay epitope — a WEAK
                                      negative (assay asymmetry), not a confirmed non-epitope.
    not_observed                    — protein absent from IEDB entirely. WEAK negative; a peptide-centric
                                      CANDIDATE not yet experimentally characterised.  (emitted by summarize)
    data_unavailable                — target not resolvable to a UniProt AC / product unreadable.  (by reader)
    """
    if n_epitopes is None:
        return "data_unavailable"
    if n_epitopes <= 0:
        return "no_positive_epitopes"
    if bool(has_tcell_positive):
        return "tcell_validated"
    return "presented_not_tcell_confirmed"


def summarize_epitope(row: Optional[dict]) -> dict:
    """Build the card summary from a per-protein IEDB row (or None = absent from IEDB = weak-negative).

    `row`: dict with n_epitopes, n_mhc_class_i_epitopes, n_mhc_class_ii_epitopes, n_hla_alleles,
    has_tcell_positive, has_mhc_ligand_positive, has_cancer_context, example_hla_alleles — or None."""
    if row is None:
        # absent from IEDB — a WEAK negative (assay asymmetry), NOT data_unavailable.
        return {
            "epitope_evidence_class": "not_observed",
            "n_epitopes": 0,
            "n_mhc_class_i_epitopes": 0,
            "n_mhc_class_ii_epitopes": 0,
            "n_hla_alleles": 0,
            "has_tcell_positive": False,
            "has_cancer_context": False,
            "example_hla_alleles": None,
            "_note": "no human source-protein epitope in IEDB (iedb-epitope-mhc-per-protein-v1) — a "
            "WEAK-negative (a positive assay is strong evidence; absence is not confirmed "
            "non-epitope) and thus a peptide-centric CANDIDATE not yet experimentally characterised.",
        }
    n_epi = _to_int(row.get("n_epitopes"))
    return {
        "epitope_evidence_class": classify_epitope_evidence(
            n_epi, row.get("has_tcell_positive"), row.get("has_mhc_ligand_positive")
        ),
        "n_epitopes": n_epi,
        "n_mhc_class_i_epitopes": _to_int(row.get("n_mhc_class_i_epitopes")),
        "n_mhc_class_ii_epitopes": _to_int(row.get("n_mhc_class_ii_epitopes")),
        "n_hla_alleles": _to_int(row.get("n_hla_alleles")),
        "has_tcell_positive": _to_bool(row.get("has_tcell_positive")),
        "has_cancer_context": _to_bool(row.get("has_cancer_context")),
        "example_hla_alleles": row.get("example_hla_alleles"),
    }


def _to_int(v) -> Optional[int]:
    try:
        if v is None or v != v:
            return None
        return int(v)
    except (TypeError, ValueError):
        return None


def _to_bool(v) -> Optional[bool]:
    if v is None:
        return None
    try:
        if v != v:  # NaN
            return None
    except (TypeError, ValueError):
        pass
    return bool(v)
