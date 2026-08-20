"""selectivity_claims — tumor-selectivity's CLAIM VECTOR + KEY SIGNALS: a verdict-INERT projection of
the selectivity cards into (signal × corroboration) per orthogonal claim.

The THIRD concrete instance of the shared claim_vector_core contract (presence + dependency are the
first two). Declares tumor-selectivity's four axes as a ClaimSpec list:

  WIN  tumor-vs-normal window   — the core selectivity signal (tumor-vs-origin DESeq2 class + effect
                                  size); corroboration = fraction of normal comparators agreeing.
  DIST distributional separation — per-sample tumor-vs-normal percentile crossing; corroboration =
                                  tumor/normal distribution overlap (low overlap = clean separation).
  INT  tumor-cell-intrinsic     — is the selective signal malignant-cell-intrinsic or stroma/purity-
                                  confounded? (single-cell malignant detection + CAF/purity); a
                                  microenvironment-driven signal is a FALSE window (→ `negative`).
  SAFE normal-tissue window     — the therapeutic-window liability / veto instrument: a clean normal
                                  side supports selectivity (strong), a critical-organ normal expression
                                  refutes it (`negative`, the veto). SAFETY VERDICT is owned by
                                  on-target-safety-liability; this is window FRAMING, not a safety call.

FIT: unlike presence's entangled A/B/C/D, selectivity's claims are cleanly SEPARABLE (signal from a
class field, corroboration from a distinct provenance number), so they map onto the core's
signal_fn / corroboration_fn ClaimSpec contract directly.

Verdict-INERT: reads the ALREADY-computed _headline; never feeds the selectivity resolver or the
normal-breadth veto. The CEACAM5/TACSTD2 offline replay guard freezes selectivity_class byte-stable.
All inputs are read from `headline` (populated by run.py::_headline via card_summary/get_card_field);
the `cards` param is accepted for contract-uniformity but unused here.
"""
from __future__ import annotations

from _skills_common.claim_vector_core import (ClaimSpec, build_claim_vector, build_key_signals,
                                              cap_corroboration, sig_ge)

# ── enum → tier maps (grounded in the target-contracts card summary_fields_vocabulary) ────────────
# tumor-vs-normal-selectivity.selectivity_class (raw pre-veto tumor-vs-origin class)
_WIN_SIGNAL = {
    "strong_tumor_selective": "strong",
    "modest_tumor_selective": "moderate",
    "field_effect_tumor_selective": "weak",       # selective vs DISTANT normal, not adjacent → weak window
    "selective_but_broadly_normal": "weak",        # selective signal but broad normal → window liability
    "discordant_across_comparators": "weak",
    "not_selective": "absent",                     # a MEASURED negative
    "not_informative": "unmeasured",
    "data_unavailable": "unmeasured",
}
# tumor-vs-normal-percentile-crossing.selectivity_class
_DIST_SIGNAL = {
    "strongly_tumor_enriched": "strong",
    "enriched_subset": "moderate",
    "minimally_enriched": "weak",
    "not_enriched": "absent",
    "data_unavailable": "unmeasured",
}
# tumor-scrna-celltype-expression.sc_expression_class (tumor side)
_INT_SIGNAL = {
    "malignant_broadly_detected": "strong",
    "malignant_subset_detected": "moderate",
    "microenvironment_dominant": "negative",       # signal is stroma-driven → a FALSE selectivity window
    "broadly_low": "absent",
    "data_unavailable": "unmeasured",
}
# sc-normal-celltype-expression.sc_normal_safety_essential_class — INVERSE-liability: a clean normal
# side is a STRONG selectivity-window signal; a critical-organ liability is a NEGATIVE (the veto).
_SAFE_SIGNAL = {
    "none": "strong",
    "origin_tissue_liability": "weak",
    "critical_organ_liability": "negative",
    "data_unavailable": "unmeasured",
}

_INFORMS = {
    "WIN": "tumor-vs-normal window — the core selectivity signal (therapeutic index)",
    "DIST": "distributional separation — per-sample, patient-level selectivity",
    "INT": "tumor-cell-intrinsic — informs tumor-cell-targeted modalities (ADC/TCE/CAR); a stroma-driven signal is a false window",
    "SAFE": "normal-tissue window — the therapeutic-window liability (veto instrument); the safety VERDICT is owned by on-target-safety-liability",
}


