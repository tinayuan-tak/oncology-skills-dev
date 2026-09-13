"""narrator_lenses — per-skill LensConfig data for the generic narrator_engine.

Each skill's narration is expressed as data here (thesis, axis labels, scope guardrails, polarity, output
mode) instead of a bespoke synthesis_*.py module. Reference set: functional-requirement (verdict) +
on-target-safety-liability (verdict, polarity-inverted). All 16 lenses now live in the LENSES registry
below (the 14 hierarchy skills + target-archetype and literature-context). The curated-SL / paralog-dual-KO
relational signals are composed as CARDS under combination-and-vulnerability, not as standalone lenses.
"""

from __future__ import annotations

from _skills_common.narrator_engine import LensConfig

FUNCTIONAL_REQUIREMENT = LensConfig(
    name="functional-requirement",
    claim_spec_ref="dependency_claims:DEPENDENCY_CLAIM_SPEC",
    thesis="how much the DEPENDENCY lens informs whether the target is worth pursuing — a SELECTIVE genetic "
    "dependency supports it, a pan-essential read argues AGAINST (broad tox), non-dependent is "
    "uninformative — and, critically, whether the call is CORROBORATED across the independent "
    "perturbation channels (CRISPR-KO + RNAi + PRISM chemical-genetic + Broad↔Sanger cross-consortium) "
    "or rests on a single screen, and whether it is buffered by a redundant PARALOG (single-gene KO can "
    "under-call a real dependency).",
    relevance_prompt="judge how much the dependency lens supports pursuing this target in this indication; "
    "foreground the SELECTIVE-vs-PAN-ESSENTIAL distinction and any CRISPR/RNAi disagreement.",
    axis_labels={
        "DEP": "genetic dependency",
        "SEL": "context-selectivity",
        "COND": "conditional/SL",
        "CHEM": "chemical-genetic",
    },
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
        "absent; (3) the pooled verdict is TARGET-GRAIN, so when indication_scope_note is present READ THE "
        "NOTE — it does NOT always mean the dependency lies outside the queried indication. The note is "
        "keyed on the verdict's PROVENANCE and carries four distinct meanings: a LINEAGE-DERIVED verdict "
        "(lineage_selective) genuinely rests on a lineage contrast the queried indication lost, so report "
        "dependency_verdict_by_scope.indication instead of the target-grain token; a STRATIFIED verdict "
        "(partner_conditional_dependent) rests on a dependency inside a partner-deficient SUBSTRATUM and is "
        "scored against a POOLED indication median that DILUTES it, so a shallow indication median is NOT "
        "evidence the dependency lies elsewhere (WRN×MSI is a colorectal synthetic lethality whose pooled "
        "Bowel median is ~-0.14) — report the substratum, not the pooled median; a PANEL-MAGNITUDE verdict "
        "diverges from the indication read without an identified cause, so state the divergence and do not "
        "invent one; and an UNRESOLVED indication means NO indication-scoped read exists at all — there is "
        "no by_scope.indication answer to report, and the pooled verdict must not be passed off as one."
    ),
    mode="verdict",
    verdict_key="dependency_verdict",  # the RESOLVED dependency verdict token; else the collapsed-verdict
    # prompt line fell through to driving_rule_id (a rule-id string, e.g.
    # "lineage-selective-supportive") — mirrors the TUMOR_PRESENCE /
    # TUMOR_SELECTIVITY fix (the FR headline key is dependency_verdict).
)

ON_TARGET_SAFETY = LensConfig(
    name="on-target-safety-liability",
    claim_spec_ref="safety_claims:SAFETY_CLAIM_SPEC",
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
    # The full SAFETY_CLAIM_SPEC roster. Seven of the eight claim axes were off-roster while the thesis
    # above already enumerates every one of them (constraint, burden, dosage, ClinVar, mouse-KO,
    # pan-essentiality) — so this was an incomplete roster, not a scoped exclusion, and the literature
    # lane could only ever ask about pharmacovigilance. See test_lens_roster_covers_claim_axes.
    axis_labels={
        "CONSTRAINT": "gnomAD LoF constraint",
        "BURDEN": "population gene-burden",
        "DOSAGE": "ClinGen dosage sensitivity",
        "CLINVAR": "germline pathogenicity",
        "MOUSE_KO": "mouse-KO phenotype",
        "PAN_ESSENTIAL": "DepMap pan-essentiality",
        "NORMAL_TISSUE": "essential-tissue protein",
        "PHARMACOVIGILANCE": "on-target clinical pharmacovigilance",
    },
    scope_exclusions=("tumor presence/abundance", "efficacy", "modality choice beyond full-KO tolerability"),
    polarity_note="signal = strength of the LIABILITY. High gnomAD constraint, broad normal-tissue expression, "
    "germline pathogenicity, haploinsufficiency, and pan-essentiality are STRONG liability; a "
    "strongly_selective dependency is REASSURING (LOW broad-tox liability), not support. When a "
    "PHARMACOVIGILANCE signal is present, LEAD with the specific on-target clinical toxicity "
    "classes / boxed warnings — but treat it as CONFOUNDED CONTEXT (on- vs off-target cannot be "
    "separated; corroboration is capped): it orients, it is never itself the verdict.",
    relevance_enum=("high_liability", "moderate_liability_with_caveats", "low_liability", "insufficient_evidence"),
    mode="verdict",
    verdict_key="safety_verdict",  # the RESOLVED safety verdict token (run.py headline key); else the
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
    scope_exclusions=(
        "therapeutic modality",
        "surface accessibility",
        "the normal-tissue-liability VERDICT (owned by tumor-selectivity / on-target-safety) — "
        "note the hand-off but do not make the window call",
    ),
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
        "safety) are breadcrumbs, never the presence call."
    ),
    mode="verdict",
    verdict_key="presence_verdict",  # the collapsed word lives here (was mis-read as driving_rule_id)
)

TUMOR_SELECTIVITY = LensConfig(
    name="tumor-selectivity",
    claim_spec_ref="selectivity_claims:SELECTIVITY_CLAIM_SPEC",
    thesis="whether the target is TUMOR-SELECTIVE enough to open a therapeutic window (tumor-enriched vs "
    "normal tissue), the decisive axis being the normal-tissue comparator — and, critically, whether "
    "that window is CORROBORATED across independent platforms (bulk-RNA comparators, tumor-vs-normal "
    "PROTEIN by CPTAC/TPHP mass-spec, and in-situ SPATIAL region-RNA) or is only a HIGH-NORMAL-"
    "BASELINE FIELD EFFECT (tumor≈adjacent-normal but tumor>distant-normal — a genuine but NARROW window).",
    relevance_prompt="judge the tumor-selectivity / therapeutic-window support for this target.",
    axis_labels={
        "WIN": "therapeutic window",
        "DIST": "normal-tissue distribution",
        "INT": "tumor-intrinsic",
        "SAFE": "safety",
    },
    scope_exclusions=(
        "absolute abundance as presence",
        "therapeutic modality",
        "on-target safety severity / nomination call",
    ),
    # NARRATOR RULE: lead with cross-platform corroboration of the window, then the field-effect vs
    # wide-window distinction, then the normal-tissue liability — the three things the RNA-only class hides.
    polarity_note=(
        "LEAD by stating whether INDEPENDENT platforms corroborate the RNA tumor-vs-normal "
        "window: name the PROTEIN-layer (CPTAC/TPHP MS) and in-situ SPATIAL agreement or "
        "disagreement explicitly, and distinguish a high-normal-baseline FIELD EFFECT "
        "(adjacent-normal flat/down, distant-normal up) from a broadly wide window. A "
        "critical-organ normal-tissue liability (SAFE negative) NARROWS the window regardless "
        "of tumor-side signal strength — never let a strong tumor-side signal mask it."
    ),
    mode="verdict",
    verdict_key="selectivity_class",  # the RESOLVED (post-veto) class token; else the collapsed-verdict
    # prompt line fell through to driving_rule_id (a rule-id string),
    # e.g. "tvn-...-veto" — mirrors the TUMOR_PRESENCE fix.
)

