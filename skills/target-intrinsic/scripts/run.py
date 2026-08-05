#!/usr/bin/env python3
"""target-intrinsic — the INDICATION-INDEPENDENT target dossier.

Answers "what do we know about target X, independent of any cancer?" — the facts that are true of the
PROTEIN/GENE regardless of indication: identity, on-target-safety genetics (the whole P5 axis is
target-grain), surface/structure/modality biophysics, pan-cancer presence + dependency breadth, SL
partners. These are the `tier: target` cards (target-contracts) — a grain that already exists on cards
but had no composed entrypoint: target-profile hard-required an indication, so target-intrinsic facts
were scattered across nominally indication-scoped subskills and recomputed identically for every
(target × indication) run.

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
SKILL_VERSION = "1.0.0"

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
    "target-safety-prioritisation",      # OT composite target-safety context
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
    # --- PARALOGS (gene-family redundancy — a genomic-intrinsic property) -----------------------
    "paralog-buffering",                 # sequence paralogs + buffering (dependency-hardening context)
    # --- NORMAL (non-disease) EXPRESSION --------------------------------------------------------
    "normal-tissue-liability",           # HPA normal-tissue protein breadth (baseline, non-tumor)
]

QUESTION = ("What is known about {target} INDEPENDENT of indication — its identity, on-target-safety "
            "genetics, surface/structure/modality biophysics, pan-cancer presence + dependency "
            "breadth, and synthetic-lethal partners?")


def _headline(cards, fired, verdict_pair):
    """Descriptive target dossier — surfaces the key field per target-intrinsic sub-axis. No verdict
    spine (verdict_fn=None): target-intrinsic evidence informs confidence/context, never a nomination
    (nomination is indication-conditioned). A composed consumer reads these as target-grain context."""
    g = lambda cid, f: get_card_field(cards, cid, f)  # noqa: E731
    return {
        # identity
        "target_symbol":                 g("target-identity-summary", "resolved_hgnc_symbol"),
        "target_ensembl_id":             g("target-identity-summary", "resolved_ensembl_id"),
        # safety genetics (P5)
        "gnomad_constraint_class":       g("gnomad-lof-constraint", "constraint_class"),
        "clingen_dosage_class":          g("clingen-dosage", "dosage_sensitivity_class"),
        "clinvar_pathogenic_class":      g("clinvar-pathogenicity-safety", "clinvar_pathogenic_class"),
        "gene_burden_safety_class":      g("gene-burden-safety", "burden_safety_class"),
        "mouse_ko_phenotype_class":      g("mouse-ko-phenotype", "ko_phenotype_class"),
        "target_safety_prioritisation":  g("target-safety-prioritisation", "prioritisation_status"),
        # protein class / structure / biophysics
        "surface_protein_family":        g("surfaceome-family-classification", "family_class"),
        "is_surface_protein":            g("surfaceome-family-classification", "is_surface_protein"),
        "structure_pocket_call":         g("structure-features-static", "hotspot_pocket_adjacency_call"),
        "shed_liability_class":          g("shed-ectodomain-liability", "shed_liability_class"),
        # functional annotation (Gene Ontology)
        "go_annotation_class":           g("gene-ontology-annotation", "annotation_class"),
        "go_n_terms_total":              g("gene-ontology-annotation", "n_go_terms_total"),
        "go_n_biological_process":       g("gene-ontology-annotation", "n_biological_process"),
        "go_n_molecular_function":       g("gene-ontology-annotation", "n_molecular_function"),
        "go_n_cellular_component":       g("gene-ontology-annotation", "n_cellular_component"),
        # mechanism / pathway role
        "network_class":                 g("signaling-network-mechanism", "network_class"),
        "n_upstream_regulators":         g("signaling-network-mechanism", "n_upstream_regulators"),
        "n_downstream_effectors":        g("signaling-network-mechanism", "n_downstream_effectors"),
        # pathway / geneset membership (Reactome)
        "pathway_class":                 g("reactome-pathway-membership", "pathway_class"),
        "pathway_count":                 g("reactome-pathway-membership", "pathway_count"),
        "top_level_pathways":            g("reactome-pathway-membership", "top_level_pathways"),
        # domain architecture / protein class (UniProt curated)
        "protein_features_class":        g("protein-domains-class", "protein_features_class"),
        "n_domains":                     g("protein-domains-class", "n_domains"),
        "domain_architecture":           g("protein-domains-class", "domain_architecture"),
        "protein_class":                 g("protein-domains-class", "protein_class"),
        # interactome (STRING network + CORUM complexes)
        "interactome_class":             g("ppi-interactome", "interactome_class"),
        "n_high_confidence_interactors": g("ppi-interactome", "n_high_confidence_interactors"),
        "n_corum_complexes":             g("ppi-interactome", "n_corum_complexes"),
        "in_protein_complex":            g("ppi-interactome", "in_protein_complex"),
        # paralogs (gene-family redundancy)
        "paralog_buffering_class":       g("paralog-buffering", "paralog_buffering_class"),
        "n_paralogs_annotated":          g("paralog-buffering", "n_paralogs_annotated"),
        "strongest_paralog_symbol":      g("paralog-buffering", "strongest_paralog_symbol"),
        # normal (non-disease) expression
        "normal_tissue_breadth_class":   g("normal-tissue-liability", "normal_tissue_breadth_class"),
    }


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
