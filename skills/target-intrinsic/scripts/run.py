#!/usr/bin/env python3
"""target-intrinsic — the INDICATION-INDEPENDENT target dossier.

Answers "what do we know about target X, independent of any cancer?" — the facts true of the
PROTEIN/GENE regardless of indication: identity, on-target-safety genetics, protein-class /
structure / modality biophysics, functional annotation (GO), mechanism + pathway role (composed
signaling network / Reactome), interactome (STRING / CORUM / BioGRID), domain architecture +
domain→modality implication, and paralog buffering — the `tier: target` cards. Pan-cancer DISEASE
observations (tumor elevation, dependency, mutation frequency, PRISM, cell-line abundance) are
DELIBERATELY EXCLUDED: they are aggregated cancer behavior, owned by the disease-context subskills.

DESCRIPTIVE, not nominating (verdict_fn=None): a target's therapeutic value is indication-conditioned,
so target-intrinsic evidence informs confidence/context but never mints a recommendation. Invoked with
--target ALONE; the shared dispatcher makes --indication optional and passes a pan-cancer sentinel that
these tier:target readers ignore.

See SKILL.md for the full rationale, card roster, and how this skill composes into target-profile.
The CARDS list below is the single source of truth for the live-wired roster (grouped by sub-axis).
"""

from __future__ import annotations

import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILLS_DIR))

from _skills_common import get_card_field
from _skills_common.dispatcher import run_wired_skill
from _skills_common.headline_core import HeadlineSpec, build_headline
from _skills_common.headline_hero import emit_headline_hero
from _skills_common.literature_retrieval import default_retrieve, verify_citations
from _skills_common.literature_synthesis import make_literature_fn
from _skills_common.narrator_engine import make_synthesize_fn
from _skills_common.narrator_lenses import TARGET_INTRINSIC as _LENS
from _skills_common.skill_report import ROLE_DESCRIPTIVE, build_skill_report
from _skills_common.subgroup_derivation import make_value_classifier
from _skills_common.target_intrinsic_claims import target_intrinsic_claim_vector, target_intrinsic_key_signals
from _skills_common.target_intrinsic_question_table import target_intrinsic_question_table

# Signals-first sub-group VALUE→TIER map (VERDICT-INERT; feeds ONLY the --figures subgroup-signal panel,
# never the spine / claim_vector / narrator). Stated for target-intrinsic's OWN LIVE card vocabulary so a
# positive signal is not silently flipped to `absent` by the lens-blind default_classify substring
# heuristic (make_value_classifier docstring); any value the map omits still degrades to that default.
# Keys are the ACTUAL emitted class tokens (the prior map keyed on tokens no method emits —
# partially_annotated / poorly_annotated / moderately_characterized / connector / peripheral /
# degrader_required / curated_domain / bare-`surface` — so those live classes fell through to the
# default, which flips e.g. connected / removal_favored / kinase_surface to `absent`). MODALITY routing
# tiers MIRROR target_intrinsic_claims._MODALITY_SIGNAL (the claim_vector the narrator sees).
_TARGET_INTRINSIC_VALUE_TIERS = {
    # annotation / characterization density (GO annotation_class, signaling network_class, reactome
    # pathway_class) — a heavily-curated target is better-ANNOTATED, not better biology (disclaimed).
    "well_annotated": "strong",
    "well_characterized": "strong",
    "partial": "moderate",
    "sparse": "weak",
    # interactome hubness (ppi-interactome interactome_class); "sparse" tiered above
    "hub": "strong",
    "connected": "moderate",
    # Pharos/IDG development level (TDL) — drug-development PRECEDENT (Tdark = understudied, not adverse)
    "Tclin": "strong",
    "Tchem": "moderate",
    "Tbio": "weak",
    "Tdark": "absent",
    # domain→modality routing (domain-modality-relevance) — MIRRORS _MODALITY_SIGNAL (call conviction)
    "removal_required_scaffolding": "strong",
    "removal_favored": "moderate",
    "inhibitor_sufficient": "moderate",
    "context_dependent": "weak",
    "indeterminate": "absent",
    # UniProt curated domain architecture (protein-domains-class protein_features_class)
    "multi_domain": "strong",
    "single_domain": "moderate",
    "no_curated_domain": "absent",
    # surfaceome family (surfaceome-family-classification family_class) — a surface-confirmed family is a
    # positive modality-routing determinant; the honest non-surface token carries no surface route.
    "kinase_surface": "strong",
    "enzyme_surface": "strong",
    "transporter": "strong",
    "cd_molecule": "strong",
    "adhesion": "strong",
    "gpcr": "strong",
    "growth_factor_receptor": "strong",
    "immune_receptor": "strong",
    "other_surface": "strong",
    "not_surface": "absent",
    # MEASURED chemical matter (measured-potency-tractability measured_bioactivity_class) — a measured
    # potent binder is the STRONGEST tractability-precedent signal this roster carries; without the map it
    # fell through to the default (no "strong"/"high" substring → `absent`), inverting the panel read.
    "potent_measured_ligand": "strong",
    "weak_measured_ligand": "moderate",
    "no_measured_activity": "absent",
    # shed ectodomain (shed-ectodomain-liability shed_liability_class). Tiered on SIGNAL STRENGTH of the
    # liability read (the panel is a signal meter, not a desirability meter): a clinically documented shed
    # ectodomain is a strong, well-evidenced intrinsic property; the secretome proxy is a weaker inference;
    # a membrane-retained call is a confident negative for the liability (no signal to route on).
    "clinically_shed": "strong",
    "secretome_proxy_shed": "moderate",
    "not_shed_membrane_retained": "absent",
    # structure ligandability coverage (structure-features-static pdb_coverage_class). "strong" and
    # "partial" are already tiered above; the two model-only / empty tokens carry no experimental structure.
    "af_only": "weak",
    "none": "absent",
    # composite SM-ligandability call (structure-features-static structural_ligandability_class), the
    # card primary the panel now binds (#1592). Tiered on SIGNAL STRENGTH of the ligandability read: an
    # experimental co-crystal is the strongest handle; a predicted pocket / VS hit is a weaker inference;
    # an annotated site (no pocket call) weaker still; no positive axis and a measured-disorder liability
    # are confident negatives; absence from all six sources is a coverage gap, NOT a negative.
    "experimental_ligandable": "strong",
    "predicted_ligandable": "moderate",
    "annotation_ligandable": "weak",
    "no_ligandability_signal": "absent",
    "disordered_low": "absent",
    "insufficient_evidence": "unmeasured",
    # interactome (ppi-interactome interactome_class); hub / connected / sparse tiered above
    "no_high_confidence_interactors": "absent",
    # EXPLICIT gap token, emitted by several readers when the gene is outside the source's coverage.
    # Now `unmeasured` (the off-axis abstention added to _skills_common/subgroup_derivation.py), which is
    # what this entry has wanted since it was written: a coverage gap is no longer encoded as a measured
    # negative. It does not vote in the sub-group agreement count, does not rank as the sub-group's signal,
    # and cannot "conflict" with a card that did measure.
    # (literal, not the UNMEASURED constant: test_declared_tiers_are_valid reads this map with
    # ast.literal_eval straight from the source, and validates the spelling against _TIERS.)
    "data_unavailable": "unmeasured",
}

