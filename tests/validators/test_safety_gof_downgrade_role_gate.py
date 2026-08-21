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


# --- S1-1 (cards review 2026-08-17): amplification-driven-GoF guard --------------------------------
# pan_essential_broad_tox_concern (2026-08-21): the pan-essential broad-tox HOLD also carries a
# GROUP-1 mutant-selective downgrade, so it needs the same amplification guard as the gnomAD/burden holds.
_HOLDS = {"highly_constrained_safety_concern", "human_genetics_safety_concern", "pan_essential_broad_tox_concern"}
_AMP_GUARD = "copy-number-amplified-oncogene-safety-context"


def test_amplification_guard_rule_defined():
    """The amplification signal that blocks the mutant-selective downgrade must be a real rule keyed
    on the tumour-cohort recurrent FOCAL amplification class."""
    rule = next((x for x in _rules() if isinstance(x, dict) and x.get("rule_id") == _AMP_GUARD), None)
    assert rule is not None, f"{_AMP_GUARD} rule must be defined"
    w = rule.get("when", {})
    assert w.get("card_id") == "copy-number-distribution"
    assert w.get("field") == "patient_focal_cn_class"
    assert w.get("equals") == "recurrent_focal_amplification"


def test_amplified_gof_keeps_hold_above_every_downgrade():
    """For EVERY GROUP-1 mechanism-mismatch downgrade (warning + both role rules), there must be a
    higher-precedence GROUP-0 rung that fires the SAME warning + both role rules + the amplification
    guard and yields a HOLD (not a mismatch) — so an amplification-driven oncogene (ERBB2/MDM2), whose
    drug hits WT protein, keeps its on-target-safety hold instead of being downgraded."""
    resolve = yaml.safe_load(SAFETY.read_text())["resolve"]
    downgrades = [(i, r) for i, r in enumerate(resolve)
                  if r.get("verdict") in _MISMATCH and "when_all_fired" in r]
    assert downgrades, "expected GROUP-1 mechanism-mismatch downgrade rungs"
    guards = [(i, r) for i, r in enumerate(resolve)
              if r.get("verdict") in _HOLDS and _AMP_GUARD in (r.get("when_all_fired") or [])]
    assert guards, "expected GROUP-0 amplification-guard rungs that keep the hold"
    # every guard must AND-gate on the amp rule + BOTH role rules (else it would over-broadly hold)
    for _, g in guards:
        waf = g["when_all_fired"]
        assert "activating-driver-role-safety-context" in waf and "oncogene-role-safety-context" in waf, g
    for di, d in downgrades:
        warning = next(x for x in d["when_all_fired"] if x.endswith("-safety-warning"))
        # a guard sharing this warning must exist AND sit BEFORE the downgrade (precedence: first match wins)
        matching = [gi for gi, g in guards if warning in g["when_all_fired"]]
        assert matching, f"no amplification-guard rung for warning {warning}"
        assert min(matching) < di, (
            f"amplification guard for {warning} must precede the GROUP-1 downgrade at index {di} "
            f"(first-match-wins) — else the downgrade fires before the guard can keep the hold")