GENOMIC_ALTERATION = LensConfig(
    name="genomic-alteration-profile",
    claim_spec_ref="genomic_claims:GENOMIC_CLAIM_SPEC",
    thesis="HOW the target is genomically altered (SNV/indel, copy-number, fusion, or a mix), which "
    "alteration CLASS carries the signal (not a single 'is it a driver' call), and the variant-level "
    "clinical interpretation of the target's own alterations — oncogenicity and any CIViC-annotated "
    "THERAPY-RESISTANCE alleles (e.g. a mutation that is a negative predictive biomarker for a "
    "targeted agent), surfaced in the DEP claim's actionability read.",
    relevance_prompt="judge how the genomic-alteration evidence supports this target, naming which class "
    "drives and surfacing any variant-level therapy-resistance actionability.",
    axis_labels={
        "SNV": "SNV/indel",
        "CN": "copy-number",
        "FUS": "fusion",
        "SPL": "splice exon-skip",
        "DEP": "alteration-conferred dependency",
        # ROLE was in GENOMIC_CLAIM_SPEC but absent here, so `axis_measured_state` (which iterates
        # axis_labels) never asked about it: 0 of 100 axis reads on the genomic-20 panel, which the
        # concordance ledger then read as 0 contradicts — i.e. agreement. An off-roster claim axis is
        # UNASKABLE, not agreed. See test_lens_roster_covers_claim_axes (eval CASE-034).
        "ROLE": "curated driver role",
    },
    scope_exclusions=("therapeutic modality", "expression as presence"),
    mode="verdict",
    verdict_key="genomic_alteration_profile",  # the RESOLVED multi-class verdict token (run.py headline
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
    claim_spec_ref="surface_claims:SURFACE_CLAIM_SPEC",
    thesis="whether the surface biology supports a BIOLOGICS modality — ADC-favorable, TCE-favorable, both, "
    "or neither — from topology, surfaceome family, density, and normal-tissue/shedding liabilities, "
    "WHILE distinguishing a CONFIRMED cell-surface protein (measured surface proteomics / IHC / flow + "
    "measured or clinically-precedented internalization) from a target that merely reads surface-"
    "accessible off surfaceome-FAMILY membership or an RNA/predicted-topology prior WITHOUT confirmed "
    "cell-surface protein (the surface annotation-INFLATION trap), and flagging a SHED ectodomain "
    "(soluble-antigen sink) that can make a surface-abundant antigen a poor ADC/TCE substrate.",
    relevance_prompt="judge the biologics surface-modality fit (ADC / TCE / both / neither), and whether the "
    "surface call rests on CONFIRMED cell-surface protein or only on family/RNA annotation.",
    axis_labels={
        "FIT": "modality fit",
        "TOPOLOGY": "topology/accessibility",
        "DENSITY": "surface density",
        "SAFETY": "normal-tissue safety",
        "SHED": "shedding",
        # PMHC was in SURFACE_CLAIM_SPEC but off-roster here — the one axis that can make an
        # INTRACELLULAR target a TCE target, so leaving it unaskable biased the lane toward the
        # folded-surface ladder it exists to complement. See test_lens_roster_covers_claim_axes.
        "PMHC": "pMHC-TCE route",
    },
    scope_exclusions=(
        "small-molecule tractability (tractability-small-molecule)",
        "intracellular mechanism",
        "expression-as-presence (tumor-presence)",
        "safety severity (on-target-safety)",
    ),
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
        "and on-target-safety."
    ),
    mode="verdict",
    verdict_key="surface_modality_verdict",  # the RESOLVED surface-modality verdict token (run.py headline
    # key); else the collapsed-verdict fallback lands on the
    # <name>_verdict guess ("surface_modality_fit_verdict" — note
    # the extra "fit") which MISSES the real key, then on
    # driving_rule_id (a rule-id string). Mirrors the
    # presence/selectivity/safety/functional-requirement contract.
)

TRACTABILITY_SM = LensConfig(
    name="tractability-small-molecule",
    claim_spec_ref="tractability_claims:SMALL_MOLECULE_CLAIM_SPEC",
    thesis="whether the target looks druggable by a SMALL MOLECULE — is there a compound that DIRECTLY "
    "engages it (with measured binding potency + cellular activity), does that chemical signal AGREE "
    "with the genetic dependency (chemical-genetic concordance = on-target; discordant = off-target), "
    "and is there a ligandable POCKET even absent a known compound — WHILE distinguishing a direct "
    "target-engaging compound from an INDIRECT / pathway / downstream compound merely tabulated "
    "against the gene by DGIdb/ChEMBL (the druggability-inflation trap that makes an undruggable TF/"
    "scaffold read druggable off raw interaction counts).",
    relevance_prompt="judge the small-molecule tractability (DIRECT chemical engagement + structural "
    "ligandability), and whether the chemical signal agrees with the genetic dependency.",
    axis_labels={
        "POTENCY": "binding potency",
        "ACTIVITY": "cellular activity",
        "STRUCT": "structural ligandability",
        "DRUG": "drug/tool compound",
        "DEGRADER": "degrader handle",
    },
    scope_exclusions=(
        "biologics/surface modality (surface-modality-fit)",
        "expression as presence",
        "genetic-dependency magnitude (functional-requirement)",
    ),
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
        "and surface-modality-fit (biologics)."
    ),
    mode="verdict",
    verdict_key="druggability_snapshot",  # the headline key holding the resolved snapshot token
    # (NOT the legacy <name>_verdict guess, which would be
    # "tractability_small_molecule_verdict" and MISS it →
    # fall through to driving_rule_id, a rule-id string).
    # Mirrors presence/selectivity/FR/safety/surface/genomic;
    # tractability-small-molecule was the last one left behind.
)