# EXPLICIT sub-group reader spec {measurement_type: {"class", "n", "label"}} — which field of each source
# card the panel reads. Without it, derive_subgroups falls back to `_heuristic_reader`, which picks the
# FIRST `*_class` key in the summary DICT ORDER. That made the binding ORDER-DEPENDENT and therefore
# NON-REPRODUCIBLE: a live run (reader insertion order) bound `shed_liability_class` +
# `measured_bioactivity_class`, while the offline replay of the same run (fixture re-serialized with
# sort_keys=True) bound `measured_shed_class` + `chembl_approved_engagement_class` — a DIFFERENT panel from
# identical evidence, and the offline guard could not see the live tokens. Declaring the fields pins both
# paths to the same read. Bindings + `n` field orders are transcribed from the LIVE heuristic result on the
# EGFR reference run, so the live panel is byte-stable; only the replay converges onto it.
# (#1592: two entries were rebound to the card-primary field so the panel displays the same value the
# headline/caveat reason over. `structure_druggability` now reads the contract primary_class
# `structural_ligandability_class` (the composite SM-ligandability call) instead of the blunter
# `pdb_coverage_class`; GO's power keys on the total annotation count `n_go_terms_total` instead of the
# first-ranked `n_cellular_component`. Both move emitted panel values; verdict-inert.)
_TARGET_INTRINSIC_SUBGROUP_READER = {
    "surfaceome_family": {"class": "family_class", "n": [], "label": "family"},
    "structure_druggability": {"class": "structural_ligandability_class", "n": [], "label": "structural ligandability"},
    "shed_ectodomain_liability": {"class": "shed_liability_class", "n": [], "label": "shed liability"},
    "gene_ontology_annotation": {
        "class": "annotation_class",
        "n": [
            "n_go_terms_total",
            "n_cellular_component",
            "n_biological_process",
            "n_go_terms_experimental",
            "n_molecular_function",
        ],
        "label": "annotation",
    },
    "signaling_network_mechanism": {
        "class": "network_class",
        "n": ["n_downstream_effectors", "n_upstream_regulators"],
        "label": "network",
    },
    "reactome_pathway_membership": {"class": "pathway_class", "n": [], "label": "pathway"},
    "ppi_interactome": {"class": "interactome_class", "n": [], "label": "interactome"},
    "protein_domains_class": {"class": "protein_features_class", "n": [], "label": "protein features"},
    "domain_modality_relevance": {"class": "modality_implication_class", "n": [], "label": "modality implication"},
    "target_development_level": {"class": "tdl_class", "n": [], "label": "tdl"},
    "measured_potency_tractability": {
        "class": "measured_bioactivity_class",
        "n": ["bindingdb_n_potent_ligands", "chembl_n_potent_ligands", "n_direct_interactions"],
        "label": "measured bioactivity",
    },
    # target_identity carries no *_class field — it is not a signal source (the heuristic bound nothing
    # either). A falsy spec states that explicitly instead of relying on the fallback finding nothing.
    "target_identity": None,
}


SKILL_NAME = "target-intrinsic"
SKILL_VERSION = "1.6.1"  # 1.6.1 (2026-09-12): _TARGET_INTRINSIC_VALUE_TIERS COMPLETED against the live card vocabulary — measured_bioactivity_class (potent/weak/no_measured_activity), shed_liability_class (clinically_shed/secretome_proxy_shed/not_shed_membrane_retained), pdb_coverage_class af_only/none, no_high_confidence_interactors, explicit data_unavailable->absent. Two live EGFR signals (potent_measured_ligand, secretome_proxy_shed) were being flipped to `absent` by the lens-blind default_classify fallback. VERDICT-INERT (--figures sub-group panel only; spine/claim_vector/narrator byte-stable). + data-driven vocabulary-coverage guard (test_subgroup_value_tiers.py), 20/20 re-frozen egfr.yaml, and a full-decision golden.   # 1.6.0 (2026-09-04): --literature lane (run_wired_skill make_literature_fn(TARGET_INTRINSIC); None-indication path via _indication_phrase->'cancer') + VERDICT-INERT experimental-vs-predicted INFLATION surfacing (intrinsic_confirmation_caveat = an AlphaFold/computational or homology-annotated actionable property [predicted_ligandable / annotation_ligandable pocket, predicted-surface, family-by-homology] over-calling a co-crystal-confirmed one, OR a meta-score / OT-composite double-count; experimentally_confirmed_intrinsic_property false-demote guard, pan-target gene-level BRAF/EGFR/KRAS-G12C; intrinsic_provenance quorum). Built on BOTH _headline AND the self-contained _synthesis_facet (fan-out carrier). TARGET_INTRINSIC thesis extend + ADD polarity_note. Gateless (verdict_fn=None) — dossier byte-stable.   # 1.5.1 (2026-09-02): _TARGET_INTRINSIC_VALUE_TIERS aligned to live card vocab (dead keys removed; positive subgroup signals no longer flip to `absent`). Verdict-INERT (subgroup --figures only).   # 1.4.0 (2026-08-28): capsule-driven narrator via generic engine. Verdict-INERT.   # 1.3.0 (2026-08-27): tuned signals-first sub-group reader. Verdict-INERT.   # stamped into provenance.yaml — MUST equal SKILL.md metadata.version

