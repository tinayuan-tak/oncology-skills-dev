"""narrator_lenses — per-skill LensConfig data for the generic narrator_engine.

Each skill's narration is expressed as data here (thesis, axis labels, scope guardrails, polarity, output
mode) instead of a bespoke synthesis_*.py module. Reference set: functional-requirement (verdict) +
on-target-safety-liability (verdict, polarity-inverted). The remaining 11 lenses are added here in the
fan-out; the 6 legacy bespoke narrators migrate onto these configs.
"""
from __future__ import annotations
from _skills_common.narrator_engine import LensConfig

FUNCTIONAL_REQUIREMENT = LensConfig(
    name="functional-requirement",
    thesis="how much the DEPENDENCY lens informs whether the target is worth pursuing — a SELECTIVE genetic "
           "dependency supports it, a pan-essential read argues AGAINST (broad tox), non-dependent is uninformative.",
    relevance_prompt="judge how much the dependency lens supports pursuing this target in this indication; "
                     "foreground the SELECTIVE-vs-PAN-ESSENTIAL distinction and any CRISPR/RNAi disagreement.",
    axis_labels={"DEP": "genetic dependency", "SEL": "context-selectivity",
                 "COND": "conditional/SL", "CHEM": "chemical-genetic"},
    scope_exclusions=("therapeutic modality", "expression/abundance as a presence claim", "mutation frequency"),
    mode="verdict",
)

ON_TARGET_SAFETY = LensConfig(
    name="on-target-safety-liability",
    thesis="whether the target is intolerant of loss-of-function in humans — i.e. the ON-TARGET SAFETY "
           "LIABILITY of a full-KO modality (degrader / RNA / full-inhibition SM).",
    relevance_prompt="judge the on-target safety LIABILITY of full loss-of-function for this target; an "
                     "activating mutant-selective (GoF) mechanism DOWNGRADES the WT-constraint concern.",
    axis_labels={},
    scope_exclusions=("tumor presence/abundance", "efficacy", "modality choice beyond full-KO tolerability"),
    polarity_note="signal = strength of the LIABILITY. High gnomAD constraint, broad normal-tissue expression, "
                  "germline pathogenicity, haploinsufficiency, and pan-essentiality are STRONG liability; a "
                  "strongly_selective dependency is REASSURING (LOW broad-tox liability), not support.",
    relevance_enum=("high_liability", "moderate_liability_with_caveats", "low_liability", "insufficient_evidence"),
    mode="verdict",
)

# Registry for the dispatcher / fan-out lookup by skill name.
LENSES = {L.name: L for L in (FUNCTIONAL_REQUIREMENT, ON_TARGET_SAFETY)}