def _f(v, nd=2):
    return f"{v:.{nd}f}" if isinstance(v, (int, float)) else "n/a"


# ── the four claims (signal_fn -> (tier, evidence, conflict); corroboration_fn -> tier) ───────────
def _win_signal(h, c):
    cls = h.get("axis_a_selectivity_class")
    sig = _WIN_SIGNAL.get(cls, "unmeasured")
    conflict = None
    if h.get("discordant") or cls == "discordant_across_comparators":
        conflict = "normal comparators DISAGREE on the tumor-vs-normal direction"
    elif cls == "selective_but_broadly_normal":
        conflict = "selective vs origin but broadly expressed in normal — therapeutic-window liability"
    ev = (f"tumor-vs-normal: {cls or 'data_unavailable'}, max|log2FC|={_f(h.get('max_abs_log2fc'), 1)}, "
          f"{h.get('cells_supporting')}/{h.get('cells_ran')} comparators")
    return sig, ev, conflict


def _win_corroboration(h, c):
    cs, cr = h.get("cells_supporting"), h.get("cells_ran")
    if not isinstance(cr, (int, float)) or not cr:
        return "unmeasured"
    frac = (cs or 0) / cr
    base = "high" if frac >= 0.8 and cr >= 3 else "moderate" if frac >= 0.5 else "low"
    if h.get("discordant"):
        base = cap_corroboration(base, "low")   # disagreeing comparators cap corroboration
    return base


def _dist_signal(h, c):
    cls = h.get("percentile_crossing_class")
    fa = h.get("fraction_tumor_above_normal_p95")
    ev = (f"per-sample crossing: {cls or 'data_unavailable'}"
          + (f", {_f((fa or 0) * 100, 0)}% of tumours > normal p95" if isinstance(fa, (int, float)) else ""))
    return _DIST_SIGNAL.get(cls, "unmeasured"), ev, None


def _dist_corroboration(h, c):
    if _DIST_SIGNAL.get(h.get("percentile_crossing_class"), "unmeasured") == "unmeasured":
        return "unmeasured"
    ov = h.get("distribution_overlap_tumor_normal")
    if not isinstance(ov, (int, float)):
        return "moderate"
    return "high" if ov <= 0.3 else "moderate" if ov <= 0.6 else "low"   # low overlap = clean separation


def _int_signal(h, c):
    cls = h.get("sc_tumor_expression_class")
    sig = _INT_SIGNAL.get(cls, "unmeasured")
    purity = h.get("purity_confound_class")
    conflict = None
    if purity == "microenvironment_confounded":
        conflict = "bulk selectivity may be microenvironment-confounded (purity) — the signal is not clearly tumor-cell-intrinsic"
        if sig_ge(sig, "moderate"):
            sig = "weak"   # purity contradicts an apparent intrinsic single-cell signal → downgrade
    ev = (f"single-cell: {cls or 'data_unavailable'}, malignant frac {_f(h.get('sc_malignant_detection_fraction'))}, "
          f"CAF={h.get('sc_caf_vs_malignant_class')}, purity={purity}")
    return sig, ev, conflict


def _int_corroboration(h, c):
    if _INT_SIGNAL.get(h.get("sc_tumor_expression_class"), "unmeasured") == "unmeasured":
        return "unmeasured"
    caf, purity = h.get("sc_caf_vs_malignant_class"), h.get("purity_confound_class")
    if caf == "caf_dominant" or purity == "microenvironment_confounded":
        return "low"     # a disagreeing arm (stroma-dominant / purity-confounded) caps corroboration
    agree = caf in ("malignant_dominant", "caf_low") and purity in ("tumor_intrinsic", "purity_independent")
    return "high" if agree else "moderate"


def _safe_signal(h, c):
    cls = h.get("sc_normal_safety_essential_class")
    sig = _SAFE_SIGNAL.get(cls, "unmeasured")
    conflict = ("critical-organ normal expression — therapeutic-window veto (safety verdict owned by "
                "on-target-safety-liability)" if cls == "critical_organ_liability" else None)
    ev = (f"normal-tissue: {cls or 'data_unavailable'}, sc_normal={h.get('sc_normal_expression_class')}, "
          f"{h.get('sc_normal_n_cell_types_above_20pct')} normal cell-types >20%")
    return sig, ev, conflict


