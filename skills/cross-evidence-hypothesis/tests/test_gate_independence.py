"""P4 reconciliation — the certainty discount consumes the spine's AUTHORITATIVE cross-gate
correlation (gate_independence) as the MORE CONSERVATIVE independence unit count (min with the
card-substrate view). Proves: union-find over supporting gates, the min() tightening, the
never-more-permissive invariant, and byte-stable fallback when the spine facet is absent."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from _test_support import load_run_py

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import hypothesis_core as hc  # noqa: E402

R = load_run_py(SCRIPTS.parent, "ce_run_gate_indep")

FIX = Path(__file__).resolve().parent / "fixtures"
PKG = FIX / "evidence_package_new_blocks.json"


# =============================== gate_independence (union-find) ====================================


def test_absent_facet_is_not_present_and_none():
    g = hc.gate_independence(None, ["dependency", "selectivity"])
    assert g["present"] is False and g["n_independent_gate_groups"] is None
    assert hc.gate_independence({}, ["dependency"])["present"] is False


def test_no_correlation_each_gate_its_own_group():
    g = hc.gate_independence({"correlated_gate_pairs": []}, ["dependency", "selectivity", "safety"])
    assert g["present"] is True and g["n_independent_gate_groups"] == 3


def test_one_shared_pair_collapses_to_two_groups():
    g = hc.gate_independence(
        {"correlated_gate_pairs": [["safety", "genomic_alteration"]]}, ["dependency", "safety", "genomic_alteration"]
    )
    assert g["n_independent_gate_groups"] == 2  # {dependency} + {safety, genomic_alteration}


def test_transitive_collapse_to_one_group():
    g = hc.gate_independence({"correlated_gate_pairs": [["a", "b"], ["b", "c"]]}, ["a", "b", "c"])
    assert g["n_independent_gate_groups"] == 1  # a-b-c all connected


def test_pair_touching_nonsupporting_gate_is_ignored():
    # 'surface_modality' is NOT a supporting gate this run → the pair must not collapse dependency
    g = hc.gate_independence(
        {"correlated_gate_pairs": [["dependency", "surface_modality"]]}, ["dependency", "selectivity"]
    )
    assert g["n_independent_gate_groups"] == 2 and g["correlated_gate_pairs"] == []


# =============================== discounted_certainty reconciliation ================================


def test_gate_groups_tighten_when_more_conservative():
    # substrate says 3 independent, but the spine collapses the gates to 1 group → cap low
    c = hc.discounted_certainty("high", n_independent_units=3, degraded_inputs=[], n_independent_gate_groups=1)
    assert c["final"] == "low" and c["effective_independent_units"] == 1
    assert c["independence_unit_kind"] == "decision-gate-group"
    assert any("decision-gate-group" in r for r in c["cap_reasons"])


def test_substrate_still_caps_when_gate_view_is_healthy():
    # NEVER MORE PERMISSIVE: a healthy gate count (5) must not rescue a single-substrate target
    c = hc.discounted_certainty("high", n_independent_units=1, degraded_inputs=[], n_independent_gate_groups=5)
    assert c["final"] == "low" and c["effective_independent_units"] == 1
    assert c["independence_unit_kind"] == "substrate"


def test_no_cap_when_both_views_independent():
    c = hc.discounted_certainty("high", n_independent_units=3, degraded_inputs=[], n_independent_gate_groups=4)
    assert c["final"] == "high" and c["effective_independent_units"] == 3


def test_gate_view_absent_is_substrate_only():
    # older package (facet absent) → gate groups None → substrate basis, behaviour unchanged
    c = hc.discounted_certainty("high", n_independent_units=3, degraded_inputs=[], n_independent_gate_groups=None)
    assert c["final"] == "high" and c["effective_independent_units"] == 3
    assert c["independence_unit_kind"] == "substrate"


# =============================== run-level wiring + byte-stability =================================


def _stub(system, user, name, schema, **kw):
    if name == "cross_edges":
        return {"edges": [], "principal_tensions": [], "evidence_paths": []}
    return {
        "causal_rationale": {"statement": "x", "citations": ["dependency"]},
        "therapeutic_hypothesis": {"statement": "x", "modality": "small_molecule", "citations": ["dependency"]},
        "population": {"statement": "x", "citations": ["dependency"]},
        "therapeutic_window": {"statement": "x", "citations": ["safety"]},
        "evidence_grade": {"overall": "moderate", "per_line": []},
        "proposed_verdict": "advanceable",
        "proposed_verdict_reason": "x",
        "go_forth": {"next_evidence": "y"},
    }


def test_run_without_facet_leaves_gate_independence_inert(tmp_path):
    """The fixture has no decision_facets → gate view absent → effective units == substrate units
    (byte-stable: the discount is unchanged from before P4-reconciliation)."""
    p = tmp_path / "ep.json"
    p.write_text(PKG.read_text())
    r = R.run(str(p), None, "small-molecule drug target", "small_molecule", None, synthesize_fn=_stub)
    ei = r["evidence_independence"]
    assert ei["gate_independence_present"] is False
    assert ei["n_independent_gate_groups"] is None
    assert ei["effective_independent_units"] == ei["n_independent_substrate_units"]
    assert ei["independence_unit_kind"] == "substrate"


def test_run_with_collapsing_facet_tightens_certainty(tmp_path):
    """A package whose spine cross-gate facet collapses the supporting gates to ONE group → certainty
    is discounted via the gate-group view even though the substrate view alone might not."""
    pkg = json.loads(PKG.read_text())
    supporting = [
        d
        for d, v in {
            k: (x.get("verdict") if isinstance(x, dict) else x) for k, x in pkg["synthesis"]["sub_verdicts"].items()
        }.items()
        if v not in hc.GAP_VERDICTS
    ]
    pairs = [[supporting[0], s] for s in supporting[1:]]  # star → all collapse into one group
    pkg["synthesis"]["decision_facets"] = {"cross_gate_shared_evidence": {"correlated_gate_pairs": pairs}}
    p = tmp_path / "ep.json"
    p.write_text(json.dumps(pkg))
    r = R.run(str(p), None, "small-molecule drug target", "small_molecule", None, synthesize_fn=_stub)
    ei = r["evidence_independence"]
    assert ei["gate_independence_present"] is True
    assert ei["n_independent_gate_groups"] == 1
    assert ei["effective_independent_units"] == 1
    assert r["uncertainty"]["overall_certainty"] == "low"
