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

from tp_facets import build_target_report, build_skill_report_rollup, _skill_reports_by_short  # noqa: E402


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


def test_skill_reports_by_short_reads_synthesis_facet_tolerantly():
    sub_results = {
        "safety": {"synthesis_facet": {"skill_report": {"role": "gating", "polarity": "opposing"}}},
        "immune_context": {"synthesis_facet": None},  # facet raised/absent → skipped
        "cis_coherence": {},  # no facet key → skipped
        "subtype_fit": {"verdict": ("x", "r")},  # facet-less subtype tier → skipped
    }
    out = _skill_reports_by_short(sub_results)
    assert list(out) == ["safety"] and out["safety"]["role"] == "gating"