IMMUNE_CONTEXT = LensConfig(
    name="immune-context",
    claim_spec_ref="immune_context_claims:IMMUNE_CONTEXT_CLAIM_SPEC",
    thesis="the immune/TME context for a T-cell-engager (TCE) effector arm — is the indication immune-HOT "
    "(a CD8 effector infiltrate to redirect) — WHILE distinguishing a SPATIALLY-CONFIRMED, functional "
    "INFLAMED infiltrate (tumor-nest CD8 — TCE-favorable) from a BULK-CIBERSORT-FRACTION-ANNOTATED CD8 "
    "read that a RELATIVE, reference-model-dependent, non-spatial, function-blind deconvolution CANNOT "
    "localize (inflamed vs immune-EXCLUDED stroma/margin vs DESERT) or verify as functional-vs-"
    "exhausted, and from a cohort-MEDIAN that hides per-patient heterogeneity (the bulk-CD8-fraction-"
    "over-calls-spatial-infiltration trap). The effector-arm companion to surface-modality-fit "
    "(antigen); a TCE needs BOTH.",
    relevance_prompt="judge whether there is a CD8 effector context to support a TCE effector arm, and "
    "whether an immune-hot/intermediate call is spatially/orthogonally CONFIRMED or rests "
    "only on a bulk CIBERSORT deconvolution fraction.",
    axis_labels={"IMMUNE": "CD8 / immune infiltration"},
    scope_exclusions=(
        "surface antigen accessibility (owned by surface-modality-fit)",
        "small-molecule tractability",
        "expression-as-presence (tumor-presence)",
        "genetic dependency (functional-requirement)",
    ),
    # NARRATOR RULE: lead with whether the immune-hot/intermediate call is SPATIALLY-CONFIRMED (or at least
    # orthogonally corroborated by the absolute H&E-DL TIL) or rests only on a bulk CIBERSORT FRACTION; then
    # the inflamed-vs-excluded-vs-desert localization caveat + the presence-vs-exhaustion caveat; then the
    # immune-cold effector-absence efficacy risk and the cohort-median heterogeneity caveat.
    polarity_note=(
        "signal = strength of the evidence FOR a CD8 effector context to support a TCE. LEAD by stating "
        "whether the immune-hot / immune-intermediate call is SPATIALLY-CONFIRMED (or at least orthogonally "
        "corroborated) or rests ONLY on a bulk CIBERSORT deconvolution FRACTION: immune_context_class / "
        "immune_context_verdict come from the indication's MEDIAN CD8 T-cell SHARE of the leukocyte "
        "compartment (CIBERSORT LM22) — a RELATIVE, reference-model-dependent, NON-SPATIAL, FUNCTION-BLIND "
        "estimate. So a positive read can rest on a bulk fraction while spatial localization + CD8 function "
        "are UNCONFIRMED. When immune_confirmation_caveat is present, report the positive call accordingly: "
        "reason bulk_fraction_til_discordant = the orthogonal absolute H&E-DL TIL (Saltz) CONTRADICTS the "
        "CD8 share (CD8-rich share but low absolute lymphocyte density — the PRAD over-call, the sharpest); "
        "reason bulk_fraction_spatially_unconfirmed = a positive read with NO orthogonal absolute-TIL check "
        "→ looks-hot-but-SPATIALLY-UNCONFIRMED (the immune-EXCLUDED / desert risk); reason "
        "orthogonally_corroborated = an independent morphology platform AGREES the tumor is infiltrated (NOT "
        "an over-call — do NOT demote a genuinely-inflamed, ICI-validated indication like melanoma / MSI-H). "
        "ALWAYS surface spatial_localization_caveat: a bulk fraction reports the SHARE, not the LOCALIZATION "
        "— it cannot separate an INFLAMED tumor (tumor-nest CD8, TCE-favorable) from an IMMUNE-EXCLUDED one "
        "(CD8 trapped in peritumoral stroma / at the invasive margin, TCE-UNfavorable) from a DESERT, and it "
        "cannot separate a functional from an EXHAUSTED / dysfunctional infiltrate that reads hot but is not "
        "cytotoxically effective (the ccRCC/KIRC high-fraction-but-exhausted paradox). Treat "
        "til_cibersort_agreement=True (absolute H&E-DL TIL corroborates) as the strongest available presence "
        "corroboration (measured morphology, orthogonal to RNA deconvolution); immune_provenance summarizes "
        "the bulk-CIBERSORT-vs-absolute-TIL quorum — confirmed_tumor_nest_infiltration is NEVER True from "
        "bulk alone. An immune_COLD read is a MEASURED effector-absence = a TCE-EFFICACY risk (no effector "
        "pool to redirect), NOT a target veto and NOT a surface/antigen problem (CIBERSORT is relative + "
        "non-spatial); a cohort-MEDIAN also hides per-patient heterogeneity (the antigen-conditioned "
        "per-patient join is a deferred v2 facet). Surface antigen accessibility, small-molecule "
        "tractability, dependency, and expression are verdict-inert breadcrumbs — hand off to "
        "surface-modality-fit (the antigen arm this effector arm composes with), tractability-small-molecule, "
        "functional-requirement, and tumor-presence."
    ),
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
    claim_spec_ref="differentiation_claims:DIFFERENTIATION_CLAIM_SPEC",
    thesis="what patient-selection / combination-biology hypotheses the co-mutation, stemness, node-leverage "
    "and prognostic landscape support for this target, WHILE distinguishing a BIOLOGICALLY-ESTABLISHED "
    "co-mutation / mutual-exclusivity relationship (shared pathway, functional cooperation, a validated "
    "patient-selection biomarker) from a STATISTICALLY-significant-but-CONFOUNDED association — the "
    "panel-intersect Fisher scan carries no TMB / MSI / molecular-subtype covariate, so a q-significant "
    "pair can be a mutation-BURDEN (MSI-H / hypermutation) passenger co-occurrence, a lineage/subtype "
    "restriction, a near-universal-driver marginal-frequency artifact, or a tiny-effect / panel-"
    "ineligible pair rather than a biological interaction (the co-mutation over-calls-biology trap).",
    relevance_prompt="judge how the differentiation-landscape evidence informs patient-selection / positioning, "
    "separating a biologically-established co-mutation / exclusivity from a statistically-"
    "significant-but-TMB/lineage-confounded association.",
    axis_labels={
        "COMUT": "co-mutation / mutual-exclusivity",
        "SURVIVAL": "subtype survival",
        "PROGNOSIS": "prognostic association",
        "NODE": "pathway node-leverage",
    },
    scope_exclusions=(
        "therapeutic modality",
        "dependency magnitude (owned by functional-requirement)",
        "synthetic-lethal / dependency call (functional-requirement + combination-and-vulnerability)",
        "therapeutic-window / normal-tissue safety (tumor-selectivity + on-target-safety)",
    ),
    # NARRATOR RULE: lead with biologically-ESTABLISHED vs statistically-significant-but-CONFOUNDED, name the
    # TMB/MSI + subtype + panel-eligibility confounders and effect-size-vs-significance, hand off SL/window.
    polarity_note=(
        "LEAD by separating a BIOLOGICALLY-ESTABLISHED co-mutation / mutual-exclusivity relationship from a "
        "STATISTICALLY-significant-but-CONFOUNDED association. A pooled panel-intersect Fisher pair carries NO "
        "TMB / MSI / molecular-subtype covariate, so a q-significant hit is NOT proof of a pairwise biological "
        "interaction: in MSI-H / POLE / hypermutated tumors (BRAF-V600E CRC is CIMP-high / MLH1-methylated / "
        "MSI-H) two genes co-occur simply because both are frequent passengers at high mutation burden (DISCOVER: "
        "chance explains most co-occurrence); a mutual-exclusivity can reflect lineage/subtype restriction "
        "(CMS/CIMP strata) rather than same-pathway redundancy; and a near-universal driver (TP53) co-occurs "
        "with a long tail as a marginal-frequency consequence. When cooccurrence_confidence_caveat is present, "
        "report the pattern accordingly: reason cooccurrence_tmb_or_lineage_confounded = a burden/lineage-driven "
        "co-occurrence HUB (statistically-real, biologically-UNCONFIRMED — the actionable axis may be MSI/dMMR, "
        "not the co-mutation); reason significant_but_near_universal / significant_but_low_effect_or_panel_"
        "ineligible = significance ≠ actionability (near-universal driver, tiny effect size, or a panel-absent "
        "per-source-only pair with no pooled claim); reason biologically_established_pattern = a canonical "
        "same-pathway relationship (KRAS/NRAS/BRAF MAPK mutual-exclusivity, one activating hit sufficient; a "
        "validated anti-EGFR negative-predictor) — NOT an over-call, do NOT demote it. Weigh EFFECT SIZE "
        "(log2_odds_ratio) + panel-eligibility (pooled_eligible) alongside q-value: a q-significant, "
        "near-unity-OR pair is not a combination / patient-selection hypothesis. CLONALITY: a pooled bulk "
        "co-occurrence is COHORT-level (same PATIENT / sample), NOT same-cell / clonal — bulk TCGA-MC3 + GENIE "
        "cannot resolve whether the two alterations share a clone or sit in separate subclones / branched "
        "lineages (subclonal / parallel evolution; Gerlinger 2012, McGranahan & Swanton 2017), so a "
        "co-occurrence is a patient-level association, not a same-cell co-driver claim (clonality_caveat). The "
        "DIRECTION (co-occurring "
        "vs mutually-exclusive; worse vs better survival) is a pattern TYPE, not good/bad — every verdict is "
        "neutral. The dependency / synthetic-lethal call is owned by functional-requirement + "
        "combination-and-vulnerability, and the therapeutic-window / safety call by tumor-selectivity + "
        "on-target-safety — verdict-inert breadcrumbs here."
    ),
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
    claim_spec_ref="mechanism_claims:MECHANISM_CLAIM_SPEC",
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
    axis_labels={
        "NETWORK": "signaling network",
        "PHOSPHO": "phospho activity",
        "PATHWAY": "pathway activity",
        "PERTURBATION": "drug-perturbation MoA",
        "PREDICTABILITY": "dependency predictability",
    },
    scope_exclusions=(
        "nomination verdict",
        "therapeutic modality selection",
        "small-molecule directness (tractability-small-molecule)",
    ),
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
        "functional-requirement, and surface-modality-fit."
    ),
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
    claim_spec_ref="cis_coherence_claims:CIS_COHERENCE_CLAIM_SPEC",
    thesis="whether the locus→expression→dependency chain is COHERENT (cis copy-number dosage coupling at "
    "BOTH mRNA and PROTEIN, methylation silencing, expression↔dependency, conjoint amp∩overexpr "
    "addiction) — a data-integrity / mechanism-plausibility context, WHILE distinguishing a CAUSAL, "
    "dosage-driven, functionally-validated cis-DRIVER / TARGETED epigenetic silencing from a merely "
    "STATISTICALLY-correlated chain: a CN↔mRNA cis-coupling can be a CO-AMPLIFIED PASSENGER bystander "
    "in a focal driver amplicon (a gene FLANKING the real driver — a 17q12 ERBB2 neighbour "
    "GRB7/STARD3/MIEN1, an 8q24 MYC neighbour, an 11q13 CCND1 neighbour: dosage-coupled at mRNA but "
    "dosage-BUFFERED at protein), and a methylation↔low-expression correlation can be a CIMP / global-"
    "hypermethylation LINEAGE passenger rather than a targeted silencing of THIS gene (the cis-"
    "correlation-over-calls-a-causal-cis-driver trap).",
    relevance_prompt="give the cis-feature-coherence context read (descriptive; no nomination call), separating "
    "a causal-validated cis-driver / targeted-silencing from a statistically-correlated / "
    "co-amplified-passenger / dosage-buffered / CIMP-confounded chain.",
    axis_labels={
        "CIS_DOSAGE": "cis copy-number dosage",
        "SILENCING": "methylation silencing",
        "EXPR_DEP": "expression↔dependency",
        "CONJOINT": "amp∩overexpr addiction",
    },
    scope_exclusions=(
        "nomination verdict",
        "copy-number / amplification FREQUENCY + alteration CLASS (genomic-alteration-profile)",
        "single-target dependency MAGNITUDE (functional-requirement)",
        "expression / abundance PRESENCE claim (tumor-presence)",
    ),
    # NARRATOR RULE: lead with causal-validated cis-driver / targeted-silencing vs statistically-correlated /
    # co-amplified-passenger / dosage-buffered / CIMP-confounded, weigh the mRNA-vs-protein dosage SLOPE RATIO,
    # and breadcrumb the frequency / magnitude / presence hand-offs.
    polarity_note=(
        "LEAD by separating a CAUSAL, dosage-driven, functionally-validated cis-DRIVER / TARGETED epigenetic "
        "silencing from a merely STATISTICALLY-correlated chain. A CN↔mRNA cis-coupling is CORRELATIONAL, not a "
        "causal mediation test: it can be a CO-AMPLIFIED PASSENGER bystander in a focal driver amplicon (a gene "
        "flanking the real driver — GRB7/STARD3/MIEN1 on 17q12/ERBB2, an 8q24/MYC or 11q13/CCND1 neighbour), "
        "dosage-coupled at mRNA yet a passenger. The BUILT-IN discriminator is the mRNA-vs-protein dosage SLOPE "
        "RATIO: a genuine cis-driver is dosage-SENSITIVE at the PROTEIN level (protein scales with CN, ERBB2-like; "
        "Gonçalves 2017), whereas a co-amplified passenger is dosage-BUFFERED (mRNA up, protein flat) — so a "
        "coherent_cis_driver resting on an mRNA-only slope with a BUFFERED / uncoupled protein slope is the "
        "over-call. A methylation↔low-expression silencing can likewise be a CIMP / global-hypermethylation "
        "LINEAGE passenger (BRAF-CIMP colorectal, IDH-G-CIMP glioma) or a consequence of pre-existing lineage "
        "repression, not a targeted silencing of THIS gene — but CIMP membership does NOT auto-demote a locus "
        "with independent functional causality (MLH1 is BOTH CIMP-associated AND a validated biallelic MSI "
        "driver). When cis_coherence_confidence_caveat is present, report accordingly: reason "
        "statistical_cis_correlation_causally_unconfirmed = a coherence call resting on a correlation without "
        "causal / protein-dosage / patient confirmation; reason amplicon_passenger_or_lineage_confounded = a "
        "dosage-BUFFERED protein slope in a focal amplicon (co-amplified passenger) OR a CIMP-lineage / bulk-"
        "purity methylation confound; reason validated_cis_driver_or_silencing = a canonical validated cis-driver "
        "(ERBB2/MYCN/MDM2/CCND1 amp) or targeted silencing (MLH1/MGMT/CDKN2A) — NOT an over-call, do NOT demote "
        "it even if its protein slope reads buffered. COHERENCE ≠ ACTIONABILITY: a coherent chain is a mechanism-"
        "plausibility signal, not a druggability or nomination call (a coherent chain for a passenger is still a "
        "passenger; CCND1-amp is a real 11q13 focal driver yet CDK4/6i benefit is NOT CCND1-amp-selected). "
        "BULK / CELL-LINE generalization: the CN↔expr and expr↔dependency legs are bulk / immortalized-2D-"
        "DepMap reads — a bulk CN↔expr correlation can be tumor-purity / whole-segment-CN driven, and cell-line "
        "coherence is necessary but not sufficient for a patient cis-driver claim; the patient-cis-coherence "
        "facet is the corroboration (context_generalization_caveat). The alteration FREQUENCY + class is owned "
        "by genomic-alteration-profile, the dependency MAGNITUDE by functional-requirement, and the "
        "expression/abundance PRESENCE by tumor-presence — verdict-inert breadcrumbs here. Every coherence class "
        "is a DESCRIPTIVE pattern, not a drug call; this lens never mints or moves a nomination. "
        "DIRECTION IS PART OF THE CLAIM (cis-dosage card v1.1.0): cis_dosage_direction says WHICH CN arm carries "
        "the coupling, and the two readings are different biology, not two shades of one. amplification_coupled "
        "= gain drives expression UP (the oncogene/amplicon reading; supports a direct-inhibition thesis). "
        "deletion_coupled = loss drives expression DOWN, which is a LOSS-of-function statement — a synthetic-"
        "lethal / re-expression / loss-biomarker hypothesis, NOT a reason to inhibit the target, and the "
        "coherent_cis_loss_of_function verdict must never be narrated as a driver signal. Never say "
        "'amplification-driven' for a deletion_coupled target. When cis_dosage_direction_basis is "
        "cn_distribution_asymmetry, NEITHER CN arm was powered enough to set the direction and it was inferred "
        "from which CN tail is longer — weak evidence: report the direction as provisional and quote the arm "
        "deltas. LINEAGE-CONFOUNDED SILENCING is a THIRD state, not a negative: methylation_silencing_class = "
        "silencing_lineage_confounded means a large, significant hypermethylated-vs-rest contrast COLLAPSED once "
        "conditioned on lineage (lineage_collapse_ratio < 0.35) — the hypermethylated group was simply the "
        "lineages that do not express the gene. Narrate it as 'measured, and not interpretable as cis silencing' "
        "and do NOT narrate it either as silencing or as evidence AGAINST silencing: a within-lineage-powered "
        "test has not been run. Likewise distinguish methylation_uncoupled (TESTED, not silenced) from "
        "methylation_invariant_panel (untestable) — they are not interchangeable ways of saying 'no signal'."
    ),
    mode="descriptive",
    # DESCRIPTIVE mode STILL builds a COLLAPSED VERDICT prompt line, and — unlike combination-and-vulnerability
    # / target-intrinsic (truly tokenless) — this skill supplies verdict_fn=_verdict and emits a RESOLVED token
    # `cis_coherence_verdict` (coherent_cis_driver / coherent_epigenetic_silencing /
    # coherent_cis_loss_of_function / expressed_cis_coupled_inert / dependency_without_cis_dosage /
    # cis_uncoupled_no_dependency / insufficient_cis_coherence — resolver v1.3.0) in the
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
    claim_spec_ref="combination_vulnerability_claims:COMBINATION_VULNERABILITY_CLAIM_SPEC",
    thesis="the relational (gene×gene) opportunities — synthetic-lethal partners, measured dual-KO "
    "co-dependencies, combination co-targets that become MORE essential under inhibition, chemical "
    "drug×drug synergy, and resistance mediators that RESCUE — as a RANKED PARTNER TABLE, "
    "distinguishing a CLINICALLY / FUNCTIONALLY-VALIDATED, druggable relationship (BRCA↔PARP, "
    "WRN↔MSI, KRAS↔SHP2/SOS1) from a merely STATISTICAL relational signal (a curated SynLethDB edge, "
    "a DepMap co-essentiality delta, a paralog GI, a drug-anchor screen delta) that OVER-CALLS a "
    "portable, druggable synthetic lethality — a pan-essential co-fitness, a cell-line/lineage "
    "artifact, a non-replicating single-screen hit, or a genetic-KO SL whose partner is an "
    "undruggable scaffold (KO ≠ pharmacological inhibition).",
    relevance_prompt="give the combination / vulnerability context read (descriptive ranked-partner annex; "
    "no nomination call). Foreground whether the TOP-ranked partner is validated vs a "
    "statistical / cell-line / pan-essential over-call.",
    axis_labels={
        "SL": "synthetic-lethal",
        "CODEP": "paralog dual-KO co-dependency",
        "COMBO": "combination co-target",
        "SYNERGY": "chemical drug×drug synergy",
        "RESISTANCE": "resistance mediators",
    },
    scope_exclusions=(
        "single-target nomination verdict",
        "the single-target dependency MAGNITUDE (owned by functional-requirement)",
        "the druggability of a partner (owned by tractability-small-molecule / surface-modality-fit)",
    ),
    # NARRATOR RULE: this is a DESCRIPTIVE ranked-partner annex (gateless — no nomination call). LEAD by
    # separating a clinically/functionally-CORROBORATED partner from a statistically-ANNOTATED one, then
    # name the four inflation modes, with the dependency-magnitude + druggability hand-offs as breadcrumbs.
    polarity_note=(
        "This is a DESCRIPTIVE ranked-partner annex — there is NO nomination verdict; do NOT imply the "
        "relational signal nominates the target. LEAD by stating whether the TOP-ranked partner is "
        "CLINICALLY or FUNCTIONALLY VALIDATED (read partner_confirmation_caveat / combination_provenance: "
        "a clinically_or_functionally_validated_partner — BRCA↔PARP, WRN↔MSI-H, KRAS↔SHP2/SOS1 — is NOT an "
        "over-call and must not be demoted) or rests only on a STATISTICAL relational signal. Then name the "
        "four inflation modes the raw table cannot self-distinguish: (a) a curated SynLethDB edge / DepMap "
        "co-essentiality delta / paralog GI / drug-anchor delta can be a passenger co-fitness, a "
        "pan-essential co-dependency (ribosome/proteasome/spliceosome-class — a therapeutic-window problem, "
        "not a selective SL), or a non-replicating single-screen artifact (statistical_partner_functionally_"
        "unconfirmed / cell_line_context_or_pan_essential_confounded); (b) DepMap is IMMORTALIZED 2D cell "
        "lines — SL is context/genotype-dependent and frequently fails to replicate across screens "
        "(context_generalization_caveat); (c) a GENETIC KO removes the ENTIRE protein whereas a drug "
        "inhibits ONE activity partially, so a KO-SL OVER-CALLS druggability and a scaffold/non-catalytic "
        "partner (STAG1, SMARCA2, ARID1B) needs a DEGRADER not an inhibitor (druggability_translation_"
        "caveat); (d) a resistance-RESCUE hit is a monitoring LIABILITY / hypothesis, not a combination "
        "win. The single-target dependency MAGNITUDE is owned by functional-requirement and the "
        "druggability call by tractability-small-molecule / surface-modality-fit — breadcrumb, do not "
        "adjudicate them here. NEVER invent partner symbols, screen deltas, PMIDs, or NCTs."
    ),
    mode="descriptive",
)

