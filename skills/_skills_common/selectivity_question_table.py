"""Selectivity QUESTION TABLE — the 8-question × (data · signal · confidence) summary that LEADS the
tumor-selectivity dashboard, computed deterministically from the already-emitted claim_vector +
answer-key headline fields. Verdict-INERT: a one-way projection over decision['headline'] + card
summaries; it never feeds a rule, resolver, gate, or the selectivity_class spine / normal-breadth veto.

The selectivity question (the north-star model): selectivity is a therapeutic-WINDOW claim — over-
expressed ENOUGH, ROBUSTLY, in the CANCER cells, with ROOM vs the worst normal. Unlike presence's
additive ladder, the meter is WIN-drives / SAFE-gates. The 4-claim claim_vector
(WIN window / DIST separation / INT malignant-intrinsic / SAFE normal-tissue window) drives four rows;
the other rows carry clear signals from the answer-key fields:

  Q1 over-expressed vs origin?   primary claim WIN     support: RNA→protein concordance
  Q2 comparator-robust?          primary comparators    support: sig-all-cells / discordant
  Q3 per-sample separation?      primary claim DIST     support: distribution overlap
  Q4 absolute vs all genes?      primary allgene rank    (level vs effect)
  Q5 window vs worst normal?     primary claim SAFE     support: therapeutic-window class + named organ
  Q6 malignant-intrinsic?        primary claim INT      support: bulk purity + spatial
  Q7 absolute surface density?   primary density floor   support: copies/cell + grade
  Q8 spatial bystander?          primary spatial coloc   support: normal-epithelium adjacency

Signal reuses the claim_vector tier vocabulary (strong>moderate>weak>absent/negative, unmeasured);
Confidence reuses the corroboration vocabulary (high>moderate>low, unmeasured). Reuses the SHARED
render_question_table_html so the gallery page + the composed target-profile dashboard render the
identical table. No new scoring model.
"""
from __future__ import annotations
from typing import Optional

# Signal tier → (meter fill 0-5, polarity). Polarity: supports / opposes / neutral / none.
_SIG_META = {
    "strong":     (5, "supports"),
    "moderate":   (3, "supports"),
    "weak":       (2, "supports"),
    "absent":     (1, "opposes"),     # measured floor
    "negative":   (1, "opposes"),     # measured against (e.g. critical-organ liability / stroma-driven)
    "unmeasured": (0, "none"),
}
_CONF_DOTS = {"high": 3, "moderate": 2, "low": 1, "unmeasured": 0}


def _cbyid(cards):
    return {c.get("card_id"): (c.get("summary") or {}) for c in (cards or [])}


def _sig(tier: str, label: str, polarity: Optional[str] = None) -> dict:
    fill, pol = _SIG_META.get(tier, (0, "none"))
    return {"tier": tier, "fill": fill, "polarity": polarity or pol, "label": label}


def _conf(tier: str, label: str = "") -> dict:
    return {"tier": tier, "dots": _CONF_DOTS.get(tier, 0), "label": label or tier}


def _row(qid, question, primary, support, signal, confidence):
    return {"id": qid, "question": question, "primary": primary, "support": support,
            "signal": signal, "confidence": confidence}


def _f(x, nd=2):
    return f"{x:.{nd}f}" if isinstance(x, (int, float)) else "n/a"


# ── per-question builders ─────────────────────────────────────────────────────────────────────────
def _q1_window(h, c, cv):
    w = cv.get("WIN", {})
    tier, corr = w.get("signal", "unmeasured"), w.get("corroboration", "unmeasured")
    primary = (f"axis-A {h.get('axis_a_selectivity_class', 'n/a')} · max|log2FC| "
               f"{_f(h.get('max_abs_log2fc'), 1)}")
    xconc = h.get("rna_protein_tvn_concordance")
    support = (f"RNA→protein: {xconc}" if xconc and xconc != "protein_unmeasured"
               else "protein layer unmeasured")
    return _row("Q1", "Over-expressed vs tissue-of-origin?", primary, support,
                _sig(tier, tier), _conf(corr, f"comparator support: {corr}"))


def _q2_comparators(h, c, cv):
    cs, cr = h.get("cells_supporting"), h.get("cells_ran")
    disc, sig_all = h.get("discordant"), h.get("sig_all_cells")
    if not cr:
        tier, pol = "unmeasured", "none"
    elif disc:
        tier, pol = "weak", "opposes"
    elif sig_all:
        tier, pol = "strong", "supports"
    elif (cs or 0) / cr >= 2 / 3:
        tier, pol = "moderate", "supports"
    else:
        tier, pol = "weak", "supports"
    primary = f"{int(cs or 0)}/{int(cr or 0)} independent comparators agree"
    support = ("comparators DISAGREE on direction" if disc
               else ("significant in ALL cells" if sig_all else "TCGA-adjacent (raw+ComBat) + GTEx"))
    return _row("Q2", "Robust across independent comparators?", primary, support,
                _sig(tier, tier, pol), _conf("high" if sig_all else "moderate"))


def _q3_separation(h, c, cv):
    d = cv.get("DIST", {})
    tier, corr = d.get("signal", "unmeasured"), d.get("corroboration", "unmeasured")
    primary = (f"{h.get('percentile_crossing_class', 'n/a')} · "
               f"{_f(h.get('fraction_tumor_above_normal_p95'), 2)} of tumors > normal p95")
    ov = h.get("distribution_overlap_tumor_normal")
    support = f"tumor/normal overlap {_f(ov, 2)}" if ov is not None else "per-sample overlap n/a"
    return _row("Q3", "Per-sample separation from normal?", primary, support,
                _sig(tier, tier), _conf(corr, f"separation: {corr}"))


