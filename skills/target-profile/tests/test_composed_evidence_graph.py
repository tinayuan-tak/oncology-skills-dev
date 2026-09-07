"""P6 — the thin composed index at target_report.evidence_graph (docs/COMPOSED_EVIDENCE_GRAPH_ROLLUP.md §2):
the target decision as a node/edge graph (composed analog of the per-subskill decision.headline.evidence_graph).
A PURE PROJECTION over target_report — verdict + skill nodes + typed cross-lens edges that reference existing
rollups by `ref`. Verdict-inert / display-only.
"""

import json
import os
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from tp_facets import build_composed_evidence_graph, build_target_report


def _target_report() -> dict:
    return {
        "schema": "target_report.v1",
        "skill_reports": {
            "safety": {
                "role": "gating",
                "call": "highly_constrained_safety_concern",
                "polarity": "killer",
                "confidence": {"level": "moderate"},
                "evidence_graph": {"literature": {"overall_consistency": "concordant"}},
            },
            "dependency": {
                "role": "gating",
                "call": "selective_dependency",
                "polarity": "supportive",
                "confidence": {"level": "high"},
            },
            "expression": {
                "role": "gating",
                "call": "tumor_broadly_expressed",
                "polarity": "supportive",
                "confidence": {"level": "moderate"},
            },
        },
        "target_call": {
            "recommendation": "hold",
            "confidence": {"level": "moderate"},
            "deciding_axis": {
                "basis": "gate_fired",
                "deciding_axis": {"short": "safety", "gate": None, "gate_name": "On-target safety"},
            },
            "dissent": [
                {
                    "source": "target_rollup.block",
                    "detail": "dependency supportive overruled by safety",
                    "resolved_to": "hold",
                }
            ],
        },
        "risk_6dim": {
            "safety": {"pillar": "Right Safety", "bin": "HIGH"},
            "biological": {"pillar": "Right Target", "bin": "LOW"},
        },
        "modality_fit": {
            "by_channel": {
                "small_molecule": {"fit": "unfavorable", "limiting_axis": "safety", "by_axis": {}},
                "adc": {"fit": "na", "limiting_axis": None, "by_axis": {}},
            }
        },
        "subtype_convergence": {"convergent_subtypes": ["MSI_H"]},
    }


@pytest.fixture
def eg():
    return build_composed_evidence_graph(_target_report())


def test_verdict_and_skill_nodes(eg):
    assert eg["schema"] == "composed_evidence_graph.v1"
    assert eg["verdict"]["recommendation"] == "hold"
    assert eg["verdict"]["deciding_shorts"] == ["safety"]
    nodes = {s["short"]: s for s in eg["skills"]}
    assert set(nodes) == {"safety", "dependency", "expression"}
    assert nodes["safety"]["deciding"] is True
    assert nodes["safety"]["lens"] == "risk"  # SKILL_TOPICAL_LENS
    assert nodes["safety"]["has_evidence_graph"] is True
    assert nodes["safety"]["literature_consistency"] == "concordant"
    assert nodes["dependency"]["lens"] == "signals"
    assert nodes["dependency"]["has_evidence_graph"] is False


def test_typed_cross_lens_edges(eg):
    by_type = {}
    for e in eg["edges"]:
        by_type.setdefault(e["type"], []).append(e)
    assert set(by_type) == {"deciding_axis", "dissent", "modality_fit", "risk", "subtype_convergence"}
    assert by_type["deciding_axis"][0]["to"] == "safety"
    assert by_type["dissent"][0]["from"] == "target_rollup.block"
    assert by_type["subtype_convergence"][0]["to"] == "MSI_H"
    sm = next(e for e in by_type["modality_fit"] if e["to"] == "small_molecule")
    assert sm["from"] == "safety" and sm["signal"] == "unfavorable"
    risk_safety = next(e for e in by_type["risk"] if e["to"] == "safety")
    assert risk_safety["bin"] == "HIGH"
    # every edge references an existing target_report rollup by `ref`
    for e in eg["edges"]:
        assert e["ref"].startswith("target_report.")


def test_typed_referential_integrity(eg):
    shorts = {s["short"] for s in eg["skills"]}
    for e in eg["edges"]:
        if e["type"] == "deciding_axis":
            assert e["to"] in shorts  # deciding edge targets a real skill node
        if e["type"] == "modality_fit" and e["from"] is not None:
            assert e["from"] in shorts  # limiting axis is a real skill node


def test_build_target_report_attaches_the_index():
    tr = _target_report()
    report = build_target_report(
        target_call=tr["target_call"],
        skill_reports=tr["skill_reports"],
        risk_rollup=tr["risk_6dim"],
        modality_fit_by_channel=tr["modality_fit"]["by_channel"],
        subtype_facet=tr["subtype_convergence"],
    )
    assert isinstance(report.get("evidence_graph"), dict)
    assert report["evidence_graph"]["schema"] == "composed_evidence_graph.v1"
    assert report["evidence_graph"]["verdict"]["recommendation"] == "hold"


def test_fail_soft_on_empty_target_report():
    eg = build_composed_evidence_graph({})
    assert eg["schema"] == "composed_evidence_graph.v1"
    assert eg["skills"] == [] and eg["edges"] == []
    assert eg["verdict"]["recommendation"] is None


def test_validates_against_contracts_schema(eg):
    root = os.environ.get("TARGET_CONTRACTS_ROOT")
    schema_path = Path(root) / "schemas" / "composed_evidence_graph.schema.json" if root else None
    if not schema_path or not schema_path.exists():
        pytest.skip("composed_evidence_graph.schema.json not found (pin TARGET_CONTRACTS_ROOT)")
    import jsonschema

    jsonschema.validate(eg, json.loads(schema_path.read_text()))