TARGET_INTRINSIC = LensConfig(
    name="target-intrinsic",
    claim_spec_ref="target_intrinsic_claims:TARGET_INTRINSIC_CLAIM_SPEC",
    thesis="the indication-INDEPENDENT intrinsic target dossier — protein family/class, fold + pockets + "
    "ligandability, surfaceome family, localization/biophysics, germline LoF constraint, and "
    "tractability precedent — distinguishing an EXPERIMENTALLY-CONFIRMED actionable intrinsic "
    "property (a co-crystallised druggable pocket with a bound ligand / an approved drug — BRAF, "
    "EGFR, KRAS-G12C) from a PREDICTED or HOMOLOGY-ANNOTATED one (a computational / AlphaFold pocket "
    "with no co-crystal, a family/surfaceome-class membership assigned by homology, or a "
    "population-genetic / OT-composite META-SCORE) that OVER-CALLS confirmed function or "
    "druggability — annotation depth / significance ≠ actionability.",
    relevance_prompt="give the intrinsic target-biology context read (descriptive dossier; no nomination "
    "call). Foreground whether the actionability-relevant intrinsic signal is "
    "EXPERIMENTALLY confirmed vs computationally / homology annotated.",
    axis_labels={"MODALITY_ROUTING": "modality routing", "TRACTABILITY_PRECEDENT": "tractability precedent"},
    scope_exclusions=(
        "indication-conditioned nomination verdict",
        "the SM druggability call (owned by tractability-small-molecule)",
        "the biologics surface-fit call (owned by surface-modality-fit)",
        "the on-target safety verdict (owned by on-target-safety-liability)",
    ),
    # NARRATOR RULE: this is a DESCRIPTIVE indication-INDEPENDENT dossier (gateless — no nomination call).
    # LEAD by separating an EXPERIMENTALLY-confirmed intrinsic property from a PREDICTED / HOMOLOGY-annotated
    # one, then name the inflation modes the raw dossier cannot self-distinguish.
    polarity_note=(
        "This is a DESCRIPTIVE indication-INDEPENDENT dossier — there is NO nomination verdict; do NOT imply "
        "the dossier nominates the target. LEAD by stating whether the actionability-relevant intrinsic "
        "signal is EXPERIMENTALLY CONFIRMED vs PREDICTED / HOMOLOGY-ANNOTATED (read "
        "intrinsic_confirmation_caveat / intrinsic_provenance: reason "
        "experimentally_confirmed_intrinsic_property — a co-crystallised druggable pocket with a bound "
        "ligand or an approved drug, e.g. BRAF / EGFR / KRAS-G12C — is NOT an over-call and must NOT be "
        "demoted, even if a structure lane reads a target thin/predicted). Then name the inflation modes: "
        "(a) STRUCTURE / LIGANDABILITY — a PREDICTED (AlphaFold / computational) or InterPro-annotated "
        "druggable pocket with NO experimental co-crystal / fragment hit (structural_ligandability_class "
        "predicted_ligandable / annotation_ligandable) OVER-CALLS an experimentally-confirmed druggable "
        "pocket, especially on an intrinsically-disordered / pocketless surface (MYC); (b) FAMILY / "
        "HOMOLOGY — a family or surfaceome-class membership assigned by homology (EC-number / domain / HPA "
        "class) does NOT prove function or druggability: a PSEUDOKINASE sits in the kinase family yet is "
        "catalytically dead (TRIB1/TRIB2), and a bare 'plasma membrane' / SURFY prediction can tag a "
        "cytoplasmic-face or junctional protein as surface without confirmed extracellular topology; "
        "(c) META-SCORE / DOUBLE-COUNT — gnomAD LoF constraint and the Open Targets prioritisation "
        "composite are meta-scores, and the OT composite DOUBLE-COUNTS the dedicated gnomad-lof-constraint "
        "and mouse-ko-phenotype cards (orientation-only, not an independent vote); (d) SIGNIFICANCE / "
        "COMPLETENESS ≠ ACTIONABILITY — a heavily-annotated, high-TDL (Tclin) target is better-STUDIED, not "
        "necessarily a better target, and a genuinely actionable target can be MISSED / understudied "
        "(Tdark = understudied, not adverse; KRAS was called 'undruggable' pre-2013). The SM-druggability "
        "call is owned by tractability-small-molecule, the biologics surface-fit call by surface-modality-"
        "fit, and the safety verdict by on-target-safety-liability — breadcrumb, do not adjudicate them "
        "here. NEVER invent a PDB ID, pocket, ligand, PMID, or numeric ligandability score."
    ),
    mode="descriptive",
)

