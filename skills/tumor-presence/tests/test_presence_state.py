"""Pin the typed presence_state projection + its named protein<->RNA conflicts.

presence_state is a VERDICT-INERT re-projection of the claim_vector A/B/C/D + the protein/abundance/sc
facets. These cases are the ones that motivated it: an ALB-style single-contrast false-positive, a
PECAM1-style stromal signal the one word buries, and the ERBB2/EPCAM true positives (broadly-elevated
vs de-differentiating low-abundance). See skills/tumor-presence/CONTRACT.md and presence_claims.py.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from _skills_common.presence_claims import derive_presence_state, render_presence_label


def _hl(A=None, B=None, C=None, pcs=None, floor=None, scc=None, breadth=None):
    """Minimal synthetic headline: just the fields derive_presence_state reads."""
    return {
        "presence_verdict": "SENTINEL_MUST_BE_IGNORED",  # guard: the projection must NOT read this
        "claim_vector": {"A": {"signal": A}, "B": {"signal": B}, "C": {"signal": C}},
        "protein_confirmation_state": pcs,
        "abundance_floor_flag": floor,
        "sc_expression_class": scc,
        "tumor_elevation_breadth_class": breadth,
    }


def test_erbb2_like_broadly_elevated_confirmed():
    st = derive_presence_state(
        _hl(
            A="strong",
            B="strong",
            C="strong",
            pcs="confirmed",
            floor="adequate_abundance",
            scc="malignant_broadly_detected",
            breadth="multi_tumor_elevated",
        )
    )
    assert st == {
        "present": "yes",
        "conflict": False,
        "abundance_level": "high",
        "elevated_vs_normal": "yes",
        "malignant_intrinsic": "yes",
        "breadth": "multi",
        "_basis": st["_basis"],
    }
    assert render_presence_label(st) == "present_broadly_tumor_elevated_protein_confirmed"


def test_epcam_like_dedifferentiating_low_abundance_not_elevated():
    st = derive_presence_state(
        _hl(
            A="strong",
            B="absent",
            C="strong",
            pcs="confirmed",
            floor="present_low_abundance",
            scc="malignant_broadly_detected",
            breadth="multi_tumor_elevated",
        )
    )
    assert st["present"] == "yes"
    assert st["abundance_level"] == "low"  # abundance-floor caught the bottom-decile level
    assert st["elevated_vs_normal"] == "no"  # flat vs adjacent (EPCAM in colon epithelium)
    assert st["malignant_intrinsic"] == "yes"
    assert render_presence_label(st) == "present_sparsely_protein_confirmed"


def test_pecam1_like_stromal_signal_is_named():
    """CD31/PECAM1: present in the tumor section but ENDOTHELIAL, not malignant. The one word says
    tumor_broadly_expressed; the typed state must surface malignant_intrinsic=stroma."""
    st = derive_presence_state(
        _hl(
            A="weak",
            B="absent",
            C="negative",
            pcs="confirmed",
            floor="present_low_abundance",
            scc="microenvironment_dominant",
            breadth="single_tumor_elevated",
        )
    )
    assert st["present"] == "yes"
    assert st["malignant_intrinsic"] == "stroma"
    assert st["conflict"] is False


def test_alb_like_conflict_is_named_not_collapsed():
    """ALB: a single tumor-vs-adjacent contrast mints strongly_upregulated_in_tumor, but abundance +
    single-cell say not-present. Protein is measured-present (bulk lysate/IHC = serum contamination).
    The typed state must NAME the conflict, not read it as absent OR as a clean present."""
    st = derive_presence_state(
        _hl(
            A="absent",
            B="weak",
            C="absent",
            pcs="confirmed",
            floor=None,
            scc="broadly_low",
            breadth="single_tumor_elevated",
        )
    )
    assert st["present"] == "protein_only_rna_absent"
    assert st["conflict"] is True
    assert st["malignant_intrinsic"] == "no"
    assert render_presence_label(st) == "conflicted_protein_present_rna_absent"


def test_mirror_conflict_rna_present_protein_absent():
    st = derive_presence_state(_hl(A="strong", B="strong", C="strong", pcs="measured_absent"))
    assert st["present"] == "rna_only_protein_absent"
    assert st["conflict"] is True
    assert render_presence_label(st) == "present_rna_only_protein_absent"


def test_rna_only_when_protein_untested():
    st = derive_presence_state(_hl(A="moderate", B="unmeasured", C="unmeasured", pcs="untested"))
    assert st["present"] == "rna_only"
    assert st["conflict"] is False


def test_measured_absent_is_no():
    st = derive_presence_state(_hl(A="absent", B="absent", C="absent", pcs="untested", scc="broadly_low"))
    assert st["present"] == "no"
    assert render_presence_label(st) == "absent"


def test_unmeasured_is_untested():
    st = derive_presence_state(_hl(A=None, B=None, C=None, pcs="not_applicable"))
    assert st["present"] == "untested"
    assert render_presence_label(st) == "presence_untested"


def test_projection_is_verdict_inert_ignores_presence_verdict():
    """The sentinel presence_verdict must never influence the projection: two headlines with identical
    claim_vector/facets but different presence_verdict produce identical presence_state."""
    kw = dict(
        A="strong",
        B="strong",
        C="strong",
        pcs="confirmed",
        scc="malignant_broadly_detected",
        breadth="multi_tumor_elevated",
    )
    a = _hl(**kw)
    b = _hl(**kw)
    b["presence_verdict"] = "something_totally_different"
    assert derive_presence_state(a) == derive_presence_state(b)


# ── obs-3: a THIN cell-line-only protein leg must not mint a protein_only_rna_absent conflict ─────
def test_thin_contradicted_cellline_only_protein_does_not_mint_rna_absent_conflict():
    """MLANA case: RNA absent, protein 'confirmed' only by a bottom-decile Gygi cell-line read that is
    ORTHOGONALLY CONTRADICTED (abundance floor low AND HPA-IHC ihc_not_detected). Too thin to mint a
    protein_only_rna_absent CONFLICT → present='no'."""
    hl = _hl(A="absent", pcs="confirmed_cell_line_only", floor="present_low_abundance")
    hl["hpa_ihc_protein_presence_class"] = "ihc_not_detected"
    st = derive_presence_state(hl)
    assert st["present"] == "no" and st["conflict"] is False


def test_uncontradicted_cellline_only_still_mints_conflict():
    """Guard the demotion is NARROW: an RNA-absent target whose cell-line-only protein is NOT contradicted
    (IHC detected, or floor not low) still mints the protein_only_rna_absent conflict — and a full/tumor
    `confirmed` always does."""
    # IHC detected → not contradicted
    hl = _hl(A="absent", pcs="confirmed_cell_line_only", floor="present_low_abundance")
    hl["hpa_ihc_protein_presence_class"] = "ihc_detected_high"
    assert derive_presence_state(hl)["present"] == "protein_only_rna_absent"
    # floor not low → not contradicted
    hl2 = _hl(A="absent", pcs="confirmed_cell_line_only", floor="adequate_abundance")
    hl2["hpa_ihc_protein_presence_class"] = "ihc_not_detected"
    assert derive_presence_state(hl2)["present"] == "protein_only_rna_absent"
    # full (tumor) confirmation → always mints
    assert derive_presence_state(_hl(A="absent", pcs="confirmed"))["present"] == "protein_only_rna_absent"
