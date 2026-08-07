---
name: surface-modality-fit
description: |
  Phase-F skill: "For target X in indication Y, does the surface biology
  (topology, surfaceome family, structure pockets, abundance) support a
  biologics modality — ADC-favorable, TCE-favorable, both, or neither?"

  SPLIT 2026-07-14 from the former `tractability-and-modality` skill, which
  merely DISPLAYED these 6 surface cards without letting them change its
  (chemical-genetic) verdict. This skill makes the surface-modality call,
  resolving from the composed `adc-tce-modality-fit` card's `fit_class`.

  status: partial — surfaceome-family + topology + surface-abundance-density readers are
  live (density's method IS built; a derived density product is still pending), while
  structure-features is a hard gap (its derived product is absent from the data-catalog).
  The composed `fit_class` keys on topology+family and emits `neither_viable` (an honest
  negative), NOT `insufficient`, when upstream is thin. `ADC_preferred`/`both_viable` are
  REACHABLE (B1): the topology product does not measure endocytosis, so that unmeasured field
  no longer vetoes the ADC branch (ADC rests on topology; `endocytosis_confidence: unmeasured`
  is surfaced as the honest gap), and curated clinical-ADC antigens
  (internalizing_antigen_targets.yaml) carry a `clinically_internalizing` positive signal. The sibling small-molecule tractability call is `tractability-small-molecule`.

  Use for questions like "does EGFR look ADC-favorable in COADREAD?", "is this
  target TCE-viable topologically?"

metadata:
  version: 1.0.0
  owner: ryan.abo@takeda.com
  requires_preflight: true
  environment:
    - AWS_PROFILE=cbg
  method_version_pins:
    isoform_selective_targets: '1.0.0'

composition:
  data_mode: derived_read
  phase: [F]
  cards_used:
    - surface-topology-and-ptm
    - surfaceome-family-classification
    - structure-features-static
    - surface-abundance-density
    - adc-tce-modality-fit
    - normal-tissue-liability          # HPA IHC off-tumor safety (in run.py CARDS; was doc-stale)
    - copy-number-distribution         # P4 (2026-07-23): genomic amplification → surface antigen-density
                                       # signal (adc/bite_tce/antibody). Same card reads SM/degrader at
                                       # genomic-alteration-profile — Example B. Render/signal facet.
    - rna-protein-concordance-tumor    # (in run.py CARDS; synced 2026-08-05) tumor RNA↔protein concordance
                                       # → ADC/antibody antigen-reality caution (is the protein confirmed?).
                                       # Additive signal facet; verdict byte-stable (fit_class resolves off
                                       # adc-tce-modality-fit). Its P4 modality set widened in the vocab (grain-split).
    - protein-surface-evidence         # (in run.py CARDS; wired 2026-08-06, biologics-augment Phase 1.1)
                                       # CSPA wet-lab surface confirmation — the `measured` surface-residency tier.
                                       # Its rules (protein-surface-confirmed-supportive / protein-not-surface-
                                       # opposing) were silently INERT on live data (CSPA live but no skill composed
                                       # the card — was a measurement_types_pulled intent only). Additive signal
                                       # facet; verdict byte-stable (fit_class resolves off adc-tce-modality-fit).
    - shed-ectodomain-liability        # (in run.py CARDS; wired 2026-08-06, biologics-augment Phase 1.1)
                                       # Clinically-established shed-ectodomain antigen-sink liability (serum-marker
                                       # crosswalk). Its F3 rules (shed-ectodomain-clinical/secretome-proxy-opposing,
                                       # OPPOSING not killer) existed + were axis-wired but UNREACHABLE — no skill
                                       # composed the card. Additive signal facet; verdict byte-stable.
                                       # E3 (2026-08-07): + MEASURED Olink conditioned-media facet (measured_shed_class);
                                       # media_shed_high fires shed-ectodomain-measured-media-opposing. Panel bounded +
                                       # secretome-preselected → not_on_secreted_panel non-informative. Still byte-stable.
    - tumor-scrna-celltype-expression  # (in run.py CARDS; wired 2026-08-06, biologics-augment Phase 3.2)
                                       # Within-tumor antigen HOMOGENEITY via single-cell Census (tce_homogeneity_class
                                       # facet). TCE program-killer = antigen heterogeneity (antigen-low cells escape).
                                       # Its surface rules (sc-homogeneity-uniform-tce-supportive / -heterogeneous-tce-
                                       # opposing) fire on the homogeneity facet; the card's PRIMARY sc_expression_class
                                       # stays presence-axis. LIVE for COADREAD+NSCLC. Additive; verdict byte-stable.
    - modality-therapeutic-window      # (in run.py CARDS; wired 2026-08-06, biologics-augment window arc)
    - pmhc-presentation                # (in run.py CARDS; wired 2026-08-07, enrichment E1) peptide-centric
                                       # HLA presentation (benign immunopeptidome). Reaches INTRACELLULAR targets
                                       # via pMHC (TCR-mimetic TCE), invisible to surface presence. bite_tce rules;
                                       # benign-atlas = normal-presentation safety denominator. Additive; byte-stable.
                                       # Clean-antigen THERAPEUTIC WINDOW: tumor / max-essential-normal TPM, modality-
                                       # tiered (strict/TCE default). Surfaces the CEACAM5 paradox neither selectivity
                                       # nor normal-tissue-liability makes. Rules fire on window_class (essential_tissue_
                                       # liability → bite_tce opposing, adc NEUTRAL = ADC-vs-TCE discriminator). Emits
                                       # both essential + full-normal ratios (Theme-1). Additive; verdict byte-stable.
    - mutation-stratified-surface      # (in run.py CARDS; wired 2026-08-07, enrichment E4-A2) patient-selection-aware
                                       # surface presence: is the antigen elevated in a driver's MUTANT tumor subset
                                       # (a biologics handle on the mutant patient population the gene-level window
                                       # dilutes away)? v1 = KRAS×NSCLC. Rule mutant-up-surface-antigen-supportive fires
                                       # adc/bite_tce/antibody supportive on mutant_up_surface. Additive; byte-stable.
  # DATA_TO_SKILL_CONTRACT.md Rule 3 — the PULL half: this gate-view declares the
  # measurement_type CLAIMS it needs to answer "is this target biologics-viable", independent of
  # which datasets provide them. Keys resolve against target-contracts/vocabularies/
  # measurement_types.yaml. During migration cards_used (above) is the live wiring; this list is
  # the machine-checkable pull-intent a resolver will match on (migration step 5 — resolver matches
  # on type, falling back to card_id/product_id). surface_confirmation is now LIVE (2026-07-21): the
  # protein-surface-evidence card resolves via the merged CSPA reader (cspa-surface-confirmation-per-
  # uniprot-v1 on S3, dispatcher wired) — CSPA is the `measured` tier; HPA-IHC remains a future adjunct.
  # exactly the first-class visible state Rule 3 describes.
  measurement_types_pulled:
    - pmhc_presentation                # (2026-08-07, E1) peptide-centric HLA presentation; bite_tce
    - surface_confirmation
    - surface_topology
    - surfaceome_family
    - surface_density
    - adc_tce_modality_fit
    - normal_tissue_protein_breadth    # HPA IHC off-tumor safety (normal-tissue-liability)
    - rna_protein_concordance          # (backfill 2026-08-06) rna-protein-concordance-tumor has been in run.py
                                       # CARDS since the 2026-08-05 orphan-fix, but its type was never added
                                       # here → test_cards_used_types_are_a_subset_of_pulled failed pre-existing.
    - copy_number_alteration           # P4 (2026-07-23): genomic amplification → surface antigen-density lens
    - shed_ectodomain_liability        # (2026-08-06, biologics-augment Phase 1.1) shed-ectodomain antigen-sink
                                       # (serum-marker crosswalk); OPPOSING-not-killer on adc/bite_tce/antibody.
                                       # surface_confirmation (above) is now a FIRING card (protein-surface-evidence),
                                       # not just a pulled intent — CSPA wired into CARDS same change.
    - sc_tumor_celltype_expression     # (2026-08-06, biologics-augment Phase 3.2) single-cell within-tumor antigen
                                       # homogeneity (tce_homogeneity_class facet); TCE-escape signal, adc/bite_tce.
    - modality_window                  # (2026-08-06, biologics-augment window arc) tumor / max-essential-normal TPM
                                       # therapeutic-window ratio, modality-tiered; adc/bite_tce/antibody.
    - mutation_stratified_surface      # (2026-08-07, E4-A2) mutation-stratified surface window — antigen elevated in
                                       # a driver's MUTANT subset (biologics handle on mutant patients); adc/bite_tce/antibody.
  rules_scope:
    - all
  synthesis:
    - rule_engine
  output_shape:
    - data_package
  steps_covered: [1, 2, 3, 4, 6]
  optional_lenses:
    - modality
  status: partial
---

# surface-modality-fit

## What this skill does

- Fetches the 5 surface/structure cards via the compose-dashboard live-reader
  dispatchers.
- Fires the `surface_intrinsic` rule subset.
- Resolves a `surface_modality_verdict` from the composed `adc-tce-modality-fit`
  `fit_class` — the card that fuses topology / family / structure / density
  into a modality call.
- Emits `decision.json` with the verdict + `driving_rule_id`, the `fit_class`,
  and the contributing surface categoricals.

## Verdict resolution (rank-ordered, first match wins)

  1. `adc-preferred-supportive` → `adc_preferred`
  2. `tce-preferred-supportive` → `tce_preferred`
  3. `both-viable-supportive` → `both_viable`
  4. `neither-viable-killer` → `neither_viable`
  5. `isoform-dependent-modality-suppression` → `isoform_dependent_undefined`
  6. else → `insufficient` (honest — surface inputs data_unavailable)

## Orthogonality facet (E7, 2026-08-07 — VERDICT-INERT)

The headline carries an `orthogonality` sub-key: a meta-facet scoring how many
INDEPENDENT lines of surface-biology evidence converge. Of the 13 composed cards only
~5 measure independent things; the scorer collapses the 6-card presence cluster
(CSPA / topology / density / family / RNA-proxy / CN) into ONE dimension, so a target is
not double-counted for measuring presence six ways. Five dimensions —
`presence_accessibility`, `selectivity_window`, `shed_liability` (inverted: not-shed =
supportive), `effector_homogeneity`, `pmhc_presentation` — each resolve to
supportive / opposing / abstain. Coverage and support are reported SEPARATELY
(`n_dimensions_covered` vs `n_dimensions_supportive`): an abstaining dimension is a
data-coverage gap, never an opposing vote (honest-coverage doctrine). `orthogonality_class`
∈ broadly_corroborated (≥4) / moderately (3) / narrowly (2) / single_axis (1) /
uncorroborated (covered, none supportive) / insufficient_coverage (nothing measurable).
It is emitted in the headline and CANNOT move the verdict — the resolver keys only on
`fit_class` rungs (pinned by test_orthogonality_is_verdict_inert). A stronger biologics
call rests on 4-5 orthogonal axes, not one; this makes that explicit without collapsing
it into the verdict.

## Status: partial

Per-product / per-input state (reconciled 2026-08-06 against framework-health):
- LANDED + reader-live: `surfaceome-family-classification` (S3), `topology-predictions`
  (surface-topology-and-ptm, S3), `surface-abundance-density` (method IS built — reads CPTAC
  per-cohort + a 181-row calibrated antigen-density ladder; what's missing is a *derived* density
  product, not the method), `rna-protein-concordance-tumor`, `copy-number-distribution` (additive
  P4 antigen-density signal), `normal-tissue-liability`.
- HARD GAP: `structure-features-static` — the method exists, but its derived product
  `pdb-alphafold-structure-features-per-uniprot-v1` is NOT in the data-catalog (ingest-first). The
  reader always degrades to `no_structure`. NOTE: structure is a PASSTHROUGH here — it does not feed
  `fit_class` (see below).

How `fit_class` actually resolves today (the composed `adc-tce-modality-fit` card): it keys on
TOPOLOGY + SURFACEOME-FAMILY only — density and structure are consumed but do NOT move the class.
When upstream is thin the composed card emits `neither_viable` (an honest negative), NOT
`data_unavailable`/`insufficient` — the `fit_class` field is never marked `_missing`, so a rule always
fires and the resolver's `insufficient` default is effectively unreachable.

ENDOCYTOSIS / ADC-REACHABILITY (B1, 2026-08-06 — was previously unreachable): the topology product
carries NO endocytosis-motif data (the field is hardcoded null). Previously `endo_high_conf = ... or 0`
collapsed that null to 0, so the unmeasured field VETOED the ADC branch → `ADC_preferred`/`both_viable`
were structurally unreachable. FIXED: the dispatcher now reads endocytosis raw, distinguishes UNMEASURED
(abstain — a coverage gap must not veto) from MEASURED, and satisfies the ADC internalization term via
EITHER a measured motif signal, OR curated clinical-ADC precedent (internalizing_antigen_targets.yaml —
approved/late-clinical ADC antigens: ERBB2/TROP2/NECTIN4/FOLR1/…), OR abstention when genuinely unmeasured
+ uncurated. `endocytosis_confidence` (now emitted; card-declared) labels the state: `clinically_internalizing`
(curated) / `high|moderate|low` (measured) / `unmeasured` (honest gap). So an ADC-favorable call on a novel
target is flagged internalization-UNVERIFIED, while a known ADC antigen carries a positive signal. The full
endocytosis-motif prediction pipeline (YXXΦ/NPXY on the cytoplasmic tail × AlphaFold accessibility) remains
the first-principles long-term upgrade.

Note on CSPA: `surface_confirmation` (CSPA reader, `cspa-surface-confirmation-per-uniprot-v1`) is
LIVE in the framework and pulled as a measurement_type, but `protein-surface-evidence` is NOT in this
skill's runtime `cards_used` — so within surface-modality-fit, CSPA is a declared pull-intent, not a
firing card.

## How Claude invokes this skill

1. Extract `target` (HGNC symbol) + `indication` (OncoTree code).
2. Pick a durable `out` directory (avoid `/tmp`).
3. Run:
   ```
   export AWS_PROFILE=cbg && \
   python3 /home/sagemaker-user/rnd-computational-biology-oncology-claude-oncology-skills/skills/surface-modality-fit/scripts/run.py \
     --target <TARGET> --indication <INDICATION> --out <OUT_DIR>
   ```
4. Read `<OUT_DIR>/decision.json`; present `surface_modality_verdict` +
   `driving_rule_id`. If `insufficient` due to `data_unavailable`, say so
   plainly (surface data not yet landed).
