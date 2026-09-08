"""Dependency QUESTION TABLE — the 7-question × (data · signal · confidence) summary that LEADS the
functional-requirement dashboard, computed deterministically from the already-emitted claim_vector
(DEP/SEL/COND/CHEM) + the answer-key card fields. Verdict-INERT: a one-way projection over
decision['headline'] + card summaries; it never feeds a rule, resolver, gate, or the dependency_verdict.

Sibling of presence_question_table (same shape + vocabulary; no new scoring model). The dependency
question (target-evaluation model): is loss of the target lethal, is that lethality SELECTIVE (a
therapeutic window, and to THIS indication's lineage), do orthogonal assays agree, is a negative rescued
by a conditional/paralog buffer, is it drug-confirmable, and how corroborated is the call. Each row is a
PRIMARY read (drives the Signal) plus a SUPPORTING/caveat sub-line from the remaining cards:

  Q1 lethal at all?          primary claim DEP        support: RNAi + CRISPR↔RNAi concordance
  Q2 selective vs pan-ess?   primary control-benchmark (INVERTED: near pan-essential = tox, not a win)
  Q3 selective to lineage?   primary indication-lineage reduction (by_scope) / claim SEL
  Q4 CRISPR↔RNAi agree?      primary concordance      support: fraction agree
  Q5 conditional / SL?       primary claim COND       support: paralog buffer
  Q6 chemically confirmable? primary claim CHEM       support: n PRISM compounds
  Q7 corroborated?           primary cross-consortium + omics-predictability (the confidence axis)

Signal reuses the claim_vector tier vocabulary (strong>moderate>weak>absent/negative, unmeasured);
Confidence reuses the corroboration vocabulary (high>moderate>low, unmeasured).
"""

from __future__ import annotations

from typing import Optional

from _skills_common.question_table_core import cbyid as _cbyid
from _skills_common.question_table_core import conf as _conf
from _skills_common.question_table_core import row as _row

# Signal tier → (meter fill 0-5, polarity toward a SELECTIVE, actionable dependency).
_SIG_META = {
    "strong": (5, "supports"),
    "moderate": (3, "supports"),
    "weak": (2, "supports"),
    "absent": (1, "opposes"),  # measured floor (not a dependency)
    "negative": (1, "opposes"),  # measured against (e.g. off-target compound kill)
    "unmeasured": (0, "none"),
}


def _sig(tier: str, label: str, polarity: Optional[str] = None, fill: Optional[int] = None) -> dict:
    f, pol = _SIG_META.get(tier, (0, "none"))
    return {"tier": tier, "fill": fill if fill is not None else f, "polarity": polarity or pol, "label": label}


# ── per-question builders ────────────────────────────────────────────────────────────────────────
def _q1_lethal(h, c, cv):
    dep = cv.get("DEP", {})
    tier, corr = dep.get("signal", "unmeasured"), dep.get("corroboration", "unmeasured")
    primary = dep.get("evidence") or f"CRISPR {h.get('crispr_call', 'data_unavailable')}"
    rnai, conc = h.get("rnai_call"), h.get("concordance_call")
    bits = []
    if rnai:
        bits.append(f"RNAi {rnai}")
    if conc:
        bits.append(f"concordance {conc}")
    support = " · ".join(bits) if bits else "single CRISPR arm"
    label = tier + (" ⚠ RNAi disagrees" if dep.get("conflict") and "RNAi" in str(dep.get("conflict")) else "")
    return _row(
        "Q1",
        "Is loss-of-function lethal at all?",
        primary,
        support,
        _sig(tier, label),
        _conf(corr, f"CRISPR×RNAi + cross-consortium: {corr}"),
    )


# control-benchmark class → (fill, polarity, label). INVERTED semantics: near the pan-essential
# ceiling is a broad-toxicity liability (opposes a therapeutic window), NOT a win; the window is
# `between_controls`. Non-dependence (near the non-essential floor) also opposes.
_CONTROL_SIG = {
    "between_controls": (5, "supports", "selective window"),
    "selective_dependency": (5, "supports", "selective window"),
    "as_essential_as_pan_essential": (2, "opposes", "⚠ pan-essential (tox liability)"),
    "near_pan_essential": (2, "opposes", "⚠ near pan-essential (tox)"),
    "near_non_essential": (1, "opposes", "not dependent"),
    "data_unavailable": (0, "none", "unmeasured"),
}