TRANSLATIONAL_READINESS = LensConfig(
    name="translational-readiness",
    claim_spec_ref="translational_readiness_claims:TRANSLATIONAL_READINESS_CLAIM_SPEC",
    thesis="how translationally READY the target is — whether PUBLIC patient-derived models can preclinically "
    "validate it: are HCMI patient-derived models AVAILABLE in the indication, does an available model "
    "carry THIS target's ALTERATION (genotype-matched), does the dependency reproduce EX-VIVO in "
    "patient-derived 3D CRISPR ORGANOIDS, and does tractability reproduce IN-VIVO in Novartis PDXE PDX "
    "population drug-response trials — distinguishing a FAITHFUL, on-target, adequately-powered "
    "preclinical-validation precedent (a canonical faithfulness-validated PDX/organoid model — ERBB2/HER2 "
    "PDX, EGFR-mutant, BRAF) from a merely AVAILABLE / genotype-matched / small-cohort or "
    "attribution-confounded PDX-responder read that OVER-CALLS actual translational validatability.",
    relevance_prompt="give the translational-readiness context read (descriptive preclinical-validatability "
    "dossier; no nomination call). Foreground whether the readiness rests on a FAITHFUL, "
    "on-target, adequately-powered model precedent vs an availability-only / genotype-only / "
    "small-cohort / attribution-confounded over-call.",
    axis_labels={
        "MODEL": "patient-derived model availability",
        "GENOTYPE": "genotype-matched model",
        "ORGANOID": "organoid ex-vivo dependency",
        "PDX": "PDX in-vivo drug response",
    },
    scope_exclusions=(
        "single-target nomination verdict",
        "the dependency MAGNITUDE / in-vitro cell-line dependency (owned by functional-requirement)",
        "the small-molecule chemical-genetic tractability call (owned by tractability-small-molecule)",
    ),
    # NARRATOR RULE: this is a DESCRIPTIVE preclinical-validatability dossier (gateless — no nomination call).
    # LEAD by separating a FAITHFUL, on-target, adequately-powered model precedent from an availability-only /
    # genotype-only / small-cohort / attribution-confounded over-call, then name the five inflation modes, with
    # the dependency-magnitude + tractability hand-offs as breadcrumbs + the public-only/status:partial coverage note.
    polarity_note=(
        "This is a DESCRIPTIVE preclinical-validatability dossier — there is NO nomination verdict; do NOT imply "
        "model availability nominates the target. LEAD by stating whether the readiness rests on a FAITHFUL, "
        "on-target, adequately-powered preclinical-validation precedent (read translational_readiness_confidence_"
        "caveat / translational_readiness_provenance: a validated_preclinical_model — a canonical faithfulness-"
        "validated PDX/organoid precedent such as ERBB2/HER2 PDX, EGFR-mutant, BRAF — is NOT an over-call and must "
        "not be demoted) or on a merely AVAILABILITY-ONLY / genotype-only / small-cohort / attribution-confounded "
        "read. Then name the five inflation modes model availability cannot self-distinguish: (a) MODEL AVAILABILITY "
        "≠ MODEL FIDELITY — an HCMI model EXISTING does not mean it faithfully recapitulates the target biology "
        "(passage/CNA drift, clonal selection, loss of tumor heterogeneity, TME/immune absence in organoids); (b) "
        "GENOTYPE-MATCHED ≠ TARGET-DEPENDENT — a model carrying the alteration is not proof the target is a "
        "validatable dependency in it (co-occurring drivers; the alteration may be a passenger); (c) SMALL-COHORT "
        "PDX/ORGANOID — a PDXE responder fraction or an organoid dependency read on a tiny cohort is underpowered "
        "(lean on organoid_lineage_small_cohort); (d) PDX DRUG-RESPONSE ATTRIBUTION — a PDXE objective response to "
        "a drug 'naming' the target can be OFF-TARGET or COMBINATION-confounded (response ≠ on-target-for-THIS-"
        "target); (e) PUBLIC-ONLY / status:partial — the dossier is PUBLIC-model-only and the PD-assay, imaging-"
        "tracer, and INTERNAL Takeda PDX/organoid/GEMM legs are un-wired, so a 'ready' read on 4 public legs is a "
        "COVERAGE-bounded readiness, not a complete one (coverage_generalization_caveat). The single-target "
        "dependency MAGNITUDE is owned by functional-requirement and the small-molecule tractability call by "
        "tractability-small-molecule — breadcrumb, do not adjudicate them here. NEVER invent model IDs, responder "
        "fractions, PMIDs, or NCTs."
    ),
    mode="descriptive",
)

