"""Regression guard: the mutant-selective GoF safety-downgrade must be role-gated.

The framework-wide rule audit (2026-08-15) found the WT-constraint safety downgrade
(wt_constraint_mechanism_mismatch / wt_human_genetics_mechanism_mismatch) fired for TUMOR
SUPPRESSORS whose alteration-role card carries a spurious intOGen 'Act' functional_direction
(e.g. SMARCA2: oncokb_gene_type=TSG yet functional_direction=activating) — wrongly DOWNGRADING a
genuine safety concern (an under-calls-safety bug). Fix: GROUP-1 downgrades now require BOTH
activating-driver-role-safety-context AND oncogene-role-safety-context (oncokb_gene_type=ONCOGENE),
so only a genuine GoF ONCOGENE earns the downgrade. This test pins that gate.
"""
from __future__ import annotations

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
SAFETY = REPO / "resolvers" / "safety.resolver.yaml"
RULES = REPO / "interpretation-rules" / "intracellular-intrinsic.rules.yaml"

_MISMATCH = {"wt_constraint_mechanism_mismatch", "wt_human_genetics_mechanism_mismatch"}


def _rules():
    doc = yaml.safe_load(RULES.read_text())
    return doc.get("rules", doc) if isinstance(doc, (list, dict)) else []


def test_every_gof_downgrade_requires_oncogene_role():
    """Each mechanism-mismatch downgrade rung must AND-gate on both the activating signal and the
    oncogene-role signal — so a TSG (or any non-oncogene) cannot be downgraded."""
    resolver = yaml.safe_load(SAFETY.read_text())
    rungs = [r for r in resolver["resolve"] if r.get("verdict") in _MISMATCH and "when_all_fired" in r]
    assert rungs, "expected GROUP-1 mechanism-mismatch downgrade rungs"
    for r in rungs:
        waf = r["when_all_fired"]
        assert "activating-driver-role-safety-context" in waf, r
        assert "oncogene-role-safety-context" in waf, (
            f"mechanism-mismatch downgrade {r['verdict']} must require oncogene-role-safety-context "
            f"(role-agreement gate) — else a TSG gets its safety wrongly downgraded. Got: {waf}")


def test_oncogene_role_rule_defined_and_fires_on_oncogene():
    rules = _rules()
    rule = next((x for x in rules if isinstance(x, dict) and x.get("rule_id") == "oncogene-role-safety-context"), None)
    assert rule is not None, "oncogene-role-safety-context rule must be defined"
    w = rule.get("when", {})
    assert w.get("card_id") == "alteration-role"
    assert w.get("field") == "oncokb_gene_type"
    assert w.get("equals") == "ONCOGENE"