_ALLGENE_TIER = {"top_1pct": "strong", "top_decile": "moderate", "mid": "weak",
                 "bottom_decile": "negative", "data_unavailable": "unmeasured"}


def _q4_absolute(h, c, cv):
    cls = h.get("selectivity_allgene_percentile_class") or "data_unavailable"
    tier = _ALLGENE_TIER.get(cls, "unmeasured")
    pct = h.get("selectivity_allgene_percentile")
    primary = (f"all-gene fold-change rank {_f(pct, 1)}th pct · {cls}"
               if pct is not None else f"all-gene rank {cls}")
    return _row("Q4", "Absolute — rank vs all genes (in-indication)?", primary,
                "the relative-selectivity frame (level vs effect)",
                _sig(tier, cls), _conf("moderate" if tier != "unmeasured" else "unmeasured"))


def _q5_normal_window(h, c, cv):
    s = cv.get("SAFE", {})
    tier, corr = s.get("signal", "unmeasured"), s.get("corroboration", "unmeasured")
    tw = h.get("therapeutic_window_class")
    scn = h.get("sc_normal_safety_essential_class")
    primary = f"therapeutic window {tw or 'n/a'} · sc-normal {scn or 'n/a'}"
    organ = h.get("sc_normal_max_detection_cell_type")
    support = (f"named-organ liability: {organ}" if scn == "critical_organ_liability" and organ
               else ("clean vs worst critical normal" if tier == "strong" else "normal-tissue window"))
    return _row("Q5", "Window vs the WORST critical normal? (the gate)", primary, support,
                _sig(tier, tier), _conf(corr, f"normal-side agreement: {corr}"))


def _q6_intrinsic(h, c, cv):
    i = cv.get("INT", {})
    tier, corr = i.get("signal", "unmeasured"), i.get("corroboration", "unmeasured")
    primary = (f"{h.get('sc_tumor_expression_class', 'n/a')} · malignant detection "
               f"{_f(h.get('sc_malignant_detection_fraction'), 2)}")
    caf, purity = h.get("sc_caf_vs_malignant_class"), h.get("purity_confound_class")
    support = f"CAF-vs-malignant {caf or 'n/a'} · bulk purity {purity or 'n/a'}"
    return _row("Q6", "Malignant-cell-intrinsic (not stroma)?", primary, support,
                _sig(tier, tier), _conf(corr, f"attribution: {corr}"))


_DENSITY_TIER = {"high": "strong", "moderate": "moderate", "low": "weak", "very_low": "weak",
                 "no_absolute_measurement": "unmeasured", "unmeasured": "unmeasured"}


def _q7_density(h, c, cv):
    cls = h.get("absolute_surface_density_class") or "unmeasured"
    tier = _DENSITY_TIER.get(cls, "unmeasured")
    floor = h.get("density_floor_verdict")
    cpc = h.get("absolute_copies_per_cell")
    primary = (f"{_f(cpc, 0)} copies/cell · {floor}" if cpc is not None
               else f"absolute density {cls}")
    grade = h.get("absolute_density_grade")
    support = (f"grade {grade}" if grade else "no calibrated Tier-1 anchor (abstain)")
    # below-floor is a MODALITY caveat, NOT a target killer (CD19) → keep polarity neutral, not opposes.
    pol = "neutral" if floor == "below_tce_floor" else None
    return _row("Q7", "Absolute surface density vs modality floors?", primary, support,
                _sig(tier, cls, pol), _conf("moderate" if tier != "unmeasured" else "unmeasured"))


_SPATIAL_RNA_TIER = {"tumour_enriched_rna": "moderate",
                     "tumour_present_no_compartment_preference": "weak",
                     "tme_enriched_rna": "negative", "data_unavailable": "unmeasured"}


def _q8_spatial(h, c, cv):
    rna_cls = h.get("spatial_rna_class") or "data_unavailable"
    tier = _SPATIAL_RNA_TIER.get(rna_cls, "unmeasured")
    coloc = h.get("spatial_coloc_class")
    adj = h.get("spatial_normal_epithelium_adjacency_fraction")
    primary = f"in-situ RNA {rna_cls}" + (f" · coloc {coloc}" if coloc else "")
    # normal-epithelium adjacency is a bystander/off-tumour caveat — surface it as the support line.
    support = (f"normal-epithelium adjacency {_f(adj, 2)} (bystander risk)"
               if adj is not None else "in-situ spatial (thin coverage; abstain where unavailable)")
    pol = "opposes" if coloc == "normal_epithelium_adjacent" else None
    return _row("Q8", "Spatial bystander risk to adjacent normal?", primary, support,
                _sig(tier, rna_cls, pol), _conf("low" if tier != "unmeasured" else "unmeasured"))


def selectivity_question_table(headline: dict, cards: list, claim_vector: Optional[dict] = None) -> list:
    """The 8 question rows (each: id, question, primary read, supporting/caveat line, signal,
    confidence). Verdict-inert. `claim_vector` defaults to the one on the headline
    (`headline['claim_vector']`)."""
    from _skills_common.selectivity_claims import selectivity_claim_vector
    cv = claim_vector or headline.get("claim_vector") or selectivity_claim_vector(headline, cards)
    c = _cbyid(cards)
    return [
        _q1_window(headline, c, cv),
        _q2_comparators(headline, c, cv),
        _q3_separation(headline, c, cv),
        _q4_absolute(headline, c, cv),
        _q5_normal_window(headline, c, cv),
        _q6_intrinsic(headline, c, cv),
        _q7_density(headline, c, cv),
        _q8_spatial(headline, c, cv),
    ]
