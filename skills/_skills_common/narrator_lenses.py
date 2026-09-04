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
           "dependency supports it, a pan-essential read argues AGAINST (broad tox), non-dependent is "
           "uninformative — and, critically, whether the call is CORROBORATED across the independent "
           "perturbation channels (CRISPR-KO + RNAi + PRISM chemical-genetic + Broad↔Sanger cross-consortium) "
           "or rests on a single screen, and whether it is buffered by a redundant PARALOG (single-gene KO can "
           "under-call a real dependency).",
    relevance_prompt="judge how much the dependency lens supports pursuing this target in this indication; "
                     "foreground the SELECTIVE-vs-PAN-ESSENTIAL distinction and any CRISPR/RNAi disagreement.",
    axis_labels={"DEP": "genetic dependency", "SEL": "context-selectivity",
                 "COND": "conditional/SL", "CHEM": "chemical-genetic"},
    scope_exclusions=("therapeutic modality", "expression/abundance as a presence claim", "mutation frequency"),
    # NARRATOR RULE: lead with cross-channel corroboration (the quorum), then selective-vs-pan-essential,
    # then paralog buffering, then the two data-shape reconciliations — the things a single-card read hides.
    polarity_note=(
        "LEAD by stating whether the dependency is CORROBORATED across the independent perturbation "
        "channels — CRISPR-KO, RNAi (orthogonal LoF), PRISM chemical-genetic triangulation, and Broad↔Sanger "
        "cross-consortium replication (a QUORUM) — or rests on a single screen; name which channels agree "
        "vs disagree. Then make the SELECTIVE-vs-PAN-ESSENTIAL call: a pan-/common-essential read is a "
        "broad-toxicity LIABILITY, not support, and must key on the CURATED common-essential control "
        "(depmap_curated_common_essential), NOT a raw dependent-fraction (the 'oncogene reads pan-essential' "
        "trap) — a selective dependency sitting between the essential/non-essential controls is the win. "
        "Flag paralog buffering (paralog_buffering_class): a STRONG buffer means the single-gene dependency "
        "may be redundancy-masked and need combined paralog loss or an upstream pan-family node; even a "
        "PARTIAL buffer on a non-dependent/discordant read can under-call a paralog-buffered vulnerability "
        "that shifts to the redundant paralog (the SMARCA4→SMARCA2 SL class — check the COND axis). Finally, "
        "do NOT over-read three scope/data-shape artifacts: (1) a `*_concordant_non_dependent` CRISPR↔RNAi "
        "concordance alongside both distributions reading a selective class is a POOLED-SCOPE selective "
        "signature (concordance_scope_note), not a modality contradiction; (2) a decisive single-arm signal "
        "held at a coverage-gap verdict (measurement_caveat) is decisive-but-unconfirmed, not measured-"
        "absent; (3) the pooled verdict is TARGET-GRAIN — when indication_scope_note is present the queried "
        "indication is NOT the enriched lineage, so report the indication-scope answer "
        "(dependency_verdict_by_scope.indication), not the target-grain token."),
    mode="verdict",
    verdict_key="dependency_verdict",   # the RESOLVED dependency verdict token; else the collapsed-verdict
                                        # prompt line fell through to driving_rule_id (a rule-id string, e.g.
                                        # "lineage-selective-supportive") — mirrors the TUMOR_PRESENCE /
                                        # TUMOR_SELECTIVITY fix (the FR headline key is dependency_verdict).
)

