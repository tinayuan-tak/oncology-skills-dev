"""Differentiation QUESTION TABLE — the leading per-question (data · signal · confidence) hero for the
differentiation-landscape skill, computed deterministically from its already-emitted claim_vector
(COMUT / SURVIVAL / PROGNOSIS / NODE) + the clinical-precedent / competitor headline fields.

Sibling of dependency_question_table / genomic_question_table (same shape + shared vocab; no new scoring
model). Verdict-INERT: a one-way projection over decision['headline'] + card summaries — never a rule,
resolver, gate, or the differentiation_verdict.

Differentiation is a LANDSCAPE skill: its signals INFORM patient-selection / combination-biology /
competitive positioning — they are descriptive context, NOT a good/bad push on the nomination. So the
Signal polarity is `informs` (never supports/opposes), matching the skill's DESCRIPTIVE claim_vector.

  Q1 co-mutation / mutual-exclusivity?   primary claim COMUT     (patient-selection + combination biology)
  Q2 expression↔survival association?    primary claim SURVIVAL  support: PRECOG meta prognostic (PROGNOSIS)
  Q3 pathway-node leverage?              primary claim NODE      (dominant vs dominated network node)
  Q4 clinical / competitive precedent?   primary highest_clinical_stage + competitor_class (verdict-inert)
  Q5 mutational-process patient-selection? primary dominant_process (#1815 MMR/HRD/APOBEC/POLE; verdict-inert)

Signal reuses the claim_vector tier vocabulary (strong>moderate>weak>absent, unmeasured); Confidence
reuses the corroboration vocabulary (high>moderate>low, unmeasured).
"""

from __future__ import annotations

from typing import Optional

from _skills_common.question_table_core import conf as _conf
from _skills_common.question_table_core import row as _row

# Signal tier → (meter fill 0-5, polarity). Differentiation is DESCRIPTIVE: a present signal INFORMS
# patient-selection / positioning; it never "supports"/"opposes" the nomination.
_SIG_META = {
    "strong": (5, "informs"),
    "moderate": (3, "informs"),
    "weak": (2, "informs"),
    "absent": (1, "informs"),
    "unmeasured": (0, "none"),
}


def _sig(tier: str, label: str) -> dict:
    fill, pol = _SIG_META.get(tier, (0, "none"))
    return {"tier": tier, "fill": fill, "polarity": pol, "label": label}


def _axis_row(qid: str, question: str, cv: dict, key: str, support: str = "") -> dict:
    """One row driven by a claim_vector axis atom (signal × corroboration × evidence)."""
    atom = (cv or {}).get(key) or {}
    tier = atom.get("signal", "unmeasured")
    corr = atom.get("corroboration", "unmeasured")
    primary = atom.get("evidence") or "data_unavailable"
    return _row(qid, question, primary, support, _sig(tier, str(tier)), _conf(corr, f"corroboration: {corr}"))


# clinical stage → a coarse precedent Signal tier (descriptive; verdict-inert)
_STAGE_SIG = {"approved": "strong", "phase_3": "strong", "pivotal": "strong", "phase_2": "moderate", "phase_1": "weak"}


