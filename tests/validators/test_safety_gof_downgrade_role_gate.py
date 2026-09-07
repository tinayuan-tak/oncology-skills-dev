"""Regression guard: the mutant-selective GoF safety-downgrade must be role-gated.

The framework-wide rule audit (2026-08-15) found the WT-constraint safety downgrade
(wt_constraint_mechanism_mismatch / wt_human_genetics_mechanism_mismatch) fired for TUMOR
SUPPRESSORS whose alteration-role card carries a spurious intOGen 'Act' functional_direction
(e.g. SMARCA2: oncokb_gene_type=TSG yet functional_direction=activating) — wrongly DOWNGRADING a
genuine safety concern (an under-calls-safety bug).

DESIGN MOVED (safety.resolver.yaml v2.0.0, 2026-08-24): the role-proxy GROUP-1 mechanism-mismatch
downgrade rungs were RETIRED from the resolver (it now emits the honest raw WT-loss concern); the
allele-selective, modality-conditional downgrade moved to the Layer-2 modality-safety composition,
driven by vocabularies/wt_loss_safety_conditioning.yaml. The B4-1 review (2026-08-31) found the moved
logic had DROPPED the oncogene-role co-gate — the eligibility list is a flat OR-set, so a lone
activating signal (a TSG with a spurious IntOGen 'Act') again earned the small_molecule escape. Fix:
allele_selective_required_role_rules pins oncogene-role-safety-context as a REQUIRED co-gate. These
tests now pin the co-gate in its new (contract) home instead of the retired resolver rungs.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
RULES = REPO / "interpretation-rules" / "intracellular-intrinsic.rules.yaml"
COND = REPO / "vocabularies" / "wt_loss_safety_conditioning.yaml"


def _rules():
    doc = yaml.safe_load(RULES.read_text())
    return doc.get("rules", doc) if isinstance(doc, (list, dict)) else []


def _conditioning():
    return yaml.safe_load(COND.read_text())


def test_every_gof_downgrade_requires_oncogene_role():
    """The allele-selective WT-loss escape must require the oncogene-role co-gate — so a TSG whose
    alteration-role card carries a spurious activating direction cannot earn the small_molecule
    downgrade. The eligibility SIGNALS (activating / gof-driver) are necessary but not sufficient;
    oncogene-role-safety-context (oncokb_gene_type=ONCOGENE) must ALSO fire."""
    cond = _conditioning()
    required = cond.get("allele_selective_required_role_rules") or []
    assert "oncogene-role-safety-context" in required, (
        "allele_selective_required_role_rules must pin oncogene-role-safety-context — else a TSG with a "
        f"spurious IntOGen 'Act' label earns the WT-loss small_molecule escape. Got: {required}"
    )
    # the eligibility signals it co-gates must themselves still be declared
    elig = cond.get("allele_selective_eligibility_rules") or []
    assert "activating-driver-role-safety-context" in elig, elig


def test_oncogene_role_rule_defined_and_fires_on_oncogene():
    rules = _rules()
    rule = next((x for x in rules if isinstance(x, dict) and x.get("rule_id") == "oncogene-role-safety-context"), None)
    assert rule is not None, "oncogene-role-safety-context rule must be defined"
    w = rule.get("when", {})
    assert w.get("card_id") == "alteration-role"
    assert w.get("field") == "oncokb_gene_type"
    assert w.get("equals") == "ONCOGENE"


# --- S1-1 (cards review 2026-08-17): amplification-driven-GoF guard --------------------------------
# In the moved (contract) model the amplification guard is an allele-selective DISQUALIFIER, not a
# resolver rung: an amplification-driven oncogene (ERBB2/MDM2/MYC) has no selectable activating POINT
# mutation, so a small molecule engages WT and the WT-loss HOLD stands.
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


def test_amplified_gof_disqualifies_allele_selective_escape():
    """An amplification-driven oncogene (ERBB2/MDM2/MYC) is the WILD-TYPE protein over-produced from
    extra copies — a small molecule engages WT, so there is NO allele-selective escape and the WT-loss
    HOLD must stand. In the moved (contract) model this is a DISQUALIFIER: even with an activating role
    + the oncogene-role co-gate, the amplification disqualifier keeps small_molecule=hold."""
    cond = _conditioning()
    disq = cond.get("allele_selective_disqualifier_rules") or []
    assert _AMP_GUARD in disq, (
        f"{_AMP_GUARD} must be an allele_selective_disqualifier — else an amplification-driven oncogene "
        f"(whose drug hits WT protein) wrongly earns the WT-loss escape. Got: {disq}"
    )
