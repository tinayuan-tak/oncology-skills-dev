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
    return rows


__all__ = ["surface_modality_question_table"]
