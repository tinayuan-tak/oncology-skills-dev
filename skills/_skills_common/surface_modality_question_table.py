"""Surface-modality QUESTION TABLE — the LEADING hero for the surface-modality-fit skill (the
biologics analog of presence_question_table / genomic_question_table).

The skill's canonical question (target_profiling_axes.yaml → home_skill surface-modality-fit): "Does
surface biology support a biologics modality (ADC / TCE / antibody)?" decomposes into the surface
sub-questions that gate a biologics program:
  Surface  — is it a cell-surface protein at all (membrane topology)?
  Density  — is the absolute surface density above the ADC/TCE abundance floor?
  ADC      — is the ectodomain membrane-retained (not shed) → ADC-favorable?
  TCE      — is expression homogeneous across tumor cells → TCE-favorable?
Signal maps each surface card's OWN class field via its EXPLICIT vocabulary (polarity differs per
field — e.g. shed `not_shed`=good but density `low`=bad — so no generic keyword mapper). Verdict-INERT:
a one-way projection over decision['headline']; reuses the shared Signal/Confidence vocab + renderer.
"""

from __future__ import annotations

from typing import Optional

from _skills_common.evidence_frame import DENSITY_GAP_TOKENS
from _skills_common.evidence_frame import adc_modality_fit_frame as _adc_modality_fit_frame
from _skills_common.evidence_frame import forward_question_from_frame as _forward_question_from_frame
from _skills_common.evidence_frame import tce_modality_fit_frame as _tce_modality_fit_frame
from _skills_common.question_table_core import conf as _conf
from _skills_common.question_table_core import row as _row
from _skills_common.question_table_core import sig as _sig  # shared Signal/Confidence vocab

# Explicit per-field value → Signal tier maps (from each card's summary_fields_vocabulary).
_TOPOLOGY = {
    "single_pass_type_1": "strong",
    "single_pass_type_2": "moderate",
    "single_pass_type_other": "moderate",
    "multi_pass": "moderate",
    "gpi_anchored": "moderate",
    "beta_barrel": "moderate",
    "no_transmembrane": "absent",
    "data_unavailable": "unmeasured",
}
# A no-absolute-measurement state (#994) is a COVERAGE GAP, not a weak positive: without it, the
# whole-cell-estimate / no-measurement tokens fall through `_tier`'s "weak" default and render as a
# weak *supports* signal. Map them to `unmeasured` (grey) so a gap reads as a gap.
_DENSITY = {
    "high": "strong",
    "moderate": "moderate",
    "low": "weak",
    "very_low": "absent",
    "unmeasured": "unmeasured",
    "not_surface_density_whole_cell_estimate": "unmeasured",
    "no_absolute_measurement": "unmeasured",
}
_SHED = {
    "not_shed_membrane_retained": "strong",
    "secretome_proxy_shed": "weak",
    "clinically_shed": "absent",
    "indeterminate": "unmeasured",
}
# TCE antigen-escape read (#1738): repointed from the DEPRECATED lenient `tce_homogeneity_class`
# (detection-fraction-only, 0.5 homogeneous bar) to the superior `tce_antigen_escape_class` (2-axis
# coverage x inter-donor consistency) — the SAME field the verdict fires on (run.py resolver prio
# 11-14). Tiers mirror the verdict polarity: escape_risk_low = TCE-favorable (supportive rung),
# escape_risk_high = escape reservoir (efficacy foreclosure), the middle bands temper without
# foreclosing, coverage_high_donor_underpowered = honest gap.
_ESCAPE = {
    "escape_risk_low": "strong",
    "escape_risk_moderate": "moderate",
    "escape_risk_patient_variable": "weak",
    "escape_risk_high": "absent",
    "coverage_high_donor_underpowered": "unmeasured",
    "data_unavailable": "unmeasured",
}

# (row id, sub-question, headline field, value→tier map)
_ROWS = [
    ("Surface", "Is it a cell-surface protein (membrane topology)?", "topology_class", _TOPOLOGY),
    ("Density", "Absolute surface density — above the ADC/TCE abundance floor?", "surface_density_class", _DENSITY),
    ("ADC", "ADC-favorable — ectodomain membrane-retained (not shed)?", "shed_liability_class", _SHED),
    (
        "TCE",
        "TCE-favorable — antigen conserved across tumor cells (no escape reservoir)?",
        "tce_antigen_escape_class",
        _ESCAPE,
    ),
]


def _tier(mapping: dict, val) -> str:
    if val in (None, "", "data_unavailable", "unmeasured"):
        return "unmeasured"
    return mapping.get(str(val), "weak")  # an unrecognized value is a measured-but-weak signal