CARDS = [
    # STRICT MOLECULAR-INTRINSIC only: properties true of the MOLECULE (protein/gene), independent of
    # any cancer. Pan-cancer disease observations (tumor elevation, dependency, mutation frequency,
    # PRISM, cell-line abundance) are excluded — they belong to the disease-context subskills.
    # --- IDENTITY ------------------------------------------------------------------------------
    "target-identity-summary",  # canonical id, family, aliases
    # --- GERMLINE GENETICS & CONSTRAINT (properties of the GENE; the on-target-safety axis) -----
    "gnomad-lof-constraint",  # germline LoF intolerance (pLI/LOEUF)
    "gene-burden-safety",  # rare-variant burden safety signal
    "clingen-dosage",  # ClinGen haploinsufficiency / triplosensitivity
    "clinvar-pathogenicity-safety",  # germline pathogenic-variant burden
    "mouse-ko-phenotype",  # IMPC mouse-KO lethal/developmental phenotypes
    "target-safety-prioritisation",  # OT composite prioritisation score. ORIENTATION-ONLY (verdict-inert):
    # its SAFETY dimension overlaps gnomad-lof-constraint + mouse-ko-phenotype
    # (the dedicated cards); retained for its tractability/precedence dimensions,
    # not read as a standalone safety fact.
    # --- PROTEIN CLASS / STRUCTURE / BIOPHYSICS (properties of the PROTEIN) ---------------------
    "surfaceome-family-classification",  # surface protein family + membership (protein-class proxy)
    "structure-features-static",  # fold / pockets / ligandability (structure-intrinsic)
    "shed-ectodomain-liability",  # circulating soluble ectodomain (biophysical property)
    # --- FUNCTIONAL ANNOTATION (Gene Ontology: what it does / where it is / what processes) -----
    "gene-ontology-annotation",  # GO BP/MF/CC term membership (experimental-evidence-flagged)
    # --- MECHANISM / PATHWAY ROLE (the molecule's place in signaling) ---------------------------
    "signaling-network-mechanism",  # composed directed network (SIGNOR / CollecTRI / Reactome) + MoA class
    "reactome-pathway-membership",  # Reactome pathway/geneset MEMBERSHIP + top-level rollup (distinct from directed edges above)
    # --- INTERACTOME (physical/functional interactions + complex membership) --------------------
    "ppi-interactome",  # STRING functional network + CORUM complexes + BioGRID physical interactions
    # --- DOMAIN ARCHITECTURE / PROTEIN CLASS (curated UniProt features) --------------------------
    "protein-domains-class",  # FT DOMAIN architecture + UniProt-keyword protein class
    "target-development-level",  # Pharos/IDG TDL: druggability/novelty tier (Tclin/Tchem/Tbio/Tdark)
    # + family. Verdict-inert target-intrinsic facet.
    "measured-potency-tractability",  # ChEMBL/BindingDB measured potent-binder count + best potency —
    # the MEASURED chemical-matter dimension (tier:target). Borrowed from
    # tractability-small-molecule; verdict-inert intrinsic-druggability facet.
    "domain-modality-relevance",  # INTERPRETIVE domain→modality facet: inhibitor_sufficient vs
    # removal_required_scaffolding (e.g. RIPK1). tier:target, verdict-inert.
    # --- PARALOGS (gene-family redundancy — a genomic-intrinsic property) -----------------------
    "paralog-buffering",  # sequence paralogs + buffering (dependency-hardening context)
    # --- NORMAL (non-disease) EXPRESSION --------------------------------------------------------
    "normal-tissue-liability",  # HPA normal-tissue protein breadth (baseline, non-tumor)
]

QUESTION = (
    "What is known about {target} INDEPENDENT of indication — its identity, on-target-safety "
    "genetics, protein-class/structure/modality biophysics, functional annotation, mechanism + "
    "pathway role, interactome, domain architecture + domain→modality implication, and paralog "
    "buffering?"
)


# Declarative dossier field-map: (headline_key, card_id, card_field), grouped by target-intrinsic
# sub-axis. This is the SINGLE SOURCE for both _headline AND the drift guard — the test AST-parses
# this table's card_ids, so a card added to CARDS but never surfaced here is caught structurally
# (target-intrinsic is descriptive: this table is the ONLY place a card's signal reaches output).
_HEADLINE_SPEC = [
    # identity
    ("target_symbol", "target-identity-summary", "resolved_hgnc_symbol"),
    ("target_ensembl_id", "target-identity-summary", "resolved_ensembl_id"),
    # safety genetics
    ("gnomad_constraint_class", "gnomad-lof-constraint", "constraint_class"),
    ("clingen_dosage_class", "clingen-dosage", "dosage_sensitivity_class"),
    ("clinvar_pathogenic_class", "clinvar-pathogenicity-safety", "clinvar_pathogenic_class"),
    ("gene_burden_safety_class", "gene-burden-safety", "burden_safety_class"),
    ("mouse_ko_phenotype_class", "mouse-ko-phenotype", "ko_phenotype_class"),
    # target-safety-prioritisation is ORIENTATION-ONLY (safety dim overlaps constraint + mouse-KO)
    ("target_safety_prioritisation", "target-safety-prioritisation", "prioritisation_status"),
    # OT composite bands — surfaced to make the DOUBLE-COUNT explicit: genetic_constraint_band mirrors the
    # dedicated gnomad-lof-constraint card, mouse_ko_score_band mirrors mouse-ko-phenotype (same underlying
    # facts). Orientation-only; intrinsic_provenance flags the double-count so they are not read as votes.
    ("ot_genetic_constraint_band", "target-safety-prioritisation", "genetic_constraint_band"),
    ("ot_mouse_ko_score_band", "target-safety-prioritisation", "mouse_ko_score_band"),
    ("ot_has_safety_event_band", "target-safety-prioritisation", "has_safety_event_band"),
    # protein class / structure / biophysics
    ("surface_protein_family", "surfaceome-family-classification", "family_class"),
    ("is_surface_protein", "surfaceome-family-classification", "is_surface_protein"),
    # surfaceome PROVENANCE — experimental HPA plasma-membrane vs SURFY prediction vs IUPHAR type; the
    # predicted-surface-vs-experimental-localization discriminator (a bare SURFY/plasma-membrane call can
    # tag a cytoplasmic-face / junctional protein as surface without confirmed extracellular topology).
    ("surface_source_surfy_positive", "surfaceome-family-classification", "source_surfy_positive"),
    ("surface_source_hpa_plasma_membrane", "surfaceome-family-classification", "source_hpa_plasma_membrane"),
    ("surfaceome_confidence_score", "surfaceome-family-classification", "surfaceome_confidence_score"),
    ("structure_pocket_call", "structure-features-static", "hotspot_pocket_adjacency_call"),
    # STRUCTURE / LIGANDABILITY experimental-vs-predicted provenance — the core of the target-intrinsic
    # trap (a computational / AlphaFold pocket over-calling a co-crystal-confirmed druggable pocket). These
    # decision-grade fields already exist on the card (PDB-vs-AlphaFold tagged); surface them so the
    # dossier — and intrinsic_confirmation_caveat — can separate experimental_ligandable from predicted.
    ("structural_ligandability_class", "structure-features-static", "structural_ligandability_class"),
    ("has_experimental_cocrystal", "structure-features-static", "has_experimental_cocrystal"),
    ("has_druggable_pocket", "structure-features-static", "has_druggable_pocket"),
    ("has_virtual_screen_hit", "structure-features-static", "has_virtual_screen_hit"),
    ("pdb_coverage_class", "structure-features-static", "pdb_coverage_class"),
    ("alphafold_confidence_class", "structure-features-static", "alphafold_confidence_class"),
    ("structure_disordered_fraction", "structure-features-static", "disordered_fraction"),
    ("ligandability_disorder_class", "structure-features-static", "ligandability_disorder_class"),
    ("n_ligandability_axes", "structure-features-static", "n_ligandability_axes"),
    # measured chemical matter (borrowed from tractability-small-molecule; intrinsic druggability)
    ("measured_bioactivity_class", "measured-potency-tractability", "measured_bioactivity_class"),
    ("chembl_n_potent_ligands", "measured-potency-tractability", "chembl_n_potent_ligands"),
    ("best_measured_potency_neglog_m", "measured-potency-tractability", "best_measured_potency_neglog_m"),
    ("shed_liability_class", "shed-ectodomain-liability", "shed_liability_class"),
    # functional annotation (Gene Ontology)
    ("go_annotation_class", "gene-ontology-annotation", "annotation_class"),
    ("go_n_terms_total", "gene-ontology-annotation", "n_go_terms_total"),
    ("go_n_biological_process", "gene-ontology-annotation", "n_biological_process"),
    ("go_n_molecular_function", "gene-ontology-annotation", "n_molecular_function"),
    ("go_n_cellular_component", "gene-ontology-annotation", "n_cellular_component"),
    # mechanism / pathway role
    ("network_class", "signaling-network-mechanism", "network_class"),
    ("n_upstream_regulators", "signaling-network-mechanism", "n_upstream_regulators"),
    ("n_downstream_effectors", "signaling-network-mechanism", "n_downstream_effectors"),
    # pathway / geneset membership (Reactome)
    ("pathway_class", "reactome-pathway-membership", "pathway_class"),
    ("pathway_count", "reactome-pathway-membership", "pathway_count"),
    ("top_level_pathways", "reactome-pathway-membership", "top_level_pathways"),
    # domain architecture / protein class (UniProt curated)
    ("protein_features_class", "protein-domains-class", "protein_features_class"),
    ("n_domains", "protein-domains-class", "n_domains"),
    ("domain_architecture", "protein-domains-class", "domain_architecture"),
    ("protein_class", "protein-domains-class", "protein_class"),
    # Pharos/IDG Target Development Level — druggability/novelty tier (verdict-inert)
    ("tdl_class", "target-development-level", "tdl_class"),
    ("tdl_target_family", "target-development-level", "target_family"),
    ("tdl_novelty_score", "target-development-level", "novelty_score"),
    # domain→modality implication (INTERPRETIVE sibling of protein-domains-class): inhibitor-sufficient
    # vs removal-required (degrader/scaffolding). Verdict-inert; the heuristic returns indeterminate for
    # a multi-domain enzyme, curated RIPK1 → removal_required_scaffolding.
    ("modality_implication_class", "domain-modality-relevance", "modality_implication_class"),
    ("modality_implication_basis", "domain-modality-relevance", "modality_implication_basis"),
    ("modality_scaffolding_function", "domain-modality-relevance", "scaffolding_function"),
    ("modality_implication_context", "domain-modality-relevance", "modality_context"),
    # interactome (STRING functional network + CORUM complexes + BioGRID physical)
    ("interactome_class", "ppi-interactome", "interactome_class"),
    ("n_high_confidence_interactors", "ppi-interactome", "n_high_confidence_interactors"),
    ("n_corum_complexes", "ppi-interactome", "n_corum_complexes"),
    ("in_protein_complex", "ppi-interactome", "in_protein_complex"),
    # paralogs (gene-family redundancy)
    ("paralog_buffering_class", "paralog-buffering", "paralog_buffering_class"),
    ("n_paralogs_annotated", "paralog-buffering", "n_paralogs_annotated"),
    ("strongest_paralog_symbol", "paralog-buffering", "strongest_paralog_symbol"),
    # normal (non-disease) expression
    ("normal_tissue_breadth_class", "normal-tissue-liability", "normal_tissue_breadth_class"),
]


