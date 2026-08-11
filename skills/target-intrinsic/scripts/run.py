#!/usr/bin/env python3
"""target-intrinsic — the INDICATION-INDEPENDENT target dossier.

Answers "what do we know about target X, independent of any cancer?" — the facts that are true of the
PROTEIN/GENE regardless of indication: identity, on-target-safety genetics (the whole P5 axis is
target-grain), protein-class / structure / modality biophysics, functional annotation (GO), mechanism
+ pathway role (SIGNOR / Reactome), interactome (STRING / CORUM / BioGRID), domain architecture +
domain→modality implication, and paralog buffering. These are the `tier: target` cards (target-contracts)
— a grain that already exists on cards but had no composed entrypoint: target-profile hard-required an
indication, so target-intrinsic facts were scattered across nominally indication-scoped subskills and
recomputed identically for every (target × indication) run. STRICT molecular-intrinsic: pan-cancer
DISEASE observations (tumor elevation, dependency, mutation frequency, PRISM, cell-line abundance) are
DELIBERATELY EXCLUDED — they are aggregated cancer behavior, owned by the disease-context subskills.

This is a FOCUSED subskill (like tumor-presence / tumor-selectivity) that the composed skills reuse —
NOT a nominating gate. It is DESCRIPTIVE: verdict_fn=None. Nomination is inherently indication-
conditioned (a target's therapeutic value depends on the cancer), so a target-intrinsic view informs
confidence/context but never mints a recommendation — the one-directional-gate discipline, applied at
the grain level.

Invoked with --target ALONE (no --indication): the dispatcher (2026-08-05) makes --indication optional
and passes a pan-cancer sentinel that these tier:target readers ignore.

CARDS — the live-wired tier:target roster, grouped by target-intrinsic sub-axis:
"""

from __future__ import annotations

import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILLS_DIR))

from _skills_common.dispatcher import run_wired_skill
from _skills_common import get_card_field


SKILL_NAME = "target-intrinsic"
SKILL_VERSION = "1.2.0"   # 2026-08-11 — prod-readiness pass: fixed the catalog-visible description (dropped
                          # the EXCLUDED pan-cancer/dependency/SL advertising), count corrected to 19 cards
                          # (target-development-level #322 landed but prose still said 18), measurement_types
                          # parity, and corrected the target-profile bundle-reuse claim (not wired — card-level
                          # reuse only). Descriptive, no verdict.
                          # (1.1.0 2026-08-08 surfaced domain-modality-relevance in the dossier headline.)