ON_TARGET_SAFETY = LensConfig(
    name="on-target-safety-liability",
    thesis="whether the target is intolerant of loss-of-function in humans — i.e. the ON-TARGET SAFETY "
           "LIABILITY of a full-KO modality (degrader / RNA / full-inhibition SM) — corroborated across the "
           "human-genetics legs (gnomAD constraint, gene-burden, ClinGen dosage, ClinVar germline "
           "pathogenicity, mouse-KO), DepMap pan-essentiality, and — where drugs already engage the target — "
           "the ON-TARGET CLINICAL PHARMACOVIGILANCE precedent (which toxicity classes / boxed warnings the "
           "target's own drugs carry), naming the specific mouse-KO ORGAN systems and clinical toxicity "
           "CLASSES rather than a bare verdict.",
    relevance_prompt="judge the on-target safety LIABILITY of full loss-of-function for this target. The "
                     "scalar verdict is the HONEST raw WT-loss concern; the mutant-selective downgrade is "
                     "MODALITY-CONDITIONAL, realised in the per-modality safety verdict (an allele-selective "
                     "small molecule may spare WT protein), NOT applied to the scalar verdict — do not narrate "
                     "the scalar concern as downgraded. Where present, foreground the specific on-target "
                     "clinical toxicity CLASSES (pharmacovigilance) and mouse-KO ORGAN systems.",
    axis_labels={"PHARMACOVIGILANCE": "on-target clinical pharmacovigilance"},
    scope_exclusions=("tumor presence/abundance", "efficacy", "modality choice beyond full-KO tolerability"),
    polarity_note="signal = strength of the LIABILITY. High gnomAD constraint, broad normal-tissue expression, "
                  "germline pathogenicity, haploinsufficiency, and pan-essentiality are STRONG liability; a "
                  "strongly_selective dependency is REASSURING (LOW broad-tox liability), not support. When a "
                  "PHARMACOVIGILANCE signal is present, LEAD with the specific on-target clinical toxicity "
                  "classes / boxed warnings — but treat it as CONFOUNDED CONTEXT (on- vs off-target cannot be "
                  "separated; corroboration is capped): it orients, it is never itself the verdict.",
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
           "abundant + tumor-elevated/selective supports it; merely present but ubiquitous is uninformative "
           "and (when the normal comparators read HIGH_LIABILITY) flags a therapeutic-window liability whose "
           "VERDICT is owned by the tumor-selectivity + on-target-safety lenses — note the hand-off, do not "
           "adjudicate the window here — WHILE distinguishing a MALIGNANT-CELL PROTEIN-CONFIRMED presence "
           "(CPTAC/cell-line-MS or HPA-IHC protein + a single-cell malignant-compartment attribution) from "
           "a target that merely reads present off BULK RNA, a pan-cancer CELL-LINE annotation, or a "
           "STROMAL/immune compartment WITHOUT confirmed malignant-cell protein (the bulk-RNA-over-calls-"
           "malignant-protein inflation — the FAP/stromal-marker analog), and from a ubiquitous/housekeeping "
           "level that reads present but is not tumor-ELEVATED.",
    relevance_prompt="judge how much the presence evidence supports this target's relevance in this cancer "
                     "(indication and, where measured, subtype grain).",
    axis_labels={"A": "abundance", "B": "tumor-elevation", "C": "malignant-intrinsic", "D": "generality"},
    scope_exclusions=("therapeutic modality", "surface accessibility",
                      "the normal-tissue-liability VERDICT (owned by tumor-selectivity / on-target-safety) — "
                      "note the hand-off but do not make the window call"),
    # NARRATOR RULE: lead with malignant-cell-PROTEIN-CONFIRMED vs bulk-RNA/cell-line-ANNOTATED presence,
    # then the compartment confound, then present-vs-tumor-elevated — the three things the one-word
    # collapsed verdict hides — with the window/surface/safety verdicts as breadcrumbs.
    polarity_note=(
        "LEAD by stating whether the presence is CONFIRMED at the MALIGNANT-CELL PROTEIN level — CPTAC or "
        "cell-line-MS protein (or HPA-IHC) PLUS a single-cell malignant-compartment attribution "
        "(read presence_confirmation_caveat + presence_provenance.malignant_protein_confirmed) — or "
        "whether it rests only on BULK RNA / a pan-cancer CELL-LINE annotation (RNA≠protein; cell-line "
        "de-differentiation vs tumor tissue) or a STROMAL/immune compartment (the FAP/CAF pattern: bulk "
        "cannot separate malignant cells from stromal/immune admixture — single-cell/spatial is decisive; "
        "read compartment_note). A `malignant_compartment_unconfirmed` caveat means the bulk signal is a "
        "microenvironment (stromal/immune) read, NOT malignant-cell presence, EVEN IF bulk protein is "
        "detected (stromal protein is still protein). Then distinguish PRESENT from tumor-ELEVATED: a "
        "ubiquitous/housekeeping level (GAPDH-class) reads present but is uninformative for relevance — "
        "the tumor-elevation/window call is owned by tumor-selectivity (breadcrumb). Do NOT over-demote a "
        "protein-CONFIRMED or clinically-precedented antigen: an abundance-floor MS artifact "
        "(`protein_confirmed_malignant_present`/`clinically_precedented_antigen_present`, e.g. a GPI-"
        "anchored antigen the Gygi TMT panel under-reads but ProCan/IHC recover) is NOT an over-call. "
        "Surface accessibility (surface-modality-fit) and normal-tissue safety severity (on-target-"
        "safety) are breadcrumbs, never the presence call."),
    mode="verdict",
    verdict_key="presence_verdict",   # the collapsed word lives here (was mis-read as driving_rule_id)
)

