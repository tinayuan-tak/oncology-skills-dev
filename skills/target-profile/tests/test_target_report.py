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

from tp_facets import build_target_report  # noqa: E402


def test_schema_and_slot_references():
    tc = {"schema": "target_call.v1", "recommendation": "hold"}
    rollup = {"axes": {"biological_necessity": {"band": "favorable"}}, "block": {"blocked": False}}
    tr = build_target_report(
        target_call=tc, target_rollup=rollup, target_coherence={"thesis": "x"},
        ordinal_matrix={"m": 1}, modality_fit_by_channel={"small_molecule": {"fit": "favorable"}},
        modality_conjunction={"tce": "pass"}, risk_rollup={"safety": {"bin": "HIGH"}},
        subtype_facet={"convergent_subtypes": []}, fragility={"f": 1}, heterogeneity={"h": 1},
        certainty_by_axis={"c": 1})
    assert tr["schema"] == "target_report.v1"
    assert tr["target_call"] is tc                       # decision by reference
    assert tr["risk_6dim"] == {"safety": {"bin": "HIGH"}}
    assert tr["axis_rollup"] == rollup["axes"] and tr["block"] == rollup["block"]
    assert tr["modality_fit"] == {"by_channel": {"small_molecule": {"fit": "favorable"}},
                                  "conjunction": {"tce": "pass"}}
    assert tr["subtype_convergence"] == {"convergent_subtypes": []}
    # robustness clusters the reliability facets
    assert set(tr["robustness"]) == {"fragility", "heterogeneity", "correlated_evidence",
                                     "borderline", "certainty_by_axis"}
    assert tr["robustness"]["fragility"] == {"f": 1}


def test_nullable_slots_are_none_safe():
    tr = build_target_report(target_call={"recommendation": "nominate"})
    assert tr["risk_6dim"] is None and tr["axis_rollup"] is None and tr["block"] is None
    assert tr["modality_fit"] == {"by_channel": None, "conjunction": None}
    assert tr["target_call"]["recommendation"] == "nominate"
