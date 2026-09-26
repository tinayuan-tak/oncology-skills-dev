"""surface-modality-fit — orthogonality scorer (enrichment E7, 2026-08-07).

A verdict-INERT meta-facet: "how many INDEPENDENT lines of surface-biology evidence
converge for this target?" A target supported by five orthogonal axes is a
fundamentally stronger biologics call than one leaning entirely on a single axis —
even at the SAME fit_class verdict. This makes that convergence explicit.

WHY IT IS NOT A FIRED-RULE COUNT (the core design point): of the surface skill's cards,
only ~5 measure INDEPENDENT things. FIVE of them — CSPA surface confirmation, topology,
density, surfaceome-family, and RNA↔protein concordance — are all facets of ONE question:
"is the antigen actually present and bindable on the surface?" Counting fired rules would
score presence 5x and pMHC 1x, badly overweighting a single correlated cluster. This
scorer COLLAPSES each correlated cluster to ONE ternary line of evidence, then counts
distinct dimensions. (copy-number-amplification is composed by the skill as an additive
antigen-density facet but is NOT folded into D1 here — it is not read by _d1_presence;
adding it as a sixth presence-cluster member is a deliberate future extension.)

FIVE INDEPENDENT DIMENSIONS:
  D1 presence_accessibility  — is it there + bindable  (CSPA / topology / density / family / RNA-proxy)
  D2 selectivity_window      — tumor-vs-normal safety window  (normal-tissue-liability + therapeutic-window)
  D3 shed_liability          — circulating soluble decoy  (shed-ectodomain; INVERTED: not-shed = supportive)
  D4 effector_homogeneity    — within-tumor antigen homogeneity (TCE escape)  (single-cell)
  D5 pmhc_presentation       — peptide-centric HLA presentation  (pMHC, reaches intracellular)

HONESTY DOCTRINE (mirrors the framework's coverage-vs-support separation and the shed /
pMHC MS-asymmetry): each dimension resolves to supportive | opposing | abstain. `abstain`
= not measured / data_unavailable — a COVERAGE gap, NOT an opposing vote. The score
reports n_supportive, n_opposing, n_covered, n_total SEPARATELY so a target is never
penalized for a data gap the way it is for a genuine negative. orthogonality_class keys on
BREADTH OF SUPPORT (distinct supportive dimensions), gated by coverage.

VERDICT-INERT: this is computed from the SAME resolved cards `_headline` reads and emitted
as a headline sub-key `orthogonality`. The surface_modality resolver keys ONLY on
adc-tce-modality-fit.fit_class rungs (resolve_verdict_for_gate); the headline feeds no
rung, so this facet is structurally incapable of moving surface_modality_verdict. Pinned
by test_orthogonality_is_verdict_inert + the existing byte-stability sweep.
"""

from __future__ import annotations

from typing import Optional

# Each dimension: (dimension_id, [(card_id, field)], classifier). The classifier maps the
# collapsed set of that dimension's card values → 'supportive' | 'opposing' | 'abstain'.
# A dimension is `covered` iff it is not 'abstain'.

_ABSTAIN = {
    None,
    "data_unavailable",
    "unmeasured",
    "insufficient_paired_tumors",
    "not_on_secreted_panel",
    "not_observed",
    "not_expressed_in_cohort",
    "insufficient",
    "indeterminate",
}


def _get(cards, card_id, field):
    """Value of a card's summary field, or None. Matches _skills_common.get_card_field's
    access path (card['summary'][field]) but returns None for an ABSENT card_id rather
    than raising — a card may legitimately not have been composed, which is a coverage gap
    (abstain), not a caller typo in this display-facet context."""
    for c in cards or []:
        if c.get("card_id") == card_id:
            return (c.get("summary") or {}).get(field)
    return None


def _tern(supportive: bool, opposing: bool) -> str:
    if supportive and not opposing:
        return "supportive"
    if opposing and not supportive:
        return "opposing"
    if supportive and opposing:
        return "mixed"  # both a supportive and an opposing sub-signal → counts as covered, neither vote
    return "abstain"


# ---- per-dimension classifiers (keyed on REAL card vocabularies) ----


def _d1_presence(cards) -> dict:
    """Presence / surface accessibility — the CORRELATED cluster collapsed to one line.
    Supportive if ANY measured signal confirms surface residency + bindable ECD."""
    surf_conf = _get(cards, "protein-surface-evidence", "surface_confirmation_class")
    topo = _get(cards, "surface-topology-and-ptm", "topology_class")
    ecd = _get(cards, "surface-topology-and-ptm", "ecd_engineerability_class")
    dens = _get(cards, "surface-abundance-density", "surface_density_class")
    fam = _get(cards, "surfaceome-family-classification", "family_class")
    rna = _get(cards, "rna-protein-concordance-tumor", "rna_as_biomarker")
    supportive = any(
        [
            surf_conf in {"confirmed_high", "confirmed"},
            topo in {"single_pass_type_1", "single_pass_type_2", "single_pass_type_other", "gpi_anchored"},
            ecd in {"large_ecd", "moderate_ecd"},
            dens in {"high", "moderate"},
            (fam not in _ABSTAIN and fam not in {None, "not_surface"}),
            rna == "adequate_proxy",
        ]
    )
    opposing = any(
        [
            surf_conf == "not_surface",
            topo == "no_transmembrane",
            fam == "not_surface",
            ecd == "no_extracellular_domain",
        ]
    )
    members = {
        "surface_confirmation_class": surf_conf,
        "topology_class": topo,
        "ecd_engineerability_class": ecd,
        "surface_density_class": dens,
        "family_class": fam,
        "rna_as_biomarker": rna,
    }
    return {"call": _tern(supportive, opposing), "members": members}