TUMOR_SELECTIVITY = LensConfig(
    name="tumor-selectivity",
    thesis="whether the target is TUMOR-SELECTIVE enough to open a therapeutic window (tumor-enriched vs "
           "normal tissue), the decisive axis being the normal-tissue comparator — and, critically, whether "
           "that window is CORROBORATED across independent platforms (bulk-RNA comparators, tumor-vs-normal "
           "PROTEIN by CPTAC/TPHP mass-spec, and in-situ SPATIAL region-RNA) or is only a HIGH-NORMAL-"
           "BASELINE FIELD EFFECT (tumor≈adjacent-normal but tumor>distant-normal — a genuine but NARROW window).",
    relevance_prompt="judge the tumor-selectivity / therapeutic-window support for this target.",
    axis_labels={"WIN": "therapeutic window", "DIST": "normal-tissue distribution",
                 "INT": "tumor-intrinsic", "SAFE": "safety"},
    scope_exclusions=("absolute abundance as presence", "therapeutic modality",
                      "on-target safety severity / nomination call"),
    # NARRATOR RULE: lead with cross-platform corroboration of the window, then the field-effect vs
    # wide-window distinction, then the normal-tissue liability — the three things the RNA-only class hides.
    polarity_note=("LEAD by stating whether INDEPENDENT platforms corroborate the RNA tumor-vs-normal "
                   "window: name the PROTEIN-layer (CPTAC/TPHP MS) and in-situ SPATIAL agreement or "
                   "disagreement explicitly, and distinguish a high-normal-baseline FIELD EFFECT "
                   "(adjacent-normal flat/down, distant-normal up) from a broadly wide window. A "
                   "critical-organ normal-tissue liability (SAFE negative) NARROWS the window regardless "
                   "of tumor-side signal strength — never let a strong tumor-side signal mask it."),
    mode="verdict",
    verdict_key="selectivity_class",   # the RESOLVED (post-veto) class token; else the collapsed-verdict
                                       # prompt line fell through to driving_rule_id (a rule-id string),
                                       # e.g. "tvn-...-veto" — mirrors the TUMOR_PRESENCE fix.
)