def _q2_window(h, c, cv):
    crispr = c.get("pan-cancer-crispr-dependency-distribution", {})
    pos = crispr.get("dep_control_position_class") or "data_unavailable"
    fill, pol, label = _CONTROL_SIG.get(pos, (0, "none", pos))
    tier = "strong" if fill >= 5 else ("weak" if fill == 2 else ("absent" if fill == 1 else "unmeasured"))
    sel_idx = crispr.get("selectivity_index")
    primary = f"control position: {pos}"
    if isinstance(sel_idx, (int, float)):
        primary += f" · selectivity index {sel_idx:.2f}"
    ctx = crispr.get("dep_control_position_context")
    support = str(ctx) if ctx else "pan-essential ceiling ↔ non-essential floor"
    n = crispr.get("n_cell_lines_evaluated")
    conf = "high" if isinstance(n, (int, float)) and n >= 500 else "moderate" if n else "unmeasured"
    return _row(
        "Q2",
        "Selective, or pan-essential? (therapeutic window)",
        primary,
        support,
        _sig(tier, label, polarity=pol, fill=fill),
        _conf(conf),
    )


def _q3_lineage(h, c, cv):
    sel = cv.get("SEL", {})
    tier = sel.get("signal", "unmeasured")
    # Prefer the deterministic indication-lineage reduction (dependency_verdict_by_scope, Phase 3) when
    # present — it answers "selective to THIS indication's lineage?" rather than "to SOME lineage".
    by_scope = h.get("dependency_verdict_by_scope") or {}
    ind = by_scope.get("indication") if isinstance(by_scope, dict) else None
    if isinstance(ind, dict) and ind.get("class") not in (None, "data_unavailable", "not_scoped_this_run"):
        cls, lin = ind.get("class"), ind.get("depmap_lineage")
        primary = f"{lin or 'lineage'}: {cls}"
        if isinstance(ind.get("q_value"), (int, float)):
            primary += f" (q={ind['q_value']:.1e})"
        _map = {
            "selective_in_indication": "strong",
            "dependent_not_enriched": "moderate",
            "not_dependent_in_indication": "absent",
            "underpowered": "unmeasured",
            "not_in_panel": "unmeasured",
        }
        tier = _map.get(cls, tier)
        if ind.get("shared_lineage_caveat"):
            primary += " ⚠ coarse-lineage (shared)"
    else:
        primary = sel.get("evidence") or f"lineage enrichment: {h.get('lineage_selectivity', 'data_unavailable')}"
    nlin = h.get("n_lineages_evaluated")
    support = f"{nlin} lineages evaluated (target-grain enrichment)" if nlin else "target-grain lineage scan"
    conf = "high" if isinstance(nlin, (int, float)) and nlin >= 20 else "moderate" if nlin else "unmeasured"
    return _row("Q3", "Selective to this indication's lineage?", primary, support, _sig(tier, tier), _conf(conf))


_CONC_TIER = {
    "strongly_concordant_dependent": "strong",
    "moderately_concordant_dependent": "moderate",
    "strongly_concordant_non_dependent": "absent",
    "moderately_concordant_non_dependent": "absent",
    "discordant": "negative",
    "partially_assayed": "unmeasured",
    "data_unavailable": "unmeasured",
}


def _q4_concordance(h, c, cv):
    conc = c.get("crispr-rnai-dependency-concordance", {})
    cls = conc.get("concordance_class") or h.get("concordance_call") or "data_unavailable"
    tier = _CONC_TIER.get(cls, "unmeasured")
    fa, nb = conc.get("fraction_agree"), conc.get("n_in_both")
    primary = f"{cls}" + (f" ({fa:.0%} agree)" if isinstance(fa, (int, float)) else "")
    support = f"{nb} lines in both assays" if nb else "single-assay coverage"
    conf = "high" if isinstance(nb, (int, float)) and nb >= 300 else "moderate" if nb else "unmeasured"
    return _row("Q4", "Do CRISPR and RNAi agree?", primary, support, _sig(tier, tier), _conf(conf))