# ── VERDICT-INERT experimental-vs-predicted / annotation INFLATION surfacing (2026-09-04) ────────
# The target-intrinsic analog of tractability's directness_caveat / surface's surface_confirmation_caveat
# / mechanism's mechanism_confirmation_caveat. A PREDICTION (AlphaFold / computational ligandability) or a
# HOMOLOGY-annotated family/surface membership OVER-CALLS an EXPERIMENTALLY-CONFIRMED actionable intrinsic
# property; and a population-genetic / OT-composite META-SCORE gets read as actionability (the OT composite
# DOUBLE-COUNTS the dedicated gnomad-lof + mouse-ko cards). VERDICT-INERT — target-intrinsic is gateless
# (verdict_fn=None); none of this feeds a resolver (there is none). Built on BOTH the standalone _headline
# (all 20 cards resolved → the full structural over-call) AND the composed _synthesis_facet (its own 8-card
# subset — structure/surfaceome/safety/gnomad cards are HOME'd elsewhere and ABSENT there, so those fields
# degrade to None and the symbol-keyed guard + annotation tier still carry it), so the composed profile
# carries the field rather than silently dropping it.

# INDICATION-INDEPENDENT, gene-level, NON-EXHAUSTIVE curated crosswalk of targets with an approved /
# clinically-validated directly-acting agent — the EXPERIMENTALLY-CONFIRMED actionable-property false-demote
# GUARD (the BRAF / EGFR / KRAS-G12C + validated-surface-antigen set). Keyed on SYMBOL (presence),
# data-blind-tolerant: it spares the guard EVEN IF a structure lane reads the target thin/predicted (the
# #1042 validated_paralog_synthetic_lethal lesson; the post-land sweep requirement). Disclaimed: an ABSENT
# target is NOT penalised — it gets the honest structural read (experimental_ligandable resolves the guard on
# its own). SET literal (NOT a 2-tuple — a 2-string tuple is misread as a (rule_id, verdict) precedence pair
# by the reference-drift guard).
_VALIDATED_INTRINSIC_PROPERTY = {
    # SM active-site / covalent / allosteric — approved directly-acting agents, co-crystal-confirmed pockets
    "BRAF",
    "EGFR",
    "KRAS",
    "ERBB2",
    "ALK",
    "MET",
    "KIT",
    "ABL1",
    "ROS1",
    "RET",
    "FGFR2",
    "PIK3CA",
    "BTK",
    "JAK2",
    "CDK4",
    "CDK6",
    "IDH1",
    "IDH2",
    "FLT3",
    # clinically-validated SURFACE antigens (biologics — ADC / TCE / CAR)
    "MS4A1",
    "CD19",
    "TNFRSF17",
    "DLL3",
    "FOLR1",
    "TACSTD2",
    "CD22",
    "SDC1",
    "CEACAM5",
    "NECTIN4",
}

