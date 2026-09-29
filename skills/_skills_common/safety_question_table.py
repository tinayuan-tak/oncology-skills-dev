"""On-target-safety QUESTION TABLE — the LEADING hero for the on-target-safety-liability skill.

Canonical question (target_profiling_axes.yaml → home_skill on-target-safety-liability): "Is the
target intolerant of loss-of-function in humans / does normal-tissue liability threaten on-target
safety?" decomposes into the 5-leg human-genetics axis:
  Constraint  — gnomAD LoF constraint (pLI / LOEUF)
  Burden      — population rare-variant gene-burden (Open Targets)
  Dosage      — ClinGen haploinsufficiency / dosage sensitivity
  Mouse-KO    — mouse knockout phenotype (lethality)
  ClinVar     — germline pathogenicity

POLARITY (inverted vs the other heroes): a liability OPPOSES a safe target, so rows are framed as
"is this leg TOLERANT (safe)?" — Signal strong = LoF-tolerant / safe; absent = a liability (concern).
This keeps the shared "Signal — supports [good outcome]" meter semantics (green = safe) consistent
with presence/tractability. Verdict-INERT: a one-way projection over decision['headline']; reuses the
shared Signal/Confidence vocab + renderer. NB: for an activating (mutant-selective GoF) driver the
WT-constraint concern is MODALITY-CONDITIONAL — that conditioning was retired from the scalar
safety_verdict (safety.resolver 2.0.0) and now lives in the per-modality safety verdict
(safety_verdict_by_modality); the scalar safety_verdict is the honest raw concern.
"""

from __future__ import annotations

from typing import Optional

from _skills_common.question_table_core import conf as _conf
from _skills_common.question_table_core import row as _row
from _skills_common.question_table_core import sig as _sig  # shared Signal/Confidence vocab

# value → tier, where strong = LoF-TOLERANT (safe) and absent = a safety LIABILITY (concern).
_CONSTRAINT = {
    "tolerant": "strong",
    "moderately_constrained": "weak",
    "highly_constrained": "absent",
    "indeterminate": "unmeasured",
}
_BURDEN = {
    "no_burden_signal": "strong",
    "protective": "strong",
    "direction_unresolved": "weak",
    "lof_risk_phenotype": "absent",
    "insufficient": "unmeasured",
}
_DOSAGE = {
    "dosage_sufficient": "strong",
    "no_clingen_entry": "unmeasured",
    "unresolved": "weak",
    "autosomal_dominant_loss": "absent",
    "insufficient": "unmeasured",
}
_MOUSE = {
    "no_phenotype": "strong",
    "mild_phenotype": "moderate",
    "developmental_only": "weak",
    "severe_organ_phenotype": "absent",
    "lethal_ko": "absent",
    "insufficient": "unmeasured",
}
_CLINVAR = {
    "no_pathogenic_signal": "strong",
    "no_clinvar_entry": "unmeasured",
    "somatic_only": "moderate",
    "germline_pathogenic_low_review": "weak",
    "germline_pathogenic": "absent",
    "insufficient": "unmeasured",
}

# NORMAL-TISSUE liability leg (SK#1582 G3.2). SAFE-valence, INVERTED from the claim vector's
# liability-valence: essential-tissue protein EXPRESSION is an on-target-off-tumour liability (a concern →
# `absent`), a MEASURED clean read is safe (`strong`), and broad normal expression is a measured moderate
# liability (`weak`). `unknown`/missing → an unmeasured named gap (breadth fallback first, mirroring
# safety_claims._normaltissue_sig).
_NORMAL_TISSUE = {
    "present": "absent",  # essential-tissue protein expressed → off-tumour liability (concern)
    "absent": "strong",  # MEASURED: no essential-tissue expression → safe
}
_NORMAL_TISSUE_BREADTH = {"broad_normal_expression": "weak"}  # measured moderate off-tumour liability