GENOMIC_ALTERATION = LensConfig(
    name="genomic-alteration-profile",
    thesis="HOW the target is genomically altered (SNV/indel, copy-number, fusion, or a mix), which "
           "alteration CLASS carries the signal (not a single 'is it a driver' call), and the variant-level "
           "clinical interpretation of the target's own alterations — oncogenicity and any CIViC-annotated "
           "THERAPY-RESISTANCE alleles (e.g. a mutation that is a negative predictive biomarker for a "
           "targeted agent), surfaced in the DEP claim's actionability read.",
    relevance_prompt="judge how the genomic-alteration evidence supports this target, naming which class "
                     "drives and surfacing any variant-level therapy-resistance actionability.",
    axis_labels={"SNV": "SNV/indel", "CN": "copy-number", "FUS": "fusion",
                 "SPL": "splice exon-skip", "DEP": "alteration-conferred dependency"},
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
           "or neither — from topology, surfaceome family, density, and normal-tissue/shedding liabilities, "
           "WHILE distinguishing a CONFIRMED cell-surface protein (measured surface proteomics / IHC / flow + "
           "measured or clinically-precedented internalization) from a target that merely reads surface-"
           "accessible off surfaceome-FAMILY membership or an RNA/predicted-topology prior WITHOUT confirmed "
           "cell-surface protein (the surface annotation-INFLATION trap), and flagging a SHED ectodomain "
           "(soluble-antigen sink) that can make a surface-abundant antigen a poor ADC/TCE substrate.",
    relevance_prompt="judge the biologics surface-modality fit (ADC / TCE / both / neither), and whether the "
                     "surface call rests on CONFIRMED cell-surface protein or only on family/RNA annotation.",
    axis_labels={"FIT": "modality fit", "TOPOLOGY": "topology/accessibility", "DENSITY": "surface density",
                 "SAFETY": "normal-tissue safety", "SHED": "shedding"},
    scope_exclusions=("small-molecule tractability (tractability-small-molecule)", "intracellular mechanism",
                      "expression-as-presence (tumor-presence)", "safety severity (on-target-safety)"),
    # NARRATOR RULE: lead with whether the surface call is CONFIRMED (measured cell-surface protein +
    # internalization) or rests on family/RNA/topology ANNOTATION; then the shed soluble-sink caveat; then
    # the normal-tissue-surface TCE veto and the ADC-vs-TCE split — the confirmed-vs-annotated distinction a
    # one-word fit_class hides.
    polarity_note=(
        "signal = strength of the evidence FOR a viable biologics surface modality. LEAD by stating whether "
        "the surface accessibility call is CONFIRMED or only ANNOTATED: fit_class (ADC_preferred / "
        "TCE_preferred / both_viable) is composed from surfaceome-FAMILY membership + sequence-PREDICTED "
        "topology ONLY — it does NOT consume measured cell-surface protein (CSPA/HPA-IF surface_confirmation_"
        "class), antigen DENSITY, or MEASURED internalization. So a positive fit_class can rest on family/RNA "
        "annotation while the protein/spatial evidence does NOT confirm it. When surface_confirmation_caveat "
        "is present, report the positive call as looks-surface-accessible-but-UNCONFIRMED (reason "
        "family_topology_annotation_unconfirmed = NO confirmed surface protein AND no clinical biologics "
        "precedent — a genuine over-call, the LGR5/GPCR-family pattern; reason "
        "clinically_precedented_cspa_unconfirmed = a validated antigen a cell-line surface-proteomics panel "
        "simply missed — NOT an over-call). Treat surface_confirmation_class ∈ {confirmed_high, confirmed} or "
        "surface_multimodal_support=corroborated_surface as the strongest presence signal (measured protein, "
        "not an RNA/family proxy). For an ADC call, internalization is the payload-delivery requirement: "
        "endocytosis_confidence=clinically_internalizing is a curated regulatory FACT, a measured motif is "
        "high/moderate/low, and `unmeasured` is an honest gap (ADC-favorability then rests on topology alone "
        "— say so). Flag a SHED ectodomain (shed_caveat / shed_liability_class ∈ {clinically_shed, "
        "secretome_proxy_shed}, or a measured media_shed_high) as a soluble-antigen sink that neutralizes "
        "ADC/TCE binders — a surface-abundant antigen can still be a caveated substrate needing a "
        "shed-resistant epitope (a caveat, not a veto; approved ADCs exist against shed antigens). The TCE "
        "arm is the safety-fragile one: a normal-tissue-surface liability (essential-normal-tissue / "
        "sc-normal HIGH_LIABILITY / essential-window) is a bite_tce VETO but PRESERVES ADC (bystander "
        "buffer), and within-tumor antigen-escape forecloses TCE efficacy while ADC tolerates heterogeneity "
        "— so read the ADC-vs-TCE split, not a blanket call. Density below the soluble-TCE floor is a "
        "DOWNGRADE not a veto (CD19 is a validated low-density antigen). Small-molecule tractability, "
        "genetic-dependency magnitude, expression-as-presence, and safety SEVERITY are verdict-inert "
        "breadcrumbs here — hand off to tractability-small-molecule, functional-requirement, tumor-presence, "
        "and on-target-safety."),
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
    thesis="whether the target looks druggable by a SMALL MOLECULE — is there a compound that DIRECTLY "
           "engages it (with measured binding potency + cellular activity), does that chemical signal AGREE "
           "with the genetic dependency (chemical-genetic concordance = on-target; discordant = off-target), "
           "and is there a ligandable POCKET even absent a known compound — WHILE distinguishing a direct "
           "target-engaging compound from an INDIRECT / pathway / downstream compound merely tabulated "
           "against the gene by DGIdb/ChEMBL (the druggability-inflation trap that makes an undruggable TF/"
           "scaffold read druggable off raw interaction counts).",
    relevance_prompt="judge the small-molecule tractability (DIRECT chemical engagement + structural "
                     "ligandability), and whether the chemical signal agrees with the genetic dependency.",
    axis_labels={"POTENCY": "binding potency", "ACTIVITY": "cellular activity", "STRUCT": "structural ligandability",
                 "DRUG": "drug/tool compound", "DEGRADER": "degrader handle"},
    scope_exclusions=("biologics/surface modality (surface-modality-fit)", "expression as presence",
                      "genetic-dependency magnitude (functional-requirement)"),
    # NARRATOR RULE: lead with DIRECT engagement + chemical-genetic agreement, then the DGIdb/ChEMBL
    # inflation caveat, then structural ligandability — the direct-vs-indirect distinction a one-word
    # verdict hides.
    polarity_note=(
        "signal = strength of the evidence FOR small-molecule druggability. LEAD by stating whether there "
        "is a DIRECT target-engaging compound — a measured binder (POTENCY) that also shows MEASURED "
        "cellular activity (ACTIVITY = clinically_active, not merely a tool/annotation) — and whether that "
        "chemical activity AGREES with the genetic dependency: chemical-genetic concordance = "
        "triangulated/crispr_confirmed is on-target CORROBORATION, discordant_off_target_likely is a "
        "CONFLICT that argues AGAINST tractability, thin/unmeasured leaves engagement uncorroborated (read "
        "chemical_genetic_agreement). CRITICALLY, do NOT over-read a DGIdb known-drug / druggable-category "
        "boolean or a ChEMBL gene-aggregated potent-ligand/approved-phase count as DIRECT engagement: those "
        "tabulate a compound AGAINST THE GENE and are indirect-inclusive (pathway / downstream / off-target "
        "compounds, even assay dyes, antibodies, or PPI-interface-tabulated ligands) — when directness_caveat "
        "is present the positive snapshot rests on annotation WITHOUT a measured cellular hit or "
        "chemical-genetic agreement, so report it as looks-druggable-but-UNCONFIRMED, not confirmed direct "
        "druggability (the β-catenin/MYC undruggable-TF inflation pattern). Treat STRUCT as a FORWARD handle: "
        "a real ligandable pocket (experimental co-crystal, hotspot-in-pocket) is a positive prospect even "
        "before a compound exists (the KRAS-G12C switch-II archetype), but bulk PDB/structure COVERAGE is "
        "not pocket tractability (a flat PPI-groove target scores high coverage with no druggable pocket) "
        "and measured disorder is SM-opposing. Degrader feasibility and biologics/surface routes are a "
        "verdict-inert breadcrumb here — hand off to functional-requirement (degrader efficacy / paralog) "
        "and surface-modality-fit (biologics)."),
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
    # The collapsed-verdict line reads the RESOLVED differentiation token (both_patterns_present /
    # strong_cooccurring / strong_mutually_exclusive / …) from this declared headline key. Without it,
    # the fallback's legacy `<name>_verdict` guess ("differentiation-landscape" →
    # "differentiation_landscape_verdict") MISSES the real key `differentiation_verdict` and the line
    # fell through to `driving_rule_id` — handing the narrator a rule-id string (e.g.
    # `cooccurrence-both-patterns-supportive`) as the one-word verdict. Same guess-misses failure the
    # surface/genomic/tractability/mechanism lenses fixed; differentiation was the last verdict-carrying
    # lens still relying on the (broken) guess.
    verdict_key="differentiation_verdict",
)

