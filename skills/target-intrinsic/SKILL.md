---
name: target-intrinsic
description: |
  The INDICATION-INDEPENDENT target dossier: "what do we know about target X,
  independent of any cancer?" Fans out over the tier:target cards — identity,
  on-target-safety genetics (the whole P5 axis), protein-class / structure /
  modality biophysics, functional annotation (GO), mechanism + pathway role
  (SIGNOR / Reactome), interactome (STRING / CORUM / BioGRID), domain
  architecture + domain→modality implication, and paralog buffering — the facts
  true of the PROTEIN/GENE regardless of indication. Disease/pan-cancer
  observations (tumor elevation, dependency, mutation frequency, PRISM,
  cell-line abundance) are DELIBERATELY EXCLUDED — they belong to the
  indication-scoped subskills.

  Invoked with --target ALONE (no --indication). A FOCUSED subskill (like
  tumor-presence) giving a standalone portfolio-triage view — "is this target
  worth an indication deep-dive at all?" Its cards feed the indication-scoped
  skills at the CARD level (shared dispatcher); a bundle-level reuse by
  target-profile (compute-once) is a documented future optimization, NOT yet
  wired (target-intrinsic is not in target-profile's sub-skill fan-out).

  DESCRIPTIVE, not nominating (synthesis: none, no verdict): target-intrinsic
  evidence informs confidence/context but never mints a recommendation —
  nomination is inherently indication-conditioned (a target's therapeutic value
  depends on the cancer). This is the one-directional-gate discipline at the
  grain level.

metadata:
  version: 1.2.0
  owner: ryan.abo@takeda.com
  requires_preflight: true
  environment:
    - AWS_PROFILE=cbg

composition:
  data_mode: live_read
  # Cross-cutting: the tier:target cards span presence (A), functional/SL context (C),
  # surface-modality biophysics (F), and on-target-safety genetics (G).
  phase: [A, C, F, G]
  cards_used:
    - target-identity-summary
    - gnomad-lof-constraint
    - gene-burden-safety
    - clingen-dosage
    - clinvar-pathogenicity-safety
    - mouse-ko-phenotype
    - target-safety-prioritisation
    - surfaceome-family-classification
    - structure-features-static
    - shed-ectodomain-liability
    - protein-domains-class
    - target-development-level            # Pharos/IDG TDL (2026-08-10): druggability/novelty tier (Tclin/Tchem/Tbio/Tdark) + family; verdict-inert
    - domain-modality-relevance
    - ppi-interactome
    - gene-ontology-annotation
    - signaling-network-mechanism
    - reactome-pathway-membership
    - paralog-buffering
    - normal-tissue-liability
  # DATA_TO_SKILL_CONTRACT Rule 3 — measurement_type claims pulled. STRICT molecular-intrinsic:
  # properties of the molecule (protein/gene), independent of any cancer. Disease/pan-cancer
  # observations (tumor elevation, dependency, mutation frequency, PRISM, cell-line abundance) are
  # DELIBERATELY EXCLUDED — they live in the disease-context subskills where a pan-cancer roll-up belongs.
  measurement_types_pulled:
    - target_identity
    - gnomad_lof_constraint
    - human_genetic_safety
    - dosage_sensitivity_safety
    - clinvar_germline_pathogenicity_safety
    - mouse_ko_phenotype_safety
    - target_safety_prioritisation
    - surfaceome_family
    - structure_druggability
    - shed_ectodomain_liability
    - protein_domains_class
    - target_development_level          # Pharos/IDG TDL (#322, 2026-08-10) — was in cards_used but missing here
    - domain_modality_relevance
    - ppi_interactome
    - gene_ontology_annotation
    - signaling_network_mechanism
    - reactome_pathway_membership
    - paralog_buffering
    - normal_tissue_protein_breadth
  # No rules_scope + synthesis: none — DESCRIPTIVE dossier, no verdict spine (nomination is
  # indication-conditioned). Headline surfaces the key field per target-intrinsic sub-axis.
  rules_scope: []
  synthesis:
    - none
  output_shape:
    - data_package
  steps_covered: [1, 2, 6]
  status: wired
---

# Micro — Target-Intrinsic Dossier

## What this skill does

- Answers the INDICATION-INDEPENDENT question: what is true of target X as a
  protein/gene, regardless of cancer type. Invoked with `--target` alone.
- Fans out (via the shared run_wired_skill dispatcher, which makes `--indication`
  optional as of 2026-08-05) over the 19 live-wired `tier: target` cards, grouped
  by sub-axis:
  - **identity** — target-identity-summary
  - **on-target-safety genetics (P5)** — gnomAD LoF constraint, gene-burden,
    ClinGen dosage, ClinVar pathogenicity, mouse-KO phenotype, OT safety prioritisation
    (the last is orientation-only — its safety dimension overlaps the dedicated constraint + mouse-KO cards)
  - **protein class / structure / modality biophysics** — surfaceome family, structure
    ligandability, shed-ectodomain liability, normal-tissue protein breadth, Pharos/IDG
    target-development-level (Tclin/Tchem/Tbio/Tdark druggability + novelty tier)
  - **functional annotation** — Gene Ontology (BP/MF/CC)
  - **mechanism / pathway role** — SIGNOR signaling network, Reactome pathway membership
  - **interactome** — STRING network + CORUM complexes + BioGRID physical
  - **domain architecture + domain→modality implication** — UniProt/InterPro domains
    (descriptive) and the interpretive inhibitor-sufficient-vs-removal-required call
  - **paralog buffering** — gene-family redundancy (dependency-hardening context)
- STRICT molecular-intrinsic: pan-cancer DISEASE observations (tumor elevation,
  dependency, mutation frequency, PRISM, cell-line abundance) are DELIBERATELY
  EXCLUDED — they are aggregated cancer behavior owned by the disease-context subskills.
- Emits `decision.json` whose `headline` is the target dossier (one key per sub-axis).

## What this skill does NOT do

- Does NOT take or use an indication. Indication-scoped evidence (tumor-vs-normal
  in a SPECIFIC cancer, subtype landscape, biomarker-stratified dependency) is the
  domain of the (target × indication) subskills — NOT this one.
- Does NOT emit a verdict or nomination. It is descriptive (synthesis: none):
  target-intrinsic facts inform confidence/context; nomination is indication-
  conditioned and owned by target-profile's gate.
- Does NOT recompute anything. Reads the same live derived-product readers the
  composed skills use — no drift.

## Why it exists

~40 of 60 cards are target-grain, but the grain had no composed entrypoint
(target-profile hard-required an indication). This skill (a) gives a standalone
portfolio-triage dossier and (b) is the intended home for the target-intrinsic
bundle so target-profile can eventually compute it ONCE instead of re-deriving
per indication.

NOTE (2026-08-11): (b) is aspirational — target-intrinsic is NOT yet in
target-profile's sub-skill fan-out (`SUB_SKILLS` in target-profile/scripts/run.py),
so the composed skill still re-derives these cards inside its indication-scoped
sub-skills. The reuse that DOES exist today is at the CARD level: the same live
readers / CARD_DISPATCHERS back both this skill and the indication-scoped ones,
so there is no computation drift. Bundle-level compute-once reuse is a tracked
future optimization.

## Invocation

    python skills/target-intrinsic/scripts/run.py --target EGFR --out <dir>
