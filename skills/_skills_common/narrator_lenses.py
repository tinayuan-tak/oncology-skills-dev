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
    verdict_key="dependency_verdict",   # the RESOLVED dependency verdict token; else the collapsed-verdict
                                        # prompt line fell through to driving_rule_id (a rule-id string, e.g.
                                        # "lineage-selective-supportive") — mirrors the TUMOR_PRESENCE /
                                        # TUMOR_SELECTIVITY fix (the FR headline key is dependency_verdict).
)

ON_TARGET_SAFETY = LensConfig(
    name="on-target-safety-liability",
    thesis="whether the target is intolerant of loss-of-function in humans — i.e. the ON-TARGET SAFETY "
           "LIABILITY of a full-KO modality (degrader / RNA / full-inhibition SM).",
    relevance_prompt="judge the on-target safety LIABILITY of full loss-of-function for this target. The "
                     "scalar verdict is the HONEST raw WT-loss concern; the mutant-selective downgrade is "
                     "MODALITY-CONDITIONAL, realised in the per-modality safety verdict (an allele-selective "
                     "small molecule may spare WT protein), NOT applied to the scalar verdict — do not narrate "
                     "the scalar concern as downgraded.",
    axis_labels={},
    scope_exclusions=("tumor presence/abundance", "efficacy", "modality choice beyond full-KO tolerability"),
    polarity_note="signal = strength of the LIABILITY. High gnomAD constraint, broad normal-tissue expression, "
                  "germline pathogenicity, haploinsufficiency, and pan-essentiality are STRONG liability; a "
                  "strongly_selective dependency is REASSURING (LOW broad-tox liability), not support.",
    relevance_enum=("high_liability", "moderate_liability_with_caveats", "low_liability", "insufficient_evidence"),
    mode="verdict",
    verdict_key="safety_verdict",   # the RESOLVED safety verdict token (run.py headline key); else the
                                    # collapsed-verdict prompt line fell through to driving_rule_id (a rule-id
                                    # string, e.g. "highly-constrained-safety-warning") — mirrors the
                                    # TUMOR_PRESENCE / TUMOR_SELECTIVITY / FUNCTIONAL_REQUIREMENT fix.
)

TUMOR_PRESENCE = LensConfig(
    name="tumor-presence",
    thesis="how much the EXPRESSION/PRESENCE lens informs whether the target is a relevant drug target — "
           "abundant + tumor-elevated/selective supports it; merely present but ubiquitous is uninformative.",
    relevance_prompt="judge how much the presence evidence supports this target's relevance in this cancer "
                     "(indication and, where measured, subtype grain).",
    axis_labels={"A": "abundance", "B": "tumor-elevation", "C": "malignant-intrinsic", "D": "generality"},
    scope_exclusions=("therapeutic modality", "surface accessibility"),
    mode="verdict",
    verdict_key="presence_verdict",   # the collapsed word lives here (was mis-read as driving_rule_id)
)

TUMOR_SELECTIVITY = LensConfig(
    name="tumor-selectivity",
    thesis="whether the target is TUMOR-SELECTIVE enough to open a therapeutic window (tumor-enriched vs "
           "normal tissue), the decisive axis being the normal-tissue comparator.",
    relevance_prompt="judge the tumor-selectivity / therapeutic-window support for this target.",
    axis_labels={"WIN": "therapeutic window", "DIST": "normal-tissue distribution",
                 "INT": "tumor-intrinsic", "SAFE": "safety"},
    scope_exclusions=("absolute abundance as presence", "therapeutic modality",
                      "on-target safety severity / nomination call"),
    mode="verdict",
    verdict_key="selectivity_class",   # the RESOLVED (post-veto) class token; else the collapsed-verdict
                                       # prompt line fell through to driving_rule_id (a rule-id string),
                                       # e.g. "tvn-...-veto" — mirrors the TUMOR_PRESENCE fix.
)