MECHANISM_PHARMACOLOGY = LensConfig(
    name="mechanism-and-pharmacology",
    thesis="the signaling-network mechanism + candidate MoA hooks + PD-marker suggestions — how well the "
           "target's mechanism is characterized and what it implies for SM/degrader/glue programs, WHILE "
           "distinguishing an INDICATION-OPERATIVE, functionally-validated mechanism from a CONTEXT-FREE "
           "CURATED edge aggregate (a curated SIGNOR/Reactome/CollecTRI edge is tissue-agnostic — its "
           "presence does NOT prove the MoA DRIVES this indication), and flagging when has_actionable_moa "
           "rests on a generic curated edge or a low-weighted PREDICTION lane (kinome-atlas / co-essentiality) "
           "rather than a curated-and-validated, directly-druggable mechanism (the actionable-MoA "
           "annotation-INFLATION trap).",
    relevance_prompt="give the mechanism / MoA-hook context read for this target (descriptive; no nomination "
                     "call), separating an indication-operative validated mechanism from a context-free "
                     "curated / prediction-lane aggregate.",
    axis_labels={"NETWORK": "signaling network", "PHOSPHO": "phospho activity", "PATHWAY": "pathway activity",
                 "PERTURBATION": "drug-perturbation MoA", "PREDICTABILITY": "dependency predictability"},
    scope_exclusions=("nomination verdict", "therapeutic modality selection",
                      "small-molecule directness (tractability-small-molecule)"),
    # NARRATOR RULE: lead with curated-vs-operative + curated-vs-predicted PROVENANCE and the actionable-MoA
    # inflation caveat — the annotation-density / context-free distinction the one-word network_class hides.
    polarity_note=(
        "This lens is DESCRIPTIVE: network_class is ANNOTATION DENSITY (curated edge COUNT = curation depth, "
        "NOT target quality — capped at moderate) and every verdict rung is neutral. LEAD by separating an "
        "INDICATION-OPERATIVE, functionally-validated mechanism from a CONTEXT-FREE CURATED aggregate: a "
        "curated SIGNOR/Reactome/CollecTRI edge is a tissue-agnostic literature record, so a rich "
        "network_class or a has_actionable_moa=True can reflect curation depth, not a mechanism that DRIVES "
        "this indication. has_actionable_moa is composed as (>=1 curated upstream edge), so it fires for a "
        "validated-drugged kinase (BRAF/EGFR) AND an undruggable pleiotropic hub / metabolic enzyme "
        "(MYC/MTAP) alike — when mechanism_confirmation_caveat is present, report the actionable-MoA call as "
        "looks-actionable-but-UNVALIDATED (reason actionable_moa_curated_context_free_unvalidated[_thin_"
        "network] = a generic curated edge with no validated direct hook, the MYC pattern; reason "
        "actionable_moa_curated_clinically_precedented = a target with an approved directly-acting agent, "
        "NOT an over-call — do NOT demote it). Treat the kinome-atlas PREDICTION lane and DepMap "
        "co-essentiality lane (prediction_lane_caveat) as carried ALONGSIDE but NEVER merged into "
        "network_class/has_actionable_moa — a predicted or correlational edge alone must not lift the "
        "actionable-MoA call. When curation_gap_note is present, a thin network_class co-occurs with an "
        "operative signal (phospho-activity / PROGENy pathway activity / drug-perturbation / co-essentiality) "
        "the context-free curation under-reads — read it as a possible curation gap (e.g. a fusion-rewired "
        "driver), not proof of no mechanism. PHOSPHO (measured activation beyond abundance) is the one "
        "decision-grade positive signal. Small-molecule DIRECTNESS, dependency magnitude, and modality "
        "selection are verdict-inert breadcrumbs — hand off to tractability-small-molecule, "
        "functional-requirement, and surface-modality-fit."),
    mode="descriptive",
    # DESCRIPTIVE mode still builds a COLLAPSED VERDICT prompt line, and mechanism-and-pharmacology DOES emit
    # a resolved token (`mechanism_verdict`: well_characterized / partial / sparse / has_pd_marker / …) — so it
    # needs a verdict_key like the verdict-mode lenses (only combination-and-vulnerability / target-intrinsic
    # are truly TOKENLESS descriptive lenses; cis-feature-coherence looks descriptive but ALSO emits a resolved
    # token — `cis_coherence_verdict` — and carries its own verdict_key below). Without a declared verdict_key
    # the fallback lands on the legacy `<name>_verdict` guess ("mechanism_and_pharmacology_verdict"), which
    # MISSES the real headline key `mechanism_verdict` (top-level decision["verdict"] is None here), then falls
    # through to driving_rule_id — a rule-id string ("mechanism-well-characterized-supportive") that the LLM was
    # observed to echo verbatim into user-facing prose. Declaring the key hands the narrator the resolved token
    # instead. This is the surface/genomic/tractability "guess MISSES the key" class (not the immune-context
    # coincidence). Verdict-INERT.
    verdict_key="mechanism_verdict",
)