CARDS = [
    # STRICT MOLECULAR-INTRINSIC only: properties TRUE OF THE MOLECULE (protein/gene), independent of
    # any cancer. Disease/pan-cancer observations (tumor elevation, dependency, mutation frequency,
    # PRISM, cell-line abundance) DELIBERATELY EXCLUDED — those are aggregated cancer behavior, not
    # molecular-intrinsic facts, and remain in the disease-context subskills (tumor-presence,
    # functional-requirement, genomic-alteration-profile, etc.) where a pan-cancer roll-up belongs.
    # --- IDENTITY ------------------------------------------------------------------------------
    "target-identity-summary",           # canonical id, family, aliases
    # --- GERMLINE GENETICS & CONSTRAINT (properties of the GENE; the P5 safety axis) -----------
    "gnomad-lof-constraint",             # germline LoF intolerance (pLI/LOEUF)
    "gene-burden-safety",                # rare-variant burden safety signal
    "clingen-dosage",                    # ClinGen haploinsufficiency / triplosensitivity
    "clinvar-pathogenicity-safety",      # germline pathogenic-variant burden
    "mouse-ko-phenotype",                # IMPC mouse-KO lethal/developmental phenotypes
    "target-safety-prioritisation",      # OT composite prioritisation score. ORIENTATION-ONLY (verdict-inert):
                                         # its SAFETY dimension overlaps gnomad-lof-constraint + mouse-ko-phenotype
                                         # (the dedicated cards); retained for its tractability/precedence dimensions,
                                         # not to be read as a standalone safety fact. (prod-readiness review 2026-08-11)
    # --- PROTEIN CLASS / STRUCTURE / BIOPHYSICS (properties of the PROTEIN) ---------------------
    "surfaceome-family-classification",  # surface protein family + membership (protein-class proxy)
    "structure-features-static",         # fold / pockets / ligandability (structure-intrinsic)
    "shed-ectodomain-liability",         # circulating soluble ectodomain (biophysical property)
    # --- FUNCTIONAL ANNOTATION (Gene Ontology: what it does / where it is / what processes) -----
    "gene-ontology-annotation",          # GO BP/MF/CC term membership (experimental-evidence-flagged)
    # --- MECHANISM / PATHWAY ROLE (the molecule's place in signaling) ---------------------------
    "signaling-network-mechanism",       # SIGNOR/OmniPath upstream regulators + downstream effectors, MoA class
    "reactome-pathway-membership",       # Reactome pathway/geneset MEMBERSHIP + top-level rollup (distinct from directed edges above)
    # --- INTERACTOME (physical/functional interactions + complex membership) --------------------
    "ppi-interactome",                   # STRING high-confidence functional network + CORUM complex membership
    # --- DOMAIN ARCHITECTURE / PROTEIN CLASS (curated UniProt features) --------------------------
    "protein-domains-class",             # FT DOMAIN architecture + UniProt-keyword protein class
    "target-development-level",          # Pharos/IDG TDL (2026-08-10): druggability/novelty tier
                                         # (Tclin/Tchem/Tbio/Tdark) + family. VERDICT-INERT target-intrinsic facet.
    "domain-modality-relevance",         # INTERPRETIVE domain→modality facet (inhibitor_sufficient vs
                                         # removal_required_scaffolding, e.g. RIPK1). tier:target, verdict-inert.
                                         # Card + method (methods/domain_modality_relevance) + dispatcher all LIVE
                                         # (#264); was declared in SKILL.md cards_used but MISSING from run.py CARDS
                                         # (declared-not-consumed drift) AND unread in _headline (resolved invisibly).
                                         # 2026-08-08: added to CARDS + surfaced in _headline.
    # --- PARALOGS (gene-family redundancy — a genomic-intrinsic property) -----------------------
    "paralog-buffering",                 # sequence paralogs + buffering (dependency-hardening context)
    # --- NORMAL (non-disease) EXPRESSION --------------------------------------------------------
    "normal-tissue-liability",           # HPA normal-tissue protein breadth (baseline, non-tumor)
]

QUESTION = ("What is known about {target} INDEPENDENT of indication — its identity, on-target-safety "
            "genetics, protein-class/structure/modality biophysics, functional annotation, mechanism + "
            "pathway role, interactome, domain architecture + domain→modality implication, and paralog "
            "buffering?")