GENOMIC_ALTERATION = LensConfig(
    name="genomic-alteration-profile",
    thesis="HOW the target is genomically altered (SNV/indel, copy-number, fusion, or a mix) and which "
           "alteration CLASS carries the signal — not a single 'is it a driver' call.",
    relevance_prompt="judge how the genomic-alteration evidence supports this target, naming which class drives.",
    axis_labels={"SNV": "SNV/indel", "CN": "copy-number", "FUS": "fusion", "DEP": "alteration-conferred dependency"},
    scope_exclusions=("therapeutic modality", "expression as presence"),
    mode="verdict",
    verdict_key="genomic_alteration_profile",   # the RESOLVED multi-class verdict token (run.py headline
                                                # key); else the collapsed-verdict fallback lands on the
                                                # <name>_verdict guess ("genomic_alteration_profile_verdict"
                                                # — note the extra "_verdict") which MISSES the real key
                                                # `genomic_alteration_profile`, then falls through to
                                                # driving_rule_id (a rule-id string, e.g.
                                                # "mutant-strongly-dependent-supportive"). genomic-alteration
                                                # was the LAST verdict-skill left behind; mirrors the
                                                # presence/selectivity/safety/functional-requirement/
                                                # surface-modality-fit contract.
)

SURFACE_MODALITY_FIT = LensConfig(
    name="surface-modality-fit",
    thesis="whether the surface biology supports a BIOLOGICS modality — ADC-favorable, TCE-favorable, both, "
           "or neither — from topology, surfaceome family, density, and normal-tissue/shedding liabilities.",
    relevance_prompt="judge the biologics surface-modality fit (ADC / TCE / both / neither).",
    axis_labels={"FIT": "modality fit", "TOPOLOGY": "topology/accessibility", "DENSITY": "surface density",
                 "SAFETY": "normal-tissue safety", "SHED": "shedding"},
    scope_exclusions=("small-molecule tractability", "intracellular mechanism"),
    mode="verdict",
    verdict_key="surface_modality_verdict",   # the RESOLVED surface-modality verdict token (run.py headline
                                              # key); else the collapsed-verdict fallback lands on the
                                              # <name>_verdict guess ("surface_modality_fit_verdict" — note
                                              # the extra "fit") which MISSES the real key, then on
                                              # driving_rule_id (a rule-id string). Mirrors the
                                              # presence/selectivity/safety/functional-requirement contract.
)

TRACTABILITY_SM = LensConfig(
    name="tractability-small-molecule",
    thesis="whether the target looks druggable by a SMALL MOLECULE — is there a compound that hits it, and "
           "does the chemical signal agree with the genetic dependency.",
    relevance_prompt="judge the small-molecule tractability (chemical + structural evidence).",
    axis_labels={"POTENCY": "binding potency", "ACTIVITY": "cellular activity", "STRUCT": "structural ligandability",
                 "DRUG": "drug/tool compound", "DEGRADER": "degrader handle"},
    scope_exclusions=("biologics/surface modality", "expression as presence"),
    mode="verdict",
    verdict_key="druggability_snapshot",         # the headline key holding the resolved snapshot token
                                                 # (NOT the legacy <name>_verdict guess, which would be
                                                 # "tractability_small_molecule_verdict" and MISS it →
                                                 # fall through to driving_rule_id, a rule-id string).
                                                 # Mirrors presence/selectivity/FR/safety/surface/genomic;
                                                 # tractability-small-molecule was the last one left behind.
)

IMMUNE_CONTEXT = LensConfig(
    name="immune-context",
    thesis="the immune/TME context for a T-cell-engager — CD8 infiltration and whether the tumor is "
           "inflamed vs excluded/desert (the effector-arm companion to surface-modality-fit).",
    relevance_prompt="judge how the immune-context evidence supports a TCE effector arm for this target.",
    axis_labels={"IMMUNE": "CD8 / immune infiltration"},
    scope_exclusions=("surface antigen accessibility (owned by surface-modality-fit)", "small-molecule tractability"),
    mode="verdict",
    # The collapsed-verdict line reads the RESOLVED effector-context token from this declared headline key.
    # Without it, the fallback relies on the legacy `<name>_verdict` guess ("immune-context" →
    # "immune_context_verdict"), which HAPPENS to equal the real key here (unlike surface/genomic, whose
    # guesses carried an extra token) — so this is a robustness/consistency fix, not an active-bug fix:
    # it removes the naming-coincidence dependency and brings this lens into line with the fleet.
    verdict_key="immune_context_verdict",
)