# PAN-ESSENTIAL broad-tox leg. SAFE-valence, INVERTED from the claim vector's liability-valence
# (safety_claims._PANESS_SIGNAL): a broadly/commonly-essential gene is a broad-tox on-target liability
# (concern → `absent`); a selective/non-dependent read means a therapeutic window exists (safe → `strong`);
# underpowered/unavailable → an unmeasured named gap.
_PAN_ESSENTIAL = {
    "common_essential": "absent",  # broad-tox liability (concern)
    # #1794: anchor-UNREACHABLE well-powered >=85% call — the resolver HOLDs it with the same token as
    # the curated arm (an UNVERIFIABLE pan-essential must never read safe), so the safe-valence row
    # mirrors common_essential exactly. NOT the underpowered "weak": the fraction here IS trusted.
    "common_essential_unanchored": "absent",
    "broadly_dependent": "weak",  # dependent in many (not pan) lineages → partial-breadth liability
    "common_essential_underpowered": "weak",
    "strongly_selective": "strong",  # MEASURED: selective → a window exists (safe)
    "non_dependent": "strong",  # MEASURED: not dependent → safe
    "non_dependent_underpowered": "unmeasured",
    "data_unavailable": "unmeasured",
}

# (row id, sub-question [framed as tolerant/safe], headline field, value→tier map, claim_vector axis)
_ROWS = [
    ("Constraint", "LoF-tolerant in gnomAD (not constrained)?", "constraint_class", _CONSTRAINT, "CONSTRAINT"),
    ("Burden", "No population LoF rare-variant burden?", "burden_safety_class", _BURDEN, "BURDEN"),
    ("Dosage", "Dosage-tolerant (not ClinGen haploinsufficient)?", "dosage_sensitivity_class", _DOSAGE, "DOSAGE"),
    ("Mouse-KO", "Mouse knockout viable (not lethal)?", "mouse_ko_phenotype_class", _MOUSE, "MOUSE_KO"),
    ("ClinVar", "No germline pathogenic variants?", "clinvar_pathogenic_class", _CLINVAR, "CLINVAR"),
    (
        "Pan-essential",
        "Not broadly essential (a dependency window exists)?",
        "dependency_class",
        _PAN_ESSENTIAL,
        "PAN_ESSENTIAL",
    ),
]


def _tier(mapping: dict, val) -> str:
    if val in (None, "", "indeterminate", "insufficient"):
        return "unmeasured"
    return mapping.get(str(val), "unmeasured")


def _leg_conf(h: dict, axis: str, tier: str) -> dict:
    """#1792: the per-leg confidence cell, graded from the claim vector's OWN corroboration for that leg
    (high / moderate / single_arm / low — the same vocab CONF_DOTS renders) instead of the former flat
    `moderate` on every measured leg (which rendered a single-armed gnomAD read with the same dots as a
    cross-source-corroborated one). CONSERVATIVE fall-through: a measured leg whose claim atom is absent
    (or carries no corroboration) degrades to `unmeasured` (0 dots) — absence never reassures."""
    if tier == "unmeasured":
        return _conf("unmeasured")
    corr = ((h.get("claim_vector") or {}).get(axis) or {}).get("corroboration") or "unmeasured"
    return _conf(corr, f"corroboration: {corr}")


def _normal_tissue_leg(h: dict) -> "tuple[str, str]":
    """Resolve the normal-tissue leg's (safe-valence tier, primary label) from the headline: the HPA-IHC
    essential-tissue flag first, else a measured normal-tissue breadth fallback (mirrors
    safety_claims._normaltissue_sig, INVERTED to safe-valence). `unknown`/missing → an unmeasured gap.

    ★ #1793: a measured TPHP HPA-BLIND vital-organ liability (tphp_hpa_blind_vital_organ_liability_class
    == vital_organ_abundant) is the SAME essential-organ concern carried by the one protein panel that
    covers the organs HPA cannot see, and it drives a resolver HOLD — so it overrides every
    non-concerning HPA read (incl. the `absent` measured-clear, which is scope-limited to HPA's closed
    16-name vocabulary) down to `absent` (concern). An HPA `present` read keeps its own label/tier
    (already the concern). Only the liability class overrides: low/no-signal/data_unavailable NEVER
    reassure this leg (absence claims stay owned by the HPA flag). None-stable on pre-0.5.0 packages."""
    flag = h.get("essential_tissue_flag")
    if h.get("tphp_hpa_blind_vital_organ_liability_class") == "vital_organ_abundant" and flag != "present":
        return "absent", "vital_organ_abundant (HPA-blind organs)"
    if flag not in (None, "", "unknown", "indeterminate"):
        return _NORMAL_TISSUE.get(str(flag), "weak"), str(flag)
    breadth = h.get("normal_tissue_breadth_class")
    tier = _NORMAL_TISSUE_BREADTH.get(str(breadth)) if breadth not in (None, "") else None
    if tier is not None:
        return tier, str(breadth)
    return "unmeasured", "—"