TARGET_ARCHETYPE = LensConfig(
    name="target-archetype",
    thesis="the META cross-skill target-signature LANDSCAPE read — where the target sits as a SOFT PHENOTYPE "
    "MIXTURE (a convex membership to curated canonical anchors: KRAS=GoF-driver, VHL=TSG, ERBB2=amp, "
    "EPCAM=surface, AURKA=dependency, GAPDH=control — a DISTRIBUTION, never a hard label), which "
    "reference targets it is most like (nearest ANALOGS), how its fired-rule fingerprint matches "
    "precedent, whether its signature fits no canonical mix (NOVELTY = hull-residual), and a glass-box "
    "D1 nomination-READINESS scorecard — WHILE distinguishing a HIGH-STABILITY, LOW-MISSINGNESS mixture "
    "dominated by an independently-established canonical anchor from an OVER-CONFIDENT phenotype/analog/"
    "readiness read that the mixture's OWN axis-jackknife STABILITY, its MISSINGNESS map, label "
    "CIRCULARITY (the anchors/reference labels are curated + partly circular), or the ILLUSTRATIVE-not-"
    "learned scorecard weights do NOT support.",
    relevance_prompt="give the phenotype-landscape context read (descriptive signature map; NO classification "
    "and NO nomination call). Foreground whether the dominant phenotype / nearest analog / "
    "readiness read is a HIGH-STABILITY, LOW-MISSINGNESS, independently-established signal or "
    "an over-call driven by low jackknife stability, missingness-distortion, label "
    "circularity, or illustrative-not-learned scorecard weights.",
    axis_labels={
        "PHENOTYPE": "dominant phenotype mixture",
        "ANALOG": "nearest reference analog",
        "PRECEDENT": "rule-fingerprint precedent",
        "NOVELTY": "hull-residual novelty",
        "READINESS": "D1 nomination-readiness scorecard",
    },
    scope_exclusions=(
        "any single-target nomination / classification verdict (this layer is descriptive + "
        "verdict-INERT, never a gate)",
        "the per-axis evidence calls themselves (owned by the 14 fan-out sub-skills — "
        "tumor-presence / functional-requirement / genomic-alteration / surface-modality-fit / …)",
        "assigning a HARD single-phenotype label (only the soft mixture is honest)",
    ),
    # NARRATOR RULE: this is a DESCRIPTIVE META signature MAP (cardless; gateless — no nomination/classification
    # call). LEAD by separating a HIGH-STABILITY, LOW-MISSINGNESS, canonical-anchor-dominant mixture from a
    # low-stability / missingness-distorted / label-circular / illustrative-weight OVER-CALL, then name the five
    # inflation modes the raw mixture/analog/scorecard cannot self-distinguish.
    polarity_note=(
        "This is a DESCRIPTIVE cross-skill signature LANDSCAPE — the phenotype_mixture is a soft DISTRIBUTION "
        "(convex membership to curated anchors), NEVER a hard label, and there is NO classification or "
        "nomination verdict; do NOT imply the mixture / nearest_analog / scorecard classifies or nominates the "
        "target. LEAD by stating whether the dominant-phenotype / nearest-analog / readiness read is a "
        "HIGH-STABILITY, LOW-MISSINGNESS, independently-established signal or an OVER-CALL (read "
        "archetype_confidence_caveat / archetype_provenance): a validated_canonical_anchor read — a HIGH mixture "
        "stability + LOW missingness mixture dominated by a canonical anchor whose phenotype is independently "
        "biologically established (KRAS=GoF-driver, VHL=TSG, ERBB2=amp, EPCAM=surface) — is NOT an over-call and "
        "must NOT be demoted. Then name the five inflation modes: (a) LABEL CIRCULARITY — the anchors + reference "
        "panel labels are curated + PARTLY CIRCULAR (clinical antigens; cards designed from the same biology), so "
        "a nearest_analogs 'most like TROP2/CDH17' can be an artifact of shared card design, not an independent "
        "biological analogy (read label_is_derived + the analog_or_label_circular reason); (b) MISSINGNESS-"
        "DISTORTED MIXTURE — an UNMEASURED axis mean-imputes to 0 and silently distorts the mixture (the "
        "documented EGFR amp-dominant-because-SNV-silently-0 failure), so a sharp mixture on FEW measured axes / "
        "LOW mixture_uncertainty.stability is unreliable — the jackknife stability band + missingness map are the "
        "honest discriminators; (c) ILLUSTRATIVE-NOT-LEARNED scorecard weights — the D1 nomination_scorecard "
        "per-archetype weights are ILLUSTRATIVE + SHOWN, not learned, so a scorecard NUMBER ORIENTS, it is NEVER "
        "a nomination-readiness verdict (the RETIRED outcome-trained D2/D3 approval-propensity score is the "
        "cautionary tale — a learned score was maturity/study-depth-confounded, not disease biology); (d) NOVELTY "
        "MIS-CALL — the hull-residual inconsistent_flag is a heuristic (scale-invariant-relative, but still) and "
        "can mis-fire on an EXTREME-but-canonical blend; treat multimodal/mixture_entropy as the 'genuine "
        "multi-phenotype blend vs truly weird' discriminator; (e) ANCHOR PROVISIONALITY / DEFERRED FUSION — the "
        "anchors are curated + partly circular and the fusion_driver anchor is DEFERRED (a trial re-freeze bled "
        "RTK-ness into non-fusion RTKs). The per-axis evidence calls are owned by the 14 fan-out sub-skills — "
        "breadcrumb, do not adjudicate them here. NEVER invent an anchor, analog symbol, mixture weight, "
        "scorecard number, or PMID."
    ),
    mode="descriptive",
    # TOKENLESS descriptive lens (like COMBINATION_VULNERABILITY / TARGET_INTRINSIC): the companion emits NO
    # collapsed verdict token (verdict=None, no resolved rung), so NO verdict_key — the collapsed-verdict prompt
    # line resolves to None and the descriptive tool needs no verdict. The narration LEADS with the SIGNAL VECTOR
    # (the phenotype/analog/precedent/novelty/readiness claim_vector this skill's bespoke run.py builds from
    # companion + nomination_scorecard).
)