# structural_ligandability_class tokens that assert a druggable pocket from PREDICTION / HOMOLOGY (AlphaFold
# / computational trusted-axis, or an InterPro-annotated binding site) with NO experimental co-crystal — the
# SHARP over-call. `experimental_ligandable` (co-crystal present) is the guard; disordered_low /
# no_ligandability_signal / insufficient_evidence / data_unavailable are honest negatives, not over-calls.
_PREDICTED_LIGANDABILITY = {"predicted_ligandable", "annotation_ligandable"}


def _g(cards, card_id, field):
    """get_card_field that TOLERATES an absent card (returns None). The composed _synthesis_facet resolves
    only target-intrinsic's 8 EXCLUSIVE cards, so structure-features-static / surfaceome-family-classification
    / target-safety-prioritisation / gnomad-lof-constraint are absent there and get_card_field would raise —
    None-degrade cleanly on both paths."""
    try:
        return get_card_field(cards, card_id, field)
    except KeyError:
        return None


def _intrinsic_actionability_fields(cards) -> dict:
    """Assemble the experimental-vs-predicted / meta-score fields the caveat + provenance read, tolerant of
    the composed-facet card subset (structure/surfaceome/safety/gnomad absent → None)."""
    return {
        "structural_ligandability_class": _g(cards, "structure-features-static", "structural_ligandability_class"),
        "has_experimental_cocrystal": _g(cards, "structure-features-static", "has_experimental_cocrystal"),
        "has_druggable_pocket": _g(cards, "structure-features-static", "has_druggable_pocket"),
        "has_virtual_screen_hit": _g(cards, "structure-features-static", "has_virtual_screen_hit"),
        "pdb_coverage_class": _g(cards, "structure-features-static", "pdb_coverage_class"),
        "alphafold_confidence_class": _g(cards, "structure-features-static", "alphafold_confidence_class"),
        "disordered_fraction": _g(cards, "structure-features-static", "disordered_fraction"),
        "ligandability_disorder_class": _g(cards, "structure-features-static", "ligandability_disorder_class"),
        "n_ligandability_axes": _g(cards, "structure-features-static", "n_ligandability_axes"),
        "is_surface_protein": _g(cards, "surfaceome-family-classification", "is_surface_protein"),
        "surface_protein_family": _g(cards, "surfaceome-family-classification", "family_class"),
        "source_surfy_positive": _g(cards, "surfaceome-family-classification", "source_surfy_positive"),
        "source_hpa_plasma_membrane": _g(cards, "surfaceome-family-classification", "source_hpa_plasma_membrane"),
        "surfaceome_confidence_score": _g(cards, "surfaceome-family-classification", "surfaceome_confidence_score"),
        "gnomad_constraint_class": _g(cards, "gnomad-lof-constraint", "constraint_class"),
        "ot_prioritisation_status": _g(cards, "target-safety-prioritisation", "prioritisation_status"),
        "ot_genetic_band": _g(cards, "target-safety-prioritisation", "genetic_constraint_band"),
        "ot_mouse_ko_band": _g(cards, "target-safety-prioritisation", "mouse_ko_score_band"),
        "go_annotation_class": _g(cards, "gene-ontology-annotation", "annotation_class"),
        "interactome_class": _g(cards, "ppi-interactome", "interactome_class"),
        "tdl_class": _g(cards, "target-development-level", "tdl_class"),
        "measured_bioactivity_class": _g(cards, "measured-potency-tractability", "measured_bioactivity_class"),
        "chembl_n_potent_ligands": _g(cards, "measured-potency-tractability", "chembl_n_potent_ligands"),
    }


def _ot_double_counts(f) -> bool:
    """The OT prioritisation composite DOUBLE-COUNTS the dedicated cards when it is scored and carries a
    genetic-constraint / mouse-KO band (those mirror gnomad-lof-constraint + mouse-ko-phenotype)."""
    return bool(
        f.get("ot_prioritisation_status") == "scored"
        and (f.get("ot_genetic_band") is not None or f.get("ot_mouse_ko_band") is not None)
    )