def _safe_corroboration(h, c):
    ess = h.get("sc_normal_safety_essential_class")
    if _SAFE_SIGNAL.get(ess, "unmeasured") == "unmeasured":
        return "unmeasured"
    # the two independent normal-side reads (essential-cell class + expression-liability class) agree?
    liab = ess in ("critical_organ_liability", "origin_tissue_liability")
    expr_liab = h.get("sc_normal_expression_class") in ("HIGH_LIABILITY", "MODERATE_LIABILITY")
    return "high" if liab == expr_liab else "moderate"


# ── citable evidence atoms (claim_vector_core atom_fn) ──────────────────────────────────────────────
# Bind each selectivity axis's load-bearing VALUES to its source {card_id, fields} + entity, so the
# cross-evidence reasoner can cite the number (effect size + comparator support, distributional
# separation + overlap, malignant fraction, normal-tissue breadth) rather than the bare class label.
# Read from the SOURCE card summaries (cards_by_id) for correct per-card citation; verdict-inert;
# returns None when the source card is absent (axis stays byte-stable — no evidence_atom key).
def _satom(card_id: str, summary: dict, keys: tuple, entity: dict, read) -> dict | None:
    vals = {k: summary[k] for k in keys if summary.get(k) is not None}
    if not vals:
        return None
    return {"read": read, "values": vals,
            "cite": {"card_id": card_id, "fields": sorted(vals)}, "entity": entity}


def _win_atom(h, c):
    cid = "tumor-vs-normal-selectivity"
    return _satom(cid, c.get(cid) or {},
                  ("selectivity_class", "max_abs_log2fc", "cells_supporting", "cells_ran",
                   "comparator_concordance", "dominant_direction"),
                  {"measurement_type": "tumor_vs_normal_selectivity", "sample_context": "tumor"},
                  (c.get(cid) or {}).get("selectivity_class"))


def _dist_atom(h, c):
    cid = "tumor-vs-normal-percentile-crossing"
    return _satom(cid, c.get(cid) or {},
                  ("selectivity_class", "fraction_tumor_above_normal_p95",
                   "distribution_overlap_tumor_normal", "n_tumor_samples", "n_normal_samples"),
                  {"measurement_type": "tumor_vs_normal_percentile_crossing", "sample_context": "tumor"},
                  (c.get(cid) or {}).get("selectivity_class"))


def _int_atom(h, c):
    cid = "tumor-scrna-celltype-expression"
    return _satom(cid, c.get(cid) or {},
                  ("sc_expression_class", "malignant_detection_fraction", "caf_vs_malignant_class",
                   "top_microenvironment_compartment", "malignant_n_donors"),
                  {"measurement_type": "sc_tumor_celltype_expression", "sample_context": "tumor",
                   "grain": "single_cell"},
                  (c.get(cid) or {}).get("sc_expression_class"))


def _safe_atom(h, c):
    cid = "sc-normal-celltype-expression"
    return _satom(cid, c.get(cid) or {},
                  ("sc_normal_safety_essential_class", "sc_normal_expression_class",
                   "n_cell_types_above_20pct", "max_detection_fraction"),
                  {"measurement_type": "sc_normal_celltype_expression", "sample_context": "normal",
                   "grain": "single_cell"},
                  (c.get(cid) or {}).get("sc_normal_safety_essential_class"))


SELECTIVITY_CLAIM_SPEC = [
    ClaimSpec("WIN", "tumor-vs-normal window", _win_signal, _win_corroboration, _INFORMS["WIN"], _win_atom),
    ClaimSpec("DIST", "distributional separation", _dist_signal, _dist_corroboration, _INFORMS["DIST"], _dist_atom),
    ClaimSpec("INT", "tumor-cell-intrinsic", _int_signal, _int_corroboration, _INFORMS["INT"], _int_atom),
    ClaimSpec("SAFE", "normal-tissue window", _safe_signal, _safe_corroboration, _INFORMS["SAFE"], _safe_atom),
]

_DISCLAIMER = (
    "Verdict-INERT projection of the selectivity cards into orthogonal claims (WIN tumor-vs-normal "
    "window / DIST distributional separation / INT tumor-cell-intrinsic / SAFE normal-tissue window), "
    "each signal×corroboration. Claims are NOT additive; a weak WIN does not degrade a strong INT. "
    "SAFE is therapeutic-window FRAMING — the safety verdict is owned by on-target-safety-liability. "
    "corroboration is a within-claim support tier, NOT the axis certainty. Never feeds the "
    "selectivity_class or the normal-breadth veto.")