# Declarative dossier field-map: (headline_key, card_id, card_field), grouped by target-intrinsic
# sub-axis. This is the SINGLE SOURCE for both _headline AND the drift guard — the test AST-parses
# this table's card_ids, so a card added to CARDS but never surfaced here is caught structurally
# (target-intrinsic is descriptive: this table is the ONLY place a card's signal reaches output).
_HEADLINE_SPEC = [
    # identity
    ("target_symbol",                 "target-identity-summary",          "resolved_hgnc_symbol"),
    ("target_ensembl_id",             "target-identity-summary",          "resolved_ensembl_id"),
    # safety genetics (P5)
    ("gnomad_constraint_class",       "gnomad-lof-constraint",            "constraint_class"),
    ("clingen_dosage_class",          "clingen-dosage",                   "dosage_sensitivity_class"),
    ("clinvar_pathogenic_class",      "clinvar-pathogenicity-safety",     "clinvar_pathogenic_class"),
    ("gene_burden_safety_class",      "gene-burden-safety",               "burden_safety_class"),
    ("mouse_ko_phenotype_class",      "mouse-ko-phenotype",               "ko_phenotype_class"),
    # target-safety-prioritisation is ORIENTATION-ONLY (safety dim overlaps constraint + mouse-KO)
    ("target_safety_prioritisation",  "target-safety-prioritisation",     "prioritisation_status"),
    # protein class / structure / biophysics
    ("surface_protein_family",        "surfaceome-family-classification", "family_class"),
    ("is_surface_protein",            "surfaceome-family-classification", "is_surface_protein"),
    ("structure_pocket_call",         "structure-features-static",        "hotspot_pocket_adjacency_call"),
    ("shed_liability_class",          "shed-ectodomain-liability",        "shed_liability_class"),
    # functional annotation (Gene Ontology)
    ("go_annotation_class",           "gene-ontology-annotation",         "annotation_class"),
    ("go_n_terms_total",              "gene-ontology-annotation",         "n_go_terms_total"),
    ("go_n_biological_process",       "gene-ontology-annotation",         "n_biological_process"),
    ("go_n_molecular_function",       "gene-ontology-annotation",         "n_molecular_function"),
    ("go_n_cellular_component",       "gene-ontology-annotation",         "n_cellular_component"),
    # mechanism / pathway role
    ("network_class",                 "signaling-network-mechanism",      "network_class"),
    ("n_upstream_regulators",         "signaling-network-mechanism",      "n_upstream_regulators"),
    ("n_downstream_effectors",        "signaling-network-mechanism",      "n_downstream_effectors"),
    # pathway / geneset membership (Reactome)
    ("pathway_class",                 "reactome-pathway-membership",      "pathway_class"),
    ("pathway_count",                 "reactome-pathway-membership",      "pathway_count"),
    ("top_level_pathways",            "reactome-pathway-membership",      "top_level_pathways"),
    # domain architecture / protein class (UniProt curated)
    ("protein_features_class",        "protein-domains-class",            "protein_features_class"),
    ("n_domains",                     "protein-domains-class",            "n_domains"),
    ("domain_architecture",           "protein-domains-class",            "domain_architecture"),
    ("protein_class",                 "protein-domains-class",            "protein_class"),
    # Pharos/IDG Target Development Level (2026-08-10) — druggability/novelty tier (verdict-inert)
    ("tdl_class",                     "target-development-level",         "tdl_class"),
    ("tdl_target_family",             "target-development-level",         "target_family"),
    ("tdl_novelty_score",             "target-development-level",         "novelty_score"),
    # domain→modality implication (INTERPRETIVE sibling of protein-domains-class): inhibitor-sufficient
    # vs removal-required (degrader/scaffolding). Verdict-inert (target-intrinsic is descriptive); the
    # heuristic returns indeterminate for a multi-domain enzyme (v0.2.0), curated RIPK1 →
    # removal_required_scaffolding.
    ("modality_implication_class",    "domain-modality-relevance",        "modality_implication_class"),
    ("modality_implication_basis",    "domain-modality-relevance",        "modality_implication_basis"),
    ("modality_scaffolding_function", "domain-modality-relevance",        "scaffolding_function"),
    ("modality_implication_context",  "domain-modality-relevance",        "modality_context"),
    # interactome (STRING network + CORUM complexes)
    ("interactome_class",             "ppi-interactome",                  "interactome_class"),
    ("n_high_confidence_interactors", "ppi-interactome",                  "n_high_confidence_interactors"),
    ("n_corum_complexes",             "ppi-interactome",                  "n_corum_complexes"),
    ("in_protein_complex",            "ppi-interactome",                  "in_protein_complex"),
    # paralogs (gene-family redundancy)
    ("paralog_buffering_class",       "paralog-buffering",                "paralog_buffering_class"),
    ("n_paralogs_annotated",          "paralog-buffering",                "n_paralogs_annotated"),
    ("strongest_paralog_symbol",      "paralog-buffering",                "strongest_paralog_symbol"),
    # normal (non-disease) expression
    ("normal_tissue_breadth_class",   "normal-tissue-liability",          "normal_tissue_breadth_class"),
]


def _headline(cards, fired, verdict_pair):
    """Descriptive target dossier — one field per target-intrinsic sub-axis, built from the declarative
    _HEADLINE_SPEC table. No verdict spine (verdict_fn=None): target-intrinsic evidence informs
    confidence/context, never a nomination (indication-conditioned). A composed consumer reads these
    as target-grain context."""
    return {key: get_card_field(cards, cid, field) for key, cid, field in _HEADLINE_SPEC}


if __name__ == "__main__":
    sys.exit(run_wired_skill(
        skill_name=SKILL_NAME,
        skill_version=SKILL_VERSION,
        cards=CARDS,
        axis="intracellular_intrinsic",   # rules axis for loading; target-intrinsic emits no verdict
        question=QUESTION,
        verdict_fn=None,                   # DESCRIPTIVE dossier — no nomination (indication-conditioned)
        headline_fn=_headline,
    ))
