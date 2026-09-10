"""target_report.v1 — the unified per-target object (additive; references existing facets). Verdict-inert
composition; target_call owns the recommendation. Pure over synthetic inputs."""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
SKILLS = SCRIPTS.parent.parent
for _p in (str(SKILLS), str(SCRIPTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from tp_facets import _skill_reports_by_short, build_skill_report_rollup, build_target_report  # noqa: E402


def test_schema_and_slot_references():
    tc = {"schema": "target_call.v1", "recommendation": "hold"}
    rollup = {"axes": {"biological_necessity": {"band": "favorable"}}, "block": {"blocked": False}}
    tr = build_target_report(
        target_call=tc,
        target_rollup=rollup,
        target_coherence={"thesis": "x"},
        ordinal_matrix={"m": 1},
        modality_fit_by_channel={"small_molecule": {"fit": "favorable"}},
        modality_conjunction={"tce": "pass"},
        risk_rollup={"safety": {"bin": "HIGH"}},
        subtype_facet={"convergent_subtypes": []},
        fragility={"f": 1},
        heterogeneity={"h": 1},
        certainty_by_axis={"c": 1},
    )
    assert tr["schema"] == "target_report.v1"
    assert tr["target_call"] is tc  # decision by reference
    assert tr["risk_6dim"] == {"safety": {"bin": "HIGH"}}
    assert tr["axis_rollup"] == rollup["axes"] and tr["block"] == rollup["block"]
    assert tr["modality_fit"] == {
        "by_channel": {"small_molecule": {"fit": "favorable"}},
        "conjunction": {"tce": "pass"},
    }
    assert tr["subtype_convergence"] == {"convergent_subtypes": []}
    # robustness clusters the reliability facets
    assert set(tr["robustness"]) == {
        "fragility",
        "heterogeneity",
        "correlated_evidence",
        "borderline",
        "certainty_by_axis",
    }
    assert tr["robustness"]["fragility"] == {"f": 1}


def test_nullable_slots_are_none_safe():
    tr = build_target_report(target_call={"recommendation": "nominate"})
    assert tr["risk_6dim"] is None and tr["axis_rollup"] is None and tr["block"] is None
    assert tr["modality_fit"] == {"by_channel": None, "conjunction": None}
    assert tr["target_call"]["recommendation"] == "nominate"
    # step #2: the skill_report[] spine + rollup default None when no reports are passed
    assert tr["skill_reports"] is None and tr["skill_report_rollup"] is None


# ── step #2: the skill_report[] spine roll-up (docs/UNIFIED_OUTPUT_CONTRACT.md) ─────────────────────
def _reports():
    return {
        "safety": {"role": "gating", "call": "highly_constrained_safety_concern", "polarity": "opposing"},
        "selectivity": {"role": "gating", "call": "selective_but_broadly_normal", "polarity": "killer"},
        "dependency": {"role": "gating", "call": "concordant_dependent", "polarity": "supportive"},
        "expression": {"role": "descriptive", "call": "broadly_high_expression", "polarity": "not_scored"},
        "cis_coherence": {"role": "inert", "call": "expressed_cis_coupled_inert", "polarity": "not_scored"},
    }


def test_target_report_carries_and_rolls_up_the_skill_report_spine():
    tc = {"schema": "target_call.v1", "recommendation": "hold"}
    tr = build_target_report(target_call=tc, skill_reports=_reports())
    assert tr["skill_reports"] == _reports()  # the spine, by reference/value
    ru = tr["skill_report_rollup"]
    assert isinstance(ru, dict)
    # grouped by role
    assert {e["short"] for e in ru["by_role"]["gating"]} == {"safety", "selectivity", "dependency"}
    assert {e["short"] for e in ru["by_role"]["descriptive"]} == {"expression"}
    assert {e["short"] for e in ru["by_role"]["inert"]} == {"cis_coherence"}
    # peak gating signal = supportive(+2); the killer axis is named
    assert ru["peak_gating_rank"] == 2
    assert ru["killer_axes"] == ["selectivity"]
    # INV-6 coherence: a killer gating signal with a HOLD recommendation is consistent (flag False)
    assert ru["recommendation_exceeds_signals"] is False


def test_rollup_flags_inv6_breach_when_recommendation_exceeds_a_killer_signal():
    tc = {"recommendation": "nominate"}  # positive call despite a killer gating signal
    ru = build_skill_report_rollup(_reports(), tc)
    assert ru["recommendation_exceeds_signals"] is True  # surfaced, never silently allowed
    # but the rollup NEVER mutates target_call
    assert tc["recommendation"] == "nominate"


# ── #1203: biology-axis applicability mask — surface_modality "killer" on an intracellular target ────
def _mfc_intracellular_masked():
    """modality_fit_by_channel for a curated INTRACELLULAR target: biologics-family channels are masked
    `not_applicable_by_axis` (category errors), SM/degrader remain live."""
    na = {
        "fit": "not_applicable_by_axis",
        "limiting_axis": None,
        "by_axis": {},
        "masked_by_axis": "intracellular_intrinsic",
    }
    return {
        "adc": na,
        "bite_tce": na,
        "antibody": na,
        "biologics": na,
        "small_molecule": {"fit": "favorable", "by_axis": {}},
        "degrader": {"fit": "favorable", "by_axis": {}},
    }


def test_rollup_masks_surface_modality_killer_on_intracellular_target_1203():
    reports = {
        "safety": {"role": "gating", "call": "x", "polarity": "opposing"},
        "surface_modality": {"role": "gating", "call": "neither_viable", "polarity": "killer"},
        "tractability_sm": {"role": "gating", "call": "well_covered", "polarity": "supportive"},
        "dependency": {"role": "gating", "call": "concordant_dependent", "polarity": "supportive"},
    }
    ru = build_skill_report_rollup(reports, {"recommendation": "nominate"}, _mfc_intracellular_masked())
    # the surface_modality killer is a category error → relabeled not_applicable, dropped from killer_axes
    assert ru["axis_not_applicable"] == ["surface_modality"]
    assert ru["gating_polarities"]["surface_modality"] == "not_applicable"
    assert ru["killer_axes"] == []
    # so a correct nominate no longer trips the INV-6 breach
    assert ru["recommendation_exceeds_signals"] is False


def test_rollup_keeps_surface_modality_killer_on_surface_target_1203():
    # a real surface antigen: biologics channels are NOT masked → killer stays a genuine against-signal.
    reports = {
        "surface_modality": {"role": "gating", "call": "neither_viable", "polarity": "killer"},
        "dependency": {"role": "gating", "call": "x", "polarity": "supportive"},
    }
    mfc = {c: {"fit": "unfavorable"} for c in ("adc", "bite_tce", "antibody", "biologics")}
    ru = build_skill_report_rollup(reports, {"recommendation": "nominate"}, mfc)
    assert ru["axis_not_applicable"] == []
    assert ru["killer_axes"] == ["surface_modality"]
    assert ru["recommendation_exceeds_signals"] is True


def test_rollup_without_mfc_is_backward_compatible_1203():
    # no modality_fit_by_channel → no mask; the pre-#1203 behavior is preserved.
    ru = build_skill_report_rollup(_reports(), {"recommendation": "nominate"})
    assert ru["killer_axes"] == ["selectivity"]
    assert ru["axis_not_applicable"] == []
    assert ru["recommendation_exceeds_signals"] is True


def test_skill_reports_by_short_reads_synthesis_facet_tolerantly():
    sub_results = {
        "safety": {"synthesis_facet": {"skill_report": {"role": "gating", "polarity": "opposing"}}},
        "immune_context": {"synthesis_facet": None},  # facet raised/absent → skipped
        "cis_coherence": {},  # no facet key → skipped
        "subtype_fit": {"verdict": ("x", "r")},  # facet-less subtype tier → skipped
    }
    out = _skill_reports_by_short(sub_results)
    assert list(out) == ["safety"] and out["safety"]["role"] == "gating"