def _intrinsic_confirmation_caveat(target, f) -> dict | None:
    """VERDICT-INERT: does the actionability-relevant intrinsic signal rest on EXPERIMENTAL confirmation, or
    on a PREDICTION / HOMOLOGY annotation / META-SCORE that over-calls it? Precedence: experimentally-
    confirmed GUARD (milder, false-demote) → predicted/homology SHARP over-call → annotation/score orientation
    → None (nothing to adjudicate → byte-stable). Never read by any rule (there is none)."""
    slc = f.get("structural_ligandability_class")
    sym = (target or "").upper()
    crosswalk = sym in _VALIDATED_INTRINSIC_PROPERTY
    double_counted = _ot_double_counts(f)

    # ── MILDER false-demote GUARD: experimentally-confirmed intrinsic property ──────────────────
    if slc == "experimental_ligandable" or crosswalk:
        basis = []
        if slc == "experimental_ligandable":
            basis.append(
                "experimental co-crystal / strong PDB coverage (structural_ligandability_class=experimental_ligandable)"
            )
        if crosswalk:
            basis.append(
                f"{sym} carries an approved / clinically-validated directly-acting agent "
                "(_VALIDATED_INTRINSIC_PROPERTY crosswalk)"
            )
        note = (
            "The actionability-relevant intrinsic property is EXPERIMENTALLY CONFIRMED ("
            + "; ".join(basis)
            + ") — NOT a prediction / homology over-call, and explicitly NOT demoted (false-demote guard: "
            "BRAF / EGFR / KRAS-G12C class). Note experimental structure ≠ proven DIRECT druggability / "
            "indication-fit (owned by tractability-small-molecule); a solved fold + co-crystal is a "
            "confirmed intrinsic property, not a nomination."
        )
        if double_counted:
            note += (
                " Orientation: the OT prioritisation composite double-counts the dedicated "
                "gnomad-lof-constraint + mouse-ko-phenotype cards — not an independent vote."
            )
        return {"reason": "experimentally_confirmed_intrinsic_property", "basis": basis, "note": note}

    # ── SHARP: predicted / homology-annotated, experimentally UNCONFIRMED (the DRIVER over-call) ──
    predicted_pocket = slc in _PREDICTED_LIGANDABILITY
    predicted_surface = f.get("is_surface_protein") is True and f.get("source_hpa_plasma_membrane") is False
    if predicted_pocket or predicted_surface:
        basis = []
        if predicted_pocket:
            afc = f.get("alphafold_confidence_class")
            disc = f.get("ligandability_disorder_class")
            basis.append(
                f"a druggable-pocket call with NO experimental co-crystal (structural_ligandability_class="
                f"{slc}; has_experimental_cocrystal={f.get('has_experimental_cocrystal')}"
                + (f", AlphaFold confidence={afc}" if afc else "")
                + (f", {disc}" if disc else "")
                + ") — a computational / InterPro-homology pocket, not an "
                "experimentally-confirmed one"
            )
        if predicted_surface:
            basis.append(
                f"a PREDICTED surface/family membership (is_surface_protein=True, family="
                f"{f.get('surface_protein_family')}) with NO experimental HPA plasma-membrane localization "
                "(source_hpa_plasma_membrane=False) — a SURFY / IUPHAR homology call, not confirmed "
                "extracellular topology"
            )
        note = (
            "The actionability-relevant intrinsic signal is PREDICTED / HOMOLOGY-ANNOTATED and "
            "experimentally UNCONFIRMED: " + "; ".join(basis) + ". A family / surfaceome-class membership "
            "assigned by homology (EC-number / domain / HPA class) does not prove function or "
            "druggability — a pseudokinase sits in the kinase family yet is catalytically dead. Treat as "
            "looks-actionable-but-EXPERIMENTALLY-UNCONFIRMED; confirm via co-crystal / fragment screen + "
            "the literature lane (--literature). SM druggability is owned by tractability-small-molecule, "
            "surface fit by surface-modality-fit."
        )
        if double_counted:
            note += (
                " Orientation: the OT prioritisation composite also double-counts the dedicated "
                "gnomad-lof + mouse-ko cards."
            )
        return {"reason": "predicted_structure_or_homology_annotated_unconfirmed", "basis": basis, "note": note}

    # ── META-SCORE / annotation-density only (no experimental OR predicted structural actionability) ──
    signals = []
    if double_counted:
        signals.append(
            "the OT prioritisation composite DOUBLE-COUNTS the dedicated gnomad-lof-constraint + "
            "mouse-ko-phenotype cards (its geneticConstraint / mouseKOScore dims are the same facts)"
        )
    if f.get("gnomad_constraint_class") in ("highly_constrained", "moderately_constrained"):
        signals.append(
            f"gnomAD LoF constraint (constraint_class={f.get('gnomad_constraint_class')}) is a "
            "population-genetic META-SCORE — a safety-liability proxy, not a druggability signal"
        )
    if f.get("go_annotation_class") == "well_annotated" or f.get("interactome_class") == "hub":
        signals.append(
            "high annotation density (well-annotated GO / hub interactome) reflects study depth, not actionability"
        )
    if f.get("tdl_class") in ("Tclin", "Tchem"):
        signals.append(
            f"a drug-development-precedent tier (TDL={f.get('tdl_class')}) is study depth, not "
            "intrinsic drug-worthiness"
        )
    if not signals:
        return None
    note = (
        "No experimentally-confirmed OR predicted structural actionability signal is resolved here; the "
        "intrinsic read rests on META-SCORES / annotation density: " + "; ".join(signals) + ". "
        "SIGNIFICANCE / annotation-completeness ≠ ACTIONABILITY — a well-annotated / high-scoring target is "
        "better-STUDIED, not necessarily a better target, and a genuinely actionable property can be MISSED "
        "or understudied (Tdark = understudied, not adverse; KRAS was called 'undruggable' pre-2013)."
    )
    return {"reason": "annotation_score_or_double_counted", "basis": signals, "note": note}


def _intrinsic_provenance(target, f) -> dict:
    """VERDICT-INERT quorum / provenance summary of the intrinsic dossier's actionability-relevant signals:
    the structure experimental-vs-predicted provenance, the family/surface source provenance, the
    constraint/score meta-layer (+ the OT double-count flag), the annotation-density + tractability-precedent
    layer, and the load-bearing experimentally_confirmed_actionable_property boolean."""
    sym = (target or "").upper()
    return {
        # STRUCTURE / LIGANDABILITY — experimental vs predicted
        "structural_ligandability_class": f.get("structural_ligandability_class"),
        "has_experimental_cocrystal": f.get("has_experimental_cocrystal"),
        "has_druggable_pocket": f.get("has_druggable_pocket"),
        "has_virtual_screen_hit": f.get("has_virtual_screen_hit"),
        "pdb_coverage_class": f.get("pdb_coverage_class"),
        "alphafold_confidence_class": f.get("alphafold_confidence_class"),
        "disordered_fraction": f.get("disordered_fraction"),
        "ligandability_disorder_class": f.get("ligandability_disorder_class"),
        "n_ligandability_axes": f.get("n_ligandability_axes"),
        # FAMILY / SURFACE — homology vs experimental localization
        "surface_protein_family": f.get("surface_protein_family"),
        "is_surface_protein": f.get("is_surface_protein"),
        "source_surfy_positive": f.get("source_surfy_positive"),
        "source_hpa_plasma_membrane": f.get("source_hpa_plasma_membrane"),
        "surfaceome_confidence_score": f.get("surfaceome_confidence_score"),
        # CONSTRAINT / META-SCORE layer (+ the OT composite double-count)
        "gnomad_constraint_class": f.get("gnomad_constraint_class"),
        "ot_prioritisation_status": f.get("ot_prioritisation_status"),
        "ot_composite_double_counts_dedicated_cards": _ot_double_counts(f),
        # ANNOTATION DENSITY / TRACTABILITY PRECEDENT (significance ≠ actionability)
        "go_annotation_class": f.get("go_annotation_class"),
        "interactome_class": f.get("interactome_class"),
        "tdl_class": f.get("tdl_class"),
        "measured_bioactivity_class": f.get("measured_bioactivity_class"),
        "chembl_n_potent_ligands": f.get("chembl_n_potent_ligands"),
        # load-bearing: is the actionability-relevant property EXPERIMENTALLY confirmed?
        "experimentally_confirmed_actionable_property": bool(
            f.get("structural_ligandability_class") == "experimental_ligandable" or sym in _VALIDATED_INTRINSIC_PROPERTY
        ),
        "validated_intrinsic_property_crosswalk_hit": sym in _VALIDATED_INTRINSIC_PROPERTY,
    }


# ── canonical HEADLINE block (verdict + confidence + top tension) — DESCRIPTIVE MODE ─────────────
# target-intrinsic is GATELESS (verdict_fn=None), so there is no gate verdict to headline. The shared
# headline_core builder supports a DESCRIPTIVE MODE (verdict_token=None + descriptive_phrase): the block
# stays well-formed — verdict.call=None, verdict.phrase=the deterministic dominant-signal summary,
# polarity="neutral" — so this descriptive lens gets the SAME verdict+confidence+top-tension shape as a
# gated skill. Confidence is weakest-link over the claim_vector's MODALITY_ROUTING / TRACTABILITY_
# PRECEDENT corroboration; both are critical axes. Verdict-INERT: a one-way projection over the
# already-computed claim_vector / key_signals — it never mints a call (there is none).
_TARGET_INTRINSIC_HEADLINE_SPEC = HeadlineSpec(
    gate="target_intrinsic",
    axis_labels={
        "MODALITY_ROUTING": "domain→modality implication",
        "TRACTABILITY_PRECEDENT": "Pharos/IDG development level",
    },
    axis_keys=("MODALITY_ROUTING", "TRACTABILITY_PRECEDENT"),
    critical_axes=("MODALITY_ROUTING", "TRACTABILITY_PRECEDENT"),
    # No verdict_label (descriptive — no verdict token to phrase); no cross-cutting tension source beyond
    # the claim_vector conflicts + key_signals caveat.
    tension_extra=None,
)


