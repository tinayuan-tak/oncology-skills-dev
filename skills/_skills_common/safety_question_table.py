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

# (row id, sub-question [framed as tolerant/safe], headline field, value→tier map)
_ROWS = [
    ("Constraint", "LoF-tolerant in gnomAD (not constrained)?", "constraint_class", _CONSTRAINT),
    ("Burden", "No population LoF rare-variant burden?", "burden_safety_class", _BURDEN),
    ("Dosage", "Dosage-tolerant (not ClinGen haploinsufficient)?", "dosage_sensitivity_class", _DOSAGE),
    ("Mouse-KO", "Mouse knockout viable (not lethal)?", "mouse_ko_phenotype_class", _MOUSE),
    ("ClinVar", "No germline pathogenic variants?", "clinvar_pathogenic_class", _CLINVAR),
]


def _tier(mapping: dict, val) -> str:
    if val in (None, "", "indeterminate", "insufficient"):
        return "unmeasured"
    return mapping.get(str(val), "weak")


def safety_question_table(headline: dict, cards: Optional[list] = None) -> list:
    """Per-human-genetics-leg rows from the on-target-safety-liability headline. Verdict-inert; an
    absent field → an unmeasured row (never omitted), so the hero always shows the full 5-leg axis +
    which leg is a named gap. strong = LoF-tolerant (safe); absent = a safety liability."""
    h = headline or {}
    rows = []
    for qid, question, field, mapping in _ROWS:
        val = h.get(field)
        tier = _tier(mapping, val)
        rows.append(
            _row(
                qid,
                question,
                str(val if val not in (None, "") else "—"),
                "",
                _sig(tier, "not measured" if tier == "unmeasured" else str(val)),
                _conf("unmeasured" if tier == "unmeasured" else "moderate"),
            )
        )
    return rows


__all__ = ["safety_question_table"]