# ── SK#1844 L3→production (G3.4): the PER-MODALITY surface_modality_fit decision frames ──────────────
# The THIRD domain the L3 typed-evidence interface (evidence_frame.py, design G) reaches a production
# answer surface — after the dependency beachhead (#1841) and the presence domain (#1842) — and the FIRST
# that mints MORE THAN ONE frame over the same domain: a per-MODALITY family (ADC / TCE), because the
# DECISION-IMPLICATIONS of the same surface evidence differ by modality (a shed ectodomain vetoes the ADC
# frame; within-tumour antigen escape vetoes the TCE frame). Each frame consumes the ALREADY-EMITTED
# composite class tokens on the headline and produces its OWN L3 decision object; this module only RENDERS
# it as a verdict-INERT annotation on the modality's home row (the ADC frame on the "ADC" row, the TCE
# frame on the "TCE" row). Rendered under the DISTINCT keys `l3_integrated_signal` / `l3_forward_question`
# (mirrors #1842's presence Q7 wiring) so it never touches an existing meter cell, and routes NOTHING back
# into the surface verdict (`fit_class`) / claim_vector / safety_verdict_by_modality / modality_rubric /
# resolver. It is NOT a re-derivation of the surface-modality-fit verdict.
def _surface_modality_frame_signal(fr: dict, modality: str) -> dict:
    """Project a per-modality frame's L3 decision object into a row's `l3_integrated_signal` surface
    (verdict-inert). `modality` names which modality-fit family this frame is (ADC / TCE)."""
    resolved = sorted(fr.get("resolved_inputs") or {})
    decision = fr.get("decision")
    vetoes = fr.get("vetoes_applied") or []
    headline = (
        f"L3 {modality} modality-fit decision frame `{fr.get('frame_id')}` → {decision}: synthesized over "
        f"{len(resolved)} resolved typed input(s)"
        + (f" ({', '.join(resolved)})" if resolved else "")
        + (f"; measured-adverse read down-ranked ({'; '.join(vetoes)})" if vetoes else "")
        + "; the safety critical is unresolved on this surface → an L4 forward question (never a kill)."
    )
    return {
        "kind": fr.get("frame_id"),
        "modality": modality,
        "frame_id": fr.get("frame_id"),
        "claim_type": fr.get("claim_type"),  # decision_frame (L3)
        "decision": decision,
        "integration_method": fr.get("integration_method"),
        "resolved_inputs": fr.get("resolved_inputs"),
        "rationale": fr.get("rationale"),
        "reservations": fr.get("reservations"),
        "vetoes_applied": fr.get("vetoes_applied"),
        "unresolved_critical": fr.get("unresolved_critical"),
        "unresolved_required": fr.get("unresolved_required"),
        "headline": headline,
        "provenance_ref": f"evidence_frame.{fr.get('frame_id')}",
        "_disclaimer": fr.get("_disclaimer"),
    }


# The modality → (home row id, production frame entry) wiring. The ADC frame surfaces on the "ADC" row,
# the TCE frame on the "TCE" row — each modality's home sub-question.
_MODALITY_FRAME_ROWS = (
    ("ADC", _adc_modality_fit_frame),
    ("TCE", _tce_modality_fit_frame),
)


def surface_modality_question_table(headline: dict, cards: Optional[list] = None) -> list:
    """Per-surface-sub-question rows from the surface-modality-fit headline class fields. Verdict-inert;
    tolerant of missing fields (an absent field → an unmeasured row, never omitted, so the hero always
    shows the full Surface/Density/ADC/TCE ladder + which leg is a named gap)."""
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
    # SK#1844 L3→production (G3.4): when the MEASURED surface antigen density resolves (the modality
    # frames' REQUIRED payload/engager-floor anchor), evaluate each per-modality decision frame over the
    # already-emitted composite class tokens and SURFACE its synthesis as a verdict-INERT `l3_integrated_
    # signal` on that modality's home row (ADC / TCE), plus the frame's CRITICAL_UNKNOWN role as an L4
    # `l3_forward_question` via the shared #1843 projector. Attached only when the anchor resolves (keys
    # omitted otherwise → row byte-stable); the distinct `l3_*` keys never touch an existing meter cell.
    if h.get("surface_density_class") not in (None, "") and h.get("surface_density_class") not in DENSITY_GAP_TOKENS:
        by_id = {r.get("id"): r for r in rows}
        for modality, frame_entry in _MODALITY_FRAME_ROWS:
            row = by_id.get(modality)
            if row is None:
                continue
            fr = frame_entry(h)
            row["l3_integrated_signal"] = _surface_modality_frame_signal(fr, modality)
            fq = _forward_question_from_frame(fr)
            if fq is not None:
                row["l3_forward_question"] = fq
    return rows


__all__ = ["surface_modality_question_table"]