def selectivity_claim_vector(headline: dict, cards: list) -> dict:
    """The verdict-inert claim vector {WIN,DIST,INT,SAFE: {signal, corroboration, evidence, conflict,
    informs}, _disclaimer}. Projection over the computed headline."""
    return build_claim_vector(SELECTIVITY_CLAIM_SPEC, headline, cards, _DISCLAIMER)


def selectivity_key_signals(headline: dict, cards: list) -> dict:
    """A brief, direct, CITED read (deterministic; available without the LLM)."""
    vec = selectivity_claim_vector(headline, cards)
    h = headline

    def sup_win(claim):
        return (f"Tumor-selective vs normal — {h.get('axis_a_selectivity_class')} "
                f"(max|log2FC| {_f(h.get('max_abs_log2fc'), 1)}, {h.get('cells_supporting')}/{h.get('cells_ran')} comparators) "
                f"[tumor-vs-normal-selectivity]")

    def sup_dist(claim):
        return (f"Distributionally separated — {_f((h.get('fraction_tumor_above_normal_p95') or 0) * 100, 0)}% of tumours "
                f"> normal p95 (overlap {_f(h.get('distribution_overlap_tumor_normal'))}) [percentile-crossing]")

    def sup_int(claim):
        return (f"Tumor-cell-intrinsic — {_f((h.get('sc_malignant_detection_fraction') or 0) * 100, 0)}% of malignant cells, "
                f"{h.get('sc_caf_vs_malignant_class')} (purity {h.get('purity_confound_class')}) [single-cell + purity]")

    def cav_win(claim):
        return (f"Weak tumor-vs-adjacent window — {h.get('axis_a_selectivity_class')} "
                f"({h.get('cells_supporting')}/{h.get('cells_ran')} comparators agree) [tumor-vs-normal-selectivity]")

    def cav_dist(claim):
        return f"Poor distributional separation — {h.get('percentile_crossing_class')} [percentile-crossing]"

    def cav_int(claim):
        if h.get("purity_confound_class") == "microenvironment_confounded":
            return "Selectivity may be microenvironment-driven, not tumor-cell-intrinsic [single-cell + purity]"
        return f"Weak tumor-cell-intrinsic signal — {h.get('sc_tumor_expression_class')} [single-cell]"

    def cav_safe(claim):
        return (f"Normal-tissue expression → therapeutic-window liability — {h.get('sc_normal_safety_essential_class')} "
                f"(sc_normal {h.get('sc_normal_expression_class')}) [sc-normal comparators]")

    def head(v, supports):
        win, dist, intr, safe = (v["WIN"]["signal"], v["DIST"]["signal"],
                                 v["INT"]["signal"], v["SAFE"]["signal"])
        if safe == "negative":
            base = "Selective signal, but a critical-organ normal-tissue liability."
        elif sig_ge(win, "strong") or (sig_ge(dist, "strong") and sig_ge(intr, "moderate")):
            base = "Tumor-selective."
        elif sig_ge(win, "moderate") or sig_ge(dist, "moderate"):
            base = "Tumor-selective, with caveats."
        elif win == "absent" and dist == "absent":
            base = "Not tumor-selective."
        else:
            base = "Selectivity largely unmeasured or not distinguishing."
        if intr == "negative":
            base = base.rstrip(".") + " — but the signal may be microenvironment-driven."
        return base

    return build_key_signals(
        vec,
        # SAFE is a LIABILITY axis, not a positive support — a clean normal side is the absence of a
        # liability, not headline-worthy selectivity evidence. So it drives CAVEATS (critical_keys)
        # but is excluded from the positive SUPPORTS (rank_keys). WIN/DIST/INT carry the positive case.
        rank_keys=("WIN", "DIST", "INT"),
        support_fns={"WIN": sup_win, "DIST": sup_dist, "INT": sup_int},
        # SAFE first so a normal-tissue window liability wins ties as the surfaced caveat (the
        # decision-critical caveat for a selectivity call is the therapeutic-window threat).
        critical_keys=("SAFE", "WIN", "INT", "DIST"),
        caveat_fns={"WIN": cav_win, "DIST": cav_dist, "INT": cav_int, "SAFE": cav_safe},
        headline_fn=head,
    )


__all__ = ["selectivity_claim_vector", "selectivity_key_signals", "SELECTIVITY_CLAIM_SPEC"]