def _q5_conditional(h, c, cv):
    cond = cv.get("COND", {})
    tier = cond.get("signal", "unmeasured")
    primary = cond.get("evidence") or f"partner-conditional: {h.get('partner_conditional_class', 'data_unavailable')}"
    par = h.get("paralog_buffering_class")
    parsym = h.get("strongest_paralog_symbol")
    support = (
        (f"paralog buffer: {par}" + (f" (strongest {parsym})" if parsym else "")) if par else "no paralog buffer read"
    )
    corr = cond.get("corroboration", "unmeasured")
    return _row("Q5", "Conditional / synthetic-lethal rescue?", primary, support, _sig(tier, tier), _conf(corr))


def _q6_chemical(h, c, cv):
    chem = cv.get("CHEM", {})
    tier = chem.get("signal", "unmeasured")
    primary = chem.get("evidence") or f"PRISM×CRISPR: {h.get('prism_concordance_class', 'data_unavailable')}"
    ncomp = h.get("n_compounds_evaluated")
    support = f"{ncomp} PRISM compounds" if ncomp else "no PRISM coverage"
    label = tier + (" ⚠ off-target" if chem.get("conflict") else "")
    corr = chem.get("corroboration", "unmeasured")
    return _row("Q6", "Is the dependency chemically confirmable?", primary, support, _sig(tier, label), _conf(corr))


_XCONS_TIER = {
    "concordant_dependent": "strong",
    "concordant_non_dependent": "absent",
    "single_consortium_only": "weak",
    "discordant": "negative",
    "data_unavailable": "unmeasured",
}


def _q7_corroborated(h, c, cv):
    xc = h.get("cross_consortium_class") or "data_unavailable"
    tier = _XCONS_TIER.get(xc, "unmeasured")
    pred = h.get("predictability_class")
    primary = f"cross-consortium (Broad↔Sanger): {xc}"
    support_bits = []
    if pred:
        support_bits.append(f"omics-predictability: {pred}")
    if h.get("pred_dominant_feature_class"):
        support_bits.append(f"dominant feature: {h.get('pred_dominant_feature_class')}")
    # co-essential-module coherence (a 3rd corroboration signal; wired into dependency_confidence_note)
    cem = h.get("coessential_module_class")
    if cem and cem != "data_unavailable":
        cem_bit = f"co-essential module: {cem}"
        if h.get("strongest_coessential_partner"):
            cem_bit += f" (top {h.get('strongest_coessential_partner')})"
        support_bits.append(cem_bit)
    support = " · ".join(support_bits) if support_bits else "no predictability read"
    # confidence here is the dependency_confidence annotation FR already computes
    conf = h.get("dependency_confidence") or "unmeasured"
    return _row(
        "Q7",
        "How corroborated / predictable is the call?",
        primary,
        support,
        _sig(tier, tier),
        _conf(conf, f"dependency confidence: {conf}"),
    )


def dependency_question_table(headline: dict, cards: list, claim_vector: Optional[dict] = None) -> list:
    """The 7 question rows (each: id, question, primary read, supporting/caveat line, signal, confidence).
    Verdict-inert. `claim_vector` defaults to the one on the headline (`headline['claim_vector']`)."""
    from _skills_common.dependency_claims import dependency_claim_vector

    cv = claim_vector or headline.get("claim_vector") or dependency_claim_vector(headline, cards)
    c = _cbyid(cards)
    return [
        _q1_lethal(headline, c, cv),
        _q2_window(headline, c, cv),
        _q3_lineage(headline, c, cv),
        _q4_concordance(headline, c, cv),
        _q5_conditional(headline, c, cv),
        _q6_chemical(headline, c, cv),
        _q7_corroborated(headline, c, cv),
    ]


__all__ = ["dependency_question_table"]