DIFFERENTIATION_LANDSCAPE = LensConfig(
    name="differentiation-landscape",
    thesis="what patient-selection / combination-biology hypotheses the co-mutation, stemness, node-leverage "
           "and prognostic landscape support for this target.",
    relevance_prompt="judge how the differentiation-landscape evidence informs patient-selection / positioning.",
    axis_labels={"COMUT": "co-mutation / mutual-exclusivity", "SURVIVAL": "subtype survival",
                 "PROGNOSIS": "prognostic association", "NODE": "pathway node-leverage"},
    scope_exclusions=("therapeutic modality", "dependency magnitude (owned by functional-requirement)"),
    mode="verdict",
)

MECHANISM_PHARMACOLOGY = LensConfig(
    name="mechanism-and-pharmacology",
    thesis="the signaling-network mechanism + candidate MoA hooks + PD-marker suggestions — how well the "
           "target's mechanism is characterized and what it implies for SM/degrader/glue programs.",
    relevance_prompt="give the mechanism / MoA-hook context read for this target (descriptive; no nomination call).",
    axis_labels={"NETWORK": "signaling network", "PHOSPHO": "phospho activity", "PATHWAY": "pathway activity",
                 "PERTURBATION": "drug-perturbation MoA", "PREDICTABILITY": "dependency predictability"},
    scope_exclusions=("nomination verdict", "therapeutic modality selection"),
    mode="descriptive",
)

CIS_FEATURE_COHERENCE = LensConfig(
    name="cis-feature-coherence",
    thesis="whether the locus→expression→dependency chain is COHERENT (cis copy-number dosage coupling, "
           "methylation silencing, expression↔dependency) — a data-integrity / mechanism-plausibility context.",
    relevance_prompt="give the cis-feature-coherence context read (descriptive; no nomination call).",
    axis_labels={"CIS_DOSAGE": "cis copy-number dosage", "SILENCING": "methylation silencing",
                 "EXPR_DEP": "expression↔dependency", "CONJOINT": "conjoint patient cis-dosage"},
    scope_exclusions=("nomination verdict",),
    mode="descriptive",
)

COMBINATION_VULNERABILITY = LensConfig(
    name="combination-and-vulnerability",
    thesis="the relational (gene×gene) opportunities — synthetic-lethal partners, measured dual-KO "
           "co-dependencies, combination co-targets under inhibition, and resistance mediators.",
    relevance_prompt="give the combination / vulnerability context read (descriptive ranked-partner annex; no nomination call).",
    axis_labels={"SL": "synthetic-lethal", "CODEP": "paralog dual-KO co-dependency",
                 "COMBO": "combination co-target", "RESISTANCE": "resistance mediators"},
    scope_exclusions=("single-target nomination verdict",),
    mode="descriptive",
)

TARGET_INTRINSIC = LensConfig(
    name="target-intrinsic",
    thesis="the indication-INDEPENDENT intrinsic target dossier — modality routing (surface vs intracellular), "
           "annotation/characterization, interactome hubness, and tractability precedent.",
    relevance_prompt="give the intrinsic target-biology context read (descriptive dossier; no nomination call).",
    axis_labels={"MODALITY_ROUTING": "modality routing", "TRACTABILITY_PRECEDENT": "tractability precedent"},
    scope_exclusions=("indication-conditioned nomination verdict",),
    mode="descriptive",
)

# Registry for the dispatcher / fan-out lookup by skill name — ALL 13 hierarchy skills.
LENSES = {L.name: L for L in (
    FUNCTIONAL_REQUIREMENT, ON_TARGET_SAFETY, TUMOR_PRESENCE, TUMOR_SELECTIVITY, GENOMIC_ALTERATION,
    SURFACE_MODALITY_FIT, TRACTABILITY_SM, IMMUNE_CONTEXT, DIFFERENTIATION_LANDSCAPE,
    MECHANISM_PHARMACOLOGY, CIS_FEATURE_COHERENCE, COMBINATION_VULNERABILITY, TARGET_INTRINSIC)}