def _build_headline_block(headline: dict) -> dict:
    """Build the canonical Headline block from the already-computed target-intrinsic headline, in
    DESCRIPTIVE MODE (verdict_token=None). The descriptive_phrase is the deterministic dominant-signal
    summary (key_signals.headline); polarity defaults to neutral. Verdict-inert — target-intrinsic mints
    no verdict, so this carries the confidence + top-tension shape without a gate call."""
    ks = headline.get("key_signals") or {}
    return build_headline(
        headline,
        headline.get("claim_vector"),
        headline.get("key_signals"),
        spec=_TARGET_INTRINSIC_HEADLINE_SPEC,
        verdict_token=None,
        descriptive_phrase=ks.get("headline"),
    )


def _headline(cards, fired, verdict_pair, target=None, indication=None):
    """Descriptive target dossier — one field per target-intrinsic sub-axis, built from the declarative
    _HEADLINE_SPEC table. No verdict spine (verdict_fn=None): target-intrinsic evidence informs
    confidence/context, never a nomination (indication-conditioned). A composed consumer reads these
    as target-grain context.

    `target` is threaded in by the dispatcher (signature-introspected — 3-arg callers are byte-identical)
    so the verdict-INERT `intrinsic_confirmation_caveat` can apply its experimentally-confirmed-property
    false-demote GUARD by SYMBOL (BRAF / EGFR / KRAS-G12C), data-blind-tolerant. `indication` is accepted
    for signature parity with the dispatcher/fan-out contract but UNUSED — the dossier is indication-
    INDEPENDENT."""
    hl = {key: get_card_field(cards, cid, field) for key, cid, field in _HEADLINE_SPEC}
    # ── VERDICT-INERT experimental-vs-predicted / annotation INFLATION surfacing (2026-09-04) ──
    # Built from the FULL 20-card standalone roster here (structure-features-static resolved), so this is
    # the SHARP structure-prediction over-call. The mechanism/tumor-presence/tractability analog; the
    # target-intrinsic resolver does not exist (gateless) so this cannot move a verdict.
    _f = _intrinsic_actionability_fields(cards)
    hl["intrinsic_confirmation_caveat"] = _intrinsic_confirmation_caveat(target, _f)
    hl["intrinsic_provenance"] = _intrinsic_provenance(target, _f)
    # verdict-INERT claim-vector projection (10th concrete) — the two target-intrinsic fields that carry
    # a defensible signal (MODALITY_ROUTING / TRACTABILITY_PRECEDENT), the most relevant to hypothesis +
    # modality fit. Both source cards are in the composer entry, so this populates in the COMPOSED profile.
    hl["claim_vector"] = target_intrinsic_claim_vector(hl, cards)
    hl["key_signals"] = target_intrinsic_key_signals(hl, cards)
    # The per-question (data·signal·confidence) LEADING table — verdict-INERT projection over the
    # claim_vector just built (MODALITY_ROUTING/TRACTABILITY_PRECEDENT); best-effort (never abort dossier).
    try:
        hl["question_table"] = target_intrinsic_question_table(hl, cards)
    except Exception as exc:  # noqa: BLE001 — verdict-inert projection; never abort the dossier
        hl.setdefault("_enrichment_errors", {})["question_table"] = f"{type(exc).__name__}: {exc}"
        hl["question_table"] = None
    # Canonical HEADLINE block (DESCRIPTIVE MODE — no gate verdict): a verdict-INERT projection over the
    # claim_vector / key_signals just built. Best-effort (a formatting/read fault must NEVER discard the
    # descriptive dossier already built in `hl`, mirroring the fleet's degrade-on-exception discipline).
    try:
        hl["headline_block"] = _build_headline_block(hl)
    except Exception as exc:  # noqa: BLE001 — verdict-inert projection; never abort the dossier
        hl.setdefault("_enrichment_errors", {})["headline_block"] = f"{type(exc).__name__}: {exc}"
        hl["headline_block"] = None
    # UNIFIED skill_report (docs/UNIFIED_OUTPUT_CONTRACT.md) — target-intrinsic is a GATELESS DESCRIPTIVE
    # dossier (indication-independent; no verdict), so role=descriptive + verdict=None → call=None,
    # polarity=not_scored; the reader-useful content is the honest_phrase + claim_chips. Best-effort +
    # verdict-INERT.
    try:
        _used = [c.get("card_id") for c in (cards or []) if isinstance(c, dict) and not c.get("_missing")]
        _missing = [c.get("card_id") for c in (cards or []) if isinstance(c, dict) and c.get("_missing")]
        hl["skill_report"] = build_skill_report(
            role=ROLE_DESCRIPTIVE,
            verdict=None,
            driving_rule_id=hl.get("driving_rule_id"),
            headline_block=hl.get("headline_block"),
            claim_vector=hl.get("claim_vector"),
            question_table=hl.get("question_table"),
            fired_rule_ids=[f.get("rule_id") for f in (fired or [])],
            cards_used=_used or CARDS,
            cards_missing=_missing,
        )
    except Exception as exc:  # noqa: BLE001 — verdict-inert projection; never abort the dossier
        hl.setdefault("_enrichment_errors", {})["skill_report"] = f"{type(exc).__name__}: {exc}"
        hl["skill_report"] = None
    return hl