CIS_FEATURE_COHERENCE = LensConfig(
    name="cis-feature-coherence",
    thesis="whether the locus→expression→dependency chain is COHERENT (cis copy-number dosage coupling, "
           "methylation silencing, expression↔dependency) — a data-integrity / mechanism-plausibility context.",
    relevance_prompt="give the cis-feature-coherence context read (descriptive; no nomination call).",
    axis_labels={"CIS_DOSAGE": "cis copy-number dosage", "SILENCING": "methylation silencing",
                 "EXPR_DEP": "expression↔dependency", "CONJOINT": "amp∩overexpr addiction"},
    scope_exclusions=("nomination verdict",),
    mode="descriptive",
    # DESCRIPTIVE mode STILL builds a COLLAPSED VERDICT prompt line, and — unlike combination-and-vulnerability
    # / target-intrinsic (truly tokenless) — this skill supplies verdict_fn=_verdict and emits a RESOLVED token
    # `cis_coherence_verdict` (coherent_cis_driver / coherent_epigenetic_silencing / expressed_cis_coupled_inert
    # / dependency_without_cis_dosage / cis_uncoupled_no_dependency / insufficient_cis_coherence) in the
    # headline; top-level decision["verdict"] is None (verdict-INERT at nomination — never a gate). Without a
    # declared verdict_key the fallback lands on the legacy `<name>_verdict` guess
    # ("cis_feature_coherence_verdict"), which MISSES the real headline key `cis_coherence_verdict`, then falls
    # through to driving_rule_id — a rule-id string ("cis-dosage-coupled-supportive" / "cis-silencing-coupled-
    # supportive" / "cis-dosage-uncoupled-neutral", confirmed live) that the LLM can echo verbatim into prose.
    # Declaring the key hands the narrator the resolved token instead. Mirrors the mechanism guess-misses fix;
    # cis-feature-coherence was the LAST verdict-carrying lens left without a verdict_key. Verdict-INERT.
    verdict_key="cis_coherence_verdict",
)

COMBINATION_VULNERABILITY = LensConfig(
    name="combination-and-vulnerability",
    thesis="the relational (gene×gene) opportunities — synthetic-lethal partners, measured dual-KO "
           "co-dependencies, combination co-targets under inhibition, and resistance mediators.",
    relevance_prompt="give the combination / vulnerability context read (descriptive ranked-partner annex; no nomination call).",
    axis_labels={"SL": "synthetic-lethal", "CODEP": "paralog dual-KO co-dependency",
                 "COMBO": "combination co-target", "SYNERGY": "chemical drug×drug synergy",
                 "RESISTANCE": "resistance mediators"},
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