LITERATURE_CONTEXT = LensConfig(
    name="literature-context",
    claim_spec_ref="literature_context_claims:LITERATURE_CONTEXT_CLAIM_SPEC",
    thesis="what the PUBLISHED LITERATURE SAYS about the target in the indication — the co-occurrence VOLUME "
    "(how much is written), the RECENCY, the top CITED STATEMENTS, and the typed relation DIRECTION "
    "(PubTator3 BioREx associate/cause/inhibit/stimulate/…) — as a DESCRIPTIVE citation context, NOT a "
    "validated/causal/mechanistic claim, WHILE distinguishing a CANONICAL, VALIDATED, DIRECTION-CORRECT "
    "target–indication relationship (KRAS/CRC, ERBB2/breast, EGFR/lung, VHL/ccRCC — high volume AND a "
    "consistent mechanistically-correct relation) from an OVER-CONFIDENT validated/causal/direction-correct "
    "read that the raw co-occurrence VOLUME or the AUTOMATED relation direction does NOT support: a high "
    "count is CITATION / ATTENTION / STUDY bias (well-studied genes accrue mentions; a pleiotropic gene "
    "co-occurs across many diseases as a passenger — VOLUME ≠ VALIDATION), and a BioREx typed edge is "
    "ML-extracted from often a SINGLE sentence (mis-typed / conflicting / context-free — DIRECTION ≠ "
    "validated mechanism).",
    relevance_prompt="give the cited-literature CONTEXT read (descriptive; NO nomination call and NO causal/"
    "mechanistic call). Foreground the top CITED STATEMENTS + whether a high co-occurrence "
    "volume / a typed relation direction reflects a canonical validated relationship or "
    "citation-bias / pleiotropy / automated-extraction over-call.",
    axis_labels={
        "VOLUME": "co-occurrence volume",
        "RECENCY": "recent activity",
        "RELATION": "typed relation direction",
    },
    scope_exclusions=(
        "any nomination / prioritization verdict (this layer is CONTEXT-tier + verdict-INERT, "
        "NEVER a gate — RISK_ASSESSMENT_INTEGRATION.md §4)",
        "the mechanistic / causal MoA call (owned by mechanism-and-pharmacology)",
        "the 6-dimension literature RISK read (owned by literature-risk-assessment)",
        "the target–indication association's biological validity (co-occurrence describes what is "
        "WRITTEN, not what is TRUE)",
    ),
    # NARRATOR RULE: this is a DESCRIPTIVE cited-literature CONTEXT read (gateless — no nomination/causal call).
    # LEAD with the top CITED STATEMENTS (the substance), then separate a canonical validated relationship from a
    # volume-inflation / automated-relation / pleiotropy over-call, then name the inflation modes the raw
    # volume/direction cannot self-distinguish. NEVER read a "this relationship is validated" claim off a bare count.
    polarity_note=(
        "This lens is DESCRIPTIVE + CONTEXT-tier — the co-occurrence VOLUME and the PubTator3 typed relation "
        "DIRECTION describe what the literature HAS WRITTEN, they are NOT a validated / causal / mechanistic / "
        "direction-correct claim, and there is NO nomination verdict; do NOT imply the volume or the relation "
        "nominates or validates the target. LEAD by CITING the top CITED STATEMENTS (top_cited — pmid/year/"
        "sentence: the actual substance), then state whether the read is a CANONICAL, VALIDATED, DIRECTION-CORRECT "
        "relationship or an OVER-CALL (read cited_evidence_confidence_caveat / cited_evidence_provenance): a "
        "validated_established_relationship read — a canonical target–indication pair with HIGH co-occurrence "
        "volume AND a consistent, mechanistically-correct relation direction (KRAS/CRC activating driver, "
        "ERBB2/breast amplification, EGFR/lung activating SNV, VHL/ccRCC LoF) — is NOT an over-call and must NOT "
        "be demoted. Then name the inflation modes: (a) VOLUME ≠ VALIDATION — a high europePMC co-occurrence "
        "count reflects CITATION / ATTENTION / STUDY bias (well-studied targets accrue mentions — Stoeger 2018 "
        "PMID 30226837; Edwards 2011 PMID 21307913; guilt-by-association multifunctionality — Gillis & Pavlidis "
        "2012 PMID 22479173), NOT a validated or causal target–indication relationship (a pair can co-occur "
        "heavily as passengers / context) — the volume_without_validated_relation reason = HIGH volume but "
        "thin / absent / ambiguous relation direction; (b) RELATION DIRECTION IS AUTOMATED + CONTEXT-FREE — "
        "PubTator3 BioREx typed edges (associate / cause / inhibit / …) are ML-extracted, often from a SINGLE "
        "sentence, so they can be MIS-TYPED, direction-ambiguous, CONFLICTING across papers, or context-free "
        "(an in-vitro 'inhibit' edge is not a validated in-vivo mechanism) — the "
        "relation_direction_automated_or_conflicting reason; (c) RECENCY / STALENESS — an old latest_year is a "
        "stale literature that may pre-date modern understanding, and a burst of recent low-quality mentions is "
        "not validation either (stale_literature note); (d) PLEIOTROPY / SCOPE — co-occurrence is a "
        "target×disease ASSOCIATION, not target-centric causality; a high n_diseases = a promiscuous / "
        "pleiotropic target mentioned across many diseases (the TP53 pattern — nonspecific). The mechanistic / "
        "causal call is owned by mechanism-and-pharmacology and the RISK read by literature-risk-assessment — "
        "breadcrumb, do not adjudicate them here. Attribute every claim to a specific pmid from top_cited; NEVER "
        "invent a PMID, statement, relation type, or count."
    ),
    mode="descriptive",
    # TOKENLESS descriptive lens (like COMBINATION_VULNERABILITY / TARGET_INTRINSIC / TRANSLATIONAL_READINESS /
    # TARGET_ARCHETYPE): literature-context supplies verdict_fn=None and emits NO collapsed verdict token — so
    # NO verdict_key; the collapsed-verdict prompt line resolves to None and the descriptive tool needs no
    # verdict. The narration LEADS with the top CITED STATEMENTS + the VOLUME/RECENCY/RELATION claim_vector this
    # skill's run.py builds from the cited-literature-evidence card.
)

# Registry for the dispatcher / fan-out lookup by skill name — the 14 hierarchy skills + the NON-standard
# companions: target-archetype (cardless META) and literature-context (literature-native cited-evidence peer).
# The curated-SL / paralog-dual-KO relational signals are composed as CARDS under combination-and-vulnerability
# (its COMBINATION_VULNERABILITY lens narrates them); the former standalone synthetic-lethal-partners /
# combinatorial-dependency skills were retired 2026-09-10.
LENSES = {
    L.name: L
    for L in (
        FUNCTIONAL_REQUIREMENT,
        ON_TARGET_SAFETY,
        TUMOR_PRESENCE,
        TUMOR_SELECTIVITY,
        GENOMIC_ALTERATION,
        SURFACE_MODALITY_FIT,
        TRACTABILITY_SM,
        IMMUNE_CONTEXT,
        DIFFERENTIATION_LANDSCAPE,
        MECHANISM_PHARMACOLOGY,
        CIS_FEATURE_COHERENCE,
        COMBINATION_VULNERABILITY,
        TARGET_INTRINSIC,
        TRANSLATIONAL_READINESS,
        TARGET_ARCHETYPE,
        LITERATURE_CONTEXT,
    )
}