def _synthesis_facet(cards, fired, verdict_pair=None, target=None, indication=None):
    """Compact, VERDICT-INERT target-intrinsic facet for the composed synthesis. SELF-CONTAINED — reads
    ONLY this entry's 8 composer cards (the 7 target-intrinsic-EXCLUSIVE cards + the 1 BORROWED
    measured-potency-tractability, also homed under tractability-small-molecule; e.g. domain-modality-
    relevance, target-development-level, measured-potency / GO / interactome the caveat reads), and does
    NOT call _headline (whose _HEADLINE_SPEC
    reads cards HOME'd under other subskills, absent from this entry by design). Carries the descriptive
    claim_vector + its citable atoms + the two class fields + the verdict-INERT intrinsic_confirmation_caveat
    / intrinsic_provenance. target-intrinsic is gateless (verdict_fn=None) — this never moves a verdict.

    `target` / `indication` are signature-introspected by tp_fanout (mirrors the dispatcher's headline_fn
    call) and passed only when declared, so standalone (dispatcher) and composed (fan-out) compute the SAME
    facet. `target` keys the caveat's experimentally-confirmed-property false-demote GUARD by SYMBOL; the
    structural/surfaceome/safety cards are HOME'd elsewhere and absent from this 8-card subset, so the
    structural fields None-degrade and the symbol-guard + annotation tier carry the field here. `indication`
    is UNUSED (indication-INDEPENDENT dossier) — accepted for contract parity."""
    cv = target_intrinsic_claim_vector({}, cards)
    ks = target_intrinsic_key_signals({}, cards)
    _f = _intrinsic_actionability_fields(cards)
    facet = {
        "modality_implication_class": get_card_field(cards, "domain-modality-relevance", "modality_implication_class"),
        "tdl_class": get_card_field(cards, "target-development-level", "tdl_class"),
        "claim_vector": cv,
        "key_signals": ks,
        # VERDICT-INERT experimental-vs-predicted / annotation caveat + provenance — the facet dict is
        # target-intrinsic's fan-out carrier (no _SYNTHESIS_FACET_KEYS tuple), so these MUST be attached here
        # too or the composed profile silently drops them. Degrades gracefully on the 8-card subset (the
        # SHARP structure over-call is fully surfaced in the standalone _headline dossier).
        "intrinsic_confirmation_caveat": _intrinsic_confirmation_caveat(target, _f),
        "intrinsic_provenance": _intrinsic_provenance(target, _f),
        "_facet_note": (
            "Deterministic target-intrinsic facet; claim_vector is a DESCRIPTIVE modality-routing "
            "+ tractability-precedent projection (direction/meaning in the atoms). Gateless — no verdict."
        ),
    }
    # The per-question LEADING table, built from THIS facet's self-contained cv (same reason as the
    # headline_block below — the facet dict is the fan-out carrier, so it must be assembled here too).
    try:
        facet["question_table"] = target_intrinsic_question_table(facet, cards)
    except Exception as exc:  # noqa: BLE001 — verdict-inert projection; never abort the facet
        facet.setdefault("_enrichment_errors", {})["question_table"] = f"{type(exc).__name__}: {exc}"
        facet["question_table"] = None
    # Canonical HEADLINE block (DESCRIPTIVE MODE) — flows to the composed fan-out IDENTICALLY to
    # claim_vector / key_signals (this facet is target-intrinsic's fan-out carrier — the skill exposes NO
    # _SYNTHESIS_FACET_KEYS tuple). Built from THIS facet's self-contained cv/ks (not _headline, which
    # reads cards HOME'd under other subskills, absent from the composer entry). Best-effort / verdict-inert.
    try:
        facet["headline_block"] = _build_headline_block(facet)
    except Exception as exc:  # noqa: BLE001 — verdict-inert projection; never abort the facet
        facet.setdefault("_enrichment_errors", {})["headline_block"] = f"{type(exc).__name__}: {exc}"
        facet["headline_block"] = None
    # UNIFIED skill_report on the FACET (docs/UNIFIED_OUTPUT_CONTRACT.md). target-intrinsic exposes NO
    # _SYNTHESIS_FACET_KEYS tuple — this self-contained facet dict IS its fan-out carrier — so skill_report
    # must be assembled HERE (from the facet's own cv / headline_block) to reach the composed profile, in
    # addition to the _headline path used by the standalone decision. Gateless DESCRIPTIVE → call=None,
    # polarity=not_scored. Best-effort + verdict-INERT.
    try:
        _used = [c.get("card_id") for c in (cards or []) if isinstance(c, dict) and not c.get("_missing")]
        _missing = [c.get("card_id") for c in (cards or []) if isinstance(c, dict) and c.get("_missing")]
        facet["skill_report"] = build_skill_report(
            role=ROLE_DESCRIPTIVE,
            verdict=None,
            headline_block=facet.get("headline_block"),
            claim_vector=facet.get("claim_vector"),
            question_table=facet.get("question_table"),
            fired_rule_ids=[f.get("rule_id") for f in (fired or [])],
            cards_used=_used or CARDS,
            cards_missing=_missing,
        )
    except Exception as exc:  # noqa: BLE001 — verdict-inert projection; never abort the facet
        facet.setdefault("_enrichment_errors", {})["skill_report"] = f"{type(exc).__name__}: {exc}"
        facet["skill_report"] = None
    return facet


if __name__ == "__main__":
    sys.exit(
        run_wired_skill(
            skill_name=SKILL_NAME,
            skill_version=SKILL_VERSION,
            cards=CARDS,
            axis="intracellular_intrinsic",  # rules axis for loading; target-intrinsic emits no verdict
            question=QUESTION,
            verdict_fn=None,  # DESCRIPTIVE dossier — no nomination (indication-conditioned)
            headline_fn=_headline,
            # NET-NEW capsule-driven narrator (generic engine + this lens's LensConfig).
            synthesize_fn=make_synthesize_fn(_LENS),
            # Opt-in --literature: a VERDICT-INERT literature corroboration/contradiction lane (mirrors FR #987 /
            # tumor-selectivity #964 / genomic #982 / on-target-safety #1000 / tractability-SM #1006 /
            # surface-modality-fit #1021 / mechanism #1030 / combination #1040 / cis-coherence #1043). Attaches
            # decision['literature_synthesis'] AFTER the deterministic dossier is composed + feeds the
            # --synthesize narrator; the target-intrinsic query terms (experimental co-crystal / fragment screen /
            # AlphaFold predicted / pseudokinase / homology / localization / gnomAD constraint) live in
            # literature_retrieval.py::_LENS_QUERY_TERMS. INDICATION-INDEPENDENT: retrieval is target-anchored
            # (_indication_phrase(None) → "cancer"). Two-slot / spine-untouched: gateless, so structurally
            # impossible for the lane to alter a verdict. This is the lane that adjudicates per target whether a
            # predicted/homology-annotated actionable property is experimentally confirmed (the
            # intrinsic_confirmation_caveat question) at read time.
            literature_fn=make_literature_fn(_LENS, retrieve_fn=default_retrieve, verify_fn=verify_citations),
            # Skill-level graphics (opt-in --figures): the canonical headline hero (descriptive mode).
            # Additive / display-only; the descriptive dossier is byte-stable without it.
            skill_figures_fn=emit_headline_hero,
            # Signals-first: tuned sub-group reader for the target-intrinsic vocabulary. Verdict-INERT.
            # The reader spec pins WHICH field each source card contributes (order-independent, so a live
            # run and its offline replay bind the same one); the classifier pins the value→tier map.
            subgroup_reader_spec=_TARGET_INTRINSIC_SUBGROUP_READER,
            subgroup_classify=make_value_classifier(_TARGET_INTRINSIC_VALUE_TIERS),
        )
    )