def _d2_selectivity(cards) -> dict:
    """Selectivity / safety window — normal-tissue breadth + therapeutic window."""
    breadth = _get(cards, "normal-tissue-liability", "normal_tissue_breadth_class")
    essential = _get(cards, "normal-tissue-liability", "essential_tissue_flag")
    window = _get(cards, "modality-therapeutic-window", "window_class")
    supportive = any(
        [
            breadth in {"restricted_normal_expression", "not_detected_in_normal"},
            window == "clean_window",
        ]
    )
    opposing = any(
        [
            breadth == "broad_normal_expression",
            essential == "present",
            window in {"essential_tissue_liability", "narrow_window"},
        ]
    )
    return {
        "call": _tern(supportive, opposing),
        "members": {"normal_tissue_breadth_class": breadth, "essential_tissue_flag": essential, "window_class": window},
    }


def _d3_shed(cards) -> dict:
    """Shed-ectodomain liability — INVERTED: not-shed is the SUPPORTIVE (clean) call."""
    shed = _get(cards, "shed-ectodomain-liability", "shed_liability_class")
    measured = _get(cards, "shed-ectodomain-liability", "measured_shed_class")
    supportive = shed == "not_shed_membrane_retained"
    opposing = any(
        [
            shed in {"clinically_shed", "secretome_proxy_shed"},
            measured == "media_shed_high",
        ]
    )
    return {
        "call": _tern(supportive, opposing),
        "members": {"shed_liability_class": shed, "measured_shed_class": measured},
    }


def _d4_homogeneity(cards) -> dict:
    """Effector / within-tumor antigen conservation (TCE escape reservoir).

    #1738: repointed from the DEPRECATED lenient `tce_homogeneity_class` to `tce_antigen_escape_class`
    — the SAME field the verdict fires on — so this dimension agrees with the fired verdict. Polarity
    mirrors the verdict: escape_risk_low is supportive, escape_risk_high (escape reservoir) is
    opposing; the middle bands (moderate / patient_variable / underpowered) are neutral.
    """
    escape = _get(cards, "tumor-scrna-celltype-expression", "tce_antigen_escape_class")
    supportive = escape == "escape_risk_low"
    opposing = escape == "escape_risk_high"
    return {"call": _tern(supportive, opposing), "members": {"tce_antigen_escape_class": escape}}


def _d5_pmhc(cards) -> dict:
    """Peptide-centric HLA presentation (reaches intracellular via pMHC)."""
    pmhc = _get(cards, "pmhc-presentation", "pmhc_presentation_class")
    supportive = pmhc == "restricted_presentation"
    opposing = pmhc == "broadly_presented_normal"
    return {"call": _tern(supportive, opposing), "members": {"pmhc_presentation_class": pmhc}}


_DIMENSIONS = [
    ("presence_accessibility", _d1_presence),
    ("selectivity_window", _d2_selectivity),
    ("shed_liability", _d3_shed),
    ("effector_homogeneity", _d4_homogeneity),
    ("pmhc_presentation", _d5_pmhc),
]


def _classify(n_supportive: int, n_covered: int, n_total: int) -> str:
    """orthogonality_class keys on BREADTH OF SUPPORT, gated by coverage. `abstain` /
    `mixed` dimensions are covered but not supportive — they never count as support."""
    if n_covered == 0:
        return "insufficient_coverage"  # nothing measurable — honest, NOT a negative
    if n_supportive >= 4:
        return "broadly_corroborated"  # >=4 independent axes agree
    if n_supportive == 3:
        return "moderately_corroborated"
    if n_supportive == 2:
        return "narrowly_corroborated"
    if n_supportive == 1:
        return "single_axis"  # rests on ONE line of evidence
    return "uncorroborated"  # covered dims exist but none supportive


def score_orthogonality(cards: Optional[list]) -> dict:
    """Compute the verdict-inert surface orthogonality facet from the resolved cards.

    Returns a block with orthogonality_class + the coverage-vs-support counts (kept
    SEPARATE per the honesty doctrine) + a per-dimension breakdown. Emitted as a headline
    sub-key; never feeds the resolver."""
    per_dim = {}
    n_supportive = n_opposing = n_covered = 0
    for dim_id, fn in _DIMENSIONS:
        r = fn(cards)
        call = r["call"]
        per_dim[dim_id] = r
        if call != "abstain":
            n_covered += 1
        if call == "supportive":
            n_supportive += 1
        elif call == "opposing":
            n_opposing += 1
    n_total = len(_DIMENSIONS)
    return {
        "orthogonality_class": _classify(n_supportive, n_covered, n_total),
        "n_dimensions_supportive": n_supportive,
        "n_dimensions_opposing": n_opposing,
        "n_dimensions_covered": n_covered,
        "n_dimensions_total": n_total,
        "dimensions": {k: v["call"] for k, v in per_dim.items()},
        "dimension_evidence": {k: v["members"] for k, v in per_dim.items()},
        "_doctrine": (
            "VERDICT-INERT display facet: counts INDEPENDENT surface-biology "
            "dimensions with supporting evidence (the 6-card presence cluster is "
            "collapsed to ONE dimension). abstain=coverage gap, NOT an opposing "
            "vote. Never feeds the surface_modality resolver."
        ),
    }