def differentiation_question_table(headline: dict, cards: Optional[list] = None) -> list:
    """Per-question rows for differentiation-landscape, from headline.claim_vector (COMUT/SURVIVAL/
    NODE) + the PRECOG/clinical/competitor fields. Verdict-inert; tolerant of an absent/partial
    claim_vector (an absent axis → an unmeasured row, never omitted, so the hero always shows the full
    ladder + names the gap)."""
    h = headline or {}
    cv = h.get("claim_vector") or {}
    prog = cv.get("PROGNOSIS") or {}
    rows = [
        _axis_row(
            "Q1",
            "Co-mutation / mutual-exclusivity landscape (patient-selection + combination biology)?",
            cv,
            "COMUT",
            f"co-occurrence: {h.get('cooccurrence_class') or '—'}",
        ),
        _axis_row(
            "Q2",
            "Expression↔survival association (prognostic / patient-stratification)?",
            cv,
            "SURVIVAL",
            f"PRECOG meta prognostic: {prog.get('signal', 'unmeasured')}",
        ),
        _axis_row(
            "Q3",
            "Pathway-node leverage — dominant vs dominated network node?",
            cv,
            "NODE",
            " · ".join(
                b
                for b in (
                    f"node leverage: {h.get('node_leverage_class') or '—'}",
                    # (#1816) genomic pathway-alteration FREQUENCY lens — is the target's pathway both
                    # frequently altered in-cohort AND the best node, or dominated? (verdict-inert)
                    f"pathway-alteration: {h.get('oncogenic_pathway_class')}"
                    if h.get("oncogenic_pathway_class")
                    else "",
                    f"target pathway alteration: {h.get('target_pathway_alteration')}"
                    if h.get("target_pathway_alteration")
                    else "",
                    # (#1820 F7) single-KO leverage understated by paralog buffering
                    "single-KO leverage understated" if h.get("node_single_ko_leverage_understated") else "",
                )
                if b
            ),
        ),
    ]
    # Q4 — clinical / competitive precedent (no claim_vector axis; verdict-inert descriptive context)
    stage = h.get("highest_clinical_stage")
    has_stage = bool(stage) and stage not in ("none", "data_unavailable")
    tier = _STAGE_SIG.get(str(stage), "weak" if has_stage else "unmeasured")
    support_bits = [
        b
        for b in (
            f"competitor: {h.get('competitor_class')}" if h.get("competitor_class") else "",
            f"{h.get('n_active_trials')} active trials" if h.get("n_active_trials") else "",
            "notable failures" if h.get("notable_failures") else "",
            # (#1820 F6) reported resistance mechanisms — the combination-biology-hypotheses bit
            "resistance mechanisms reported" if h.get("resistance_mechanisms_reported") else "",
            # (#1820 F7) withdrawn competitor agents — a failed-precedent signal
            "withdrawn agents" if h.get("competitor_withdrawn_agents") else "",
        )
        if b
    ]
    rows.append(
        _row(
            "Q4",
            "Clinical / competitive precedent?",
            str(stage or "—"),
            " · ".join(support_bits),
            _sig(tier, str(stage or "no precedent")),
            _conf("moderate" if has_stage else "unmeasured", "AACT + Open Targets (verdict-inert)"),
        )
    )
    # (#1815) Q5 — mutational-process patient-selection context (TCGA MC3): the canonical patient-selection
    # biomarker axis (MMR-deficiency→IO, HRD→PARP, APOBEC, POLE, TMB proxies). Verdict-inert descriptive
    # context; a present dominant process INFORMS patient selection. Absent → an unmeasured row (never omitted).
    dom = h.get("mutational_dominant_process")
    has_dom = bool(dom) and dom not in ("none", "data_unavailable")
    mut_support = [
        b
        for b in (
            f"MMR-deficiency: {h.get('mutational_mmr_deficiency_class')}"
            if h.get("mutational_mmr_deficiency_class")
            else "",
            f"HRD: {h.get('mutational_hrd_class')}" if h.get("mutational_hrd_class") else "",
            f"APOBEC: {h.get('mutational_apobec_class')}" if h.get("mutational_apobec_class") else "",
            f"POLE: {h.get('mutational_pole_class')}" if h.get("mutational_pole_class") else "",
            f"enriched: {h.get('mutational_enriched_processes')}" if h.get("mutational_enriched_processes") else "",
        )
        if b
    ]
    rows.append(
        _row(
            "Q5",
            "Mutational-process patient-selection context (MMR-deficiency / HRD / APOBEC / POLE / TMB proxies)?",
            f"dominant process: {dom or '—'}",
            " · ".join(mut_support),
            _sig("moderate" if has_dom else "unmeasured", str(dom or "no dominant process")),
            _conf("moderate" if has_dom else "unmeasured", "TCGA MC3 mutational signatures (verdict-inert)"),
        )
    )
    return rows


__all__ = ["differentiation_question_table"]