def _normal_liability_concordance_integrated_signal(claim: dict) -> dict:
    """Project the L2b-3 `normal_liability_concordance` claim (safety_claims.py) into the Normal-tissue
    row's `integrated_signal` surface — a verdict-INERT, class-dependent presentation payload. UNLIKE
    G3.1's always-positive coverage helper, safety valence is class-dependent (the encouraging direction
    is a CLEAN concordance; every other class is a qualifying caveat), so the headline leads with whichever
    of positive/qualifying is populated. Carries NO signal tier / polarity / fill — it never routes the
    verdict; it is the answer's cross-source annotation, not a meter cell."""
    pos = claim.get("positive_signal")
    qual = claim.get("qualifying_signal")
    boundary = bool(claim.get("boundary_sensitive"))
    lead = (pos or qual or {}).get("statement", "")
    headline = lead
    if boundary and lead:
        headline += f" [boundary-sensitive: {claim.get('boundary_note', '')}]"
    return {
        "kind": "normal_liability_concordance",
        "concordance_class": claim.get("concordance_class"),
        "corroboration": claim.get("corroboration"),
        "boundary_sensitive": boundary,
        "boundary_note": claim.get("boundary_note"),
        "positive_signal": pos,
        "qualifying_signal": qual,
        "source_support": claim.get("source_support"),
        "headline": headline,
        "provenance_ref": "claim_vector.normal_liability_concordance",
    }


def safety_question_table(headline: dict, cards: Optional[list] = None) -> list:
    """Per-safety-leg rows from the on-target-safety-liability headline. Verdict-inert; an absent field →
    an unmeasured row (never omitted), so the hero always shows the full axis + which leg is a named gap.
    strong = LoF-tolerant (safe); absent = a safety liability.

    #1574: the hero now covers all 7 verdict-driving legs (HeadlineSpec.axis_keys) — a Pan-essential row
    (`dependency_class`, broad-tox liability, safe-valence inverted from safety_claims._PANESS_SIGNAL) and
    the Normal-tissue row below, so a verdict resolving on either omitted leg is no longer shown fully SAFE.

    SK#1582 G3.2: a Normal-tissue row presents the HPA-IHC essential-tissue leg and — when the L2b-3
    `normal_liability_concordance` claim resolves on `headline['claim_vector']` — SURFACES it as a
    first-class cross-source `integrated_signal` annotation (emitted by SK#1546, read by nothing until
    now). Verdict-inert: the row's signal/confidence meter cells carry no tier from the claim; the
    annotation routes nothing (key omitted when the claim is absent → row byte-stable).

    SK#1792: per-leg confidence is GRADED from the claim vector's corroboration for that leg (see
    `_leg_conf`) — no longer a flat `moderate` on every measured leg."""
    h = headline or {}
    rows = []
    for qid, question, field, mapping, axis in _ROWS:
        val = h.get(field)
        tier = _tier(mapping, val)
        rows.append(
            _row(
                qid,
                question,
                str(val if val not in (None, "") else "—"),
                "",
                _sig(tier, "not measured" if tier == "unmeasured" else str(val)),
                _leg_conf(h, axis, tier),
            )
        )
    # 6th leg: normal-tissue liability. Always emitted (full-axis contract); the integrated_signal
    # annotation attaches only when the cross-source claim resolves.
    nt_tier, nt_label = _normal_tissue_leg(h)
    nt_row = _row(
        "Normal-tissue",
        "Restricted normal-tissue footprint (no essential-tissue liability)?",
        nt_label,
        "",
        _sig(nt_tier, "not measured" if nt_tier == "unmeasured" else nt_label),
        _leg_conf(h, "NORMAL_TISSUE", nt_tier),
    )
    claim = (h.get("claim_vector") or {}).get("normal_liability_concordance")
    if claim:
        nt_row["integrated_signal"] = _normal_liability_concordance_integrated_signal(claim)
    rows.append(nt_row)
    return rows


__all__ = ["safety_question_table"]
