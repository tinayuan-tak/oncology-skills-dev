---
name: immune-context
description: |
  EFFECTOR-arm skill — the companion to surface-modality-fit. A T-cell engager
  redirects cytotoxic T cells to the antigen, so it can only work where T cells
  are PRESENT. surface-modality-fit answers "is there a surface target?"; this
  answers the orthogonal "is the tumor immune-hot — is there a CD8 effector
  population to redirect?" (IO-target-ID seed note method #2). A TCE needs BOTH.

  Consumes the immune-context card (CIBERSORT LM22 T-cell infiltration from
  gdc-pancanatlas-immune-2018 / Thorsson 2018). Emits immune_context_verdict:
  immune_hot | immune_intermediate | immune_cold | insufficient — from the
  indication's median CD8 T-cell fraction of the leukocyte compartment, anchored
  to pan-cancer quartiles.

  STANDALONE skill, NOT part of surface-modality-fit: immune context is the
  effector axis, orthogonal to surface biology. It composes into the TCE story
  ALONGSIDE surface-modality-fit (e.g. in target-profile), not inside it.

  v1 is per-indication / target-INDEPENDENT (tier: indication) — the immune
  landscape of the indication. The antigen-CONDITIONED read (are the ANTIGEN-HIGH
  patients also T-cell-high?) is a deferred v2 facet.

  Use for questions like "is COADREAD immune-hot enough for a TCE?", "is this
  indication a T-cell desert?"

metadata:
  version: 1.6.1
  owner: ryan.abo@takeda.com
  requires_preflight: true
  environment:
    - AWS_PROFILE=cbg

composition:
  data_mode: derived_read
  phase: [F]
  cards_used:
    - immune-context
    # VERDICT-INERT TME/immune display cards (wired 2026-08-25) — add TME composition + outcome-anchored
    # ICI-response context alongside the CD8 effector call. Fire no rule; the immune_context verdict is
    # byte-stable (gateless skill; verdict is a direct read of immune_context_class).
    - myeloid-compartment-expression-cheng   # pan-cancer tumour-infiltrating myeloid states (suppressive-TME / myeloid-target lens)
    - caf-compartment-expression-luo         # pan-cancer CAF states (stromal lens; stroma-vs-malignant denominator)
    - ici-response-association               # per-gene ICI (anti-PD-1) responder-vs-non-responder association (melanoma-scoped)
    - tcga-til-fraction-saltz                # absolute H&E-DL TIL corroborator of the CIBERSORT CD8 call (Saltz 2018); DISPLAY-ONLY / verdict-inert
    - ici-response-imvigor210                # urothelial ICI-response + desert/excluded/inflamed phenotype (IMvigor210); DISPLAY-ONLY / verdict-inert
  measurement_types_pulled:
    - immune_context
    - sc_tumor_myeloid_state_expression      # DISPLAY-ONLY
    - sc_tumor_caf_state_expression          # DISPLAY-ONLY
    - ici_response_expression                # DISPLAY-ONLY
    - spatial_til_fraction                   # tcga-til-fraction-saltz (absolute H&E-DL TIL); DISPLAY-ONLY corroborator
  rules_scope:
    - surface_intrinsic       # the immune-context rules live on the surface_intrinsic axis (bite_tce)
  synthesis:
    - rule_engine
  output_shape:
    - data_package
  steps_covered: [1, 2, 3, 4, 6]
  status: partial             # v1 per-indication; antigen-conditioned join is v2
---

# immune-context

## What this skill does

- Loads the `immune-context` card (CIBERSORT LM22 leukocyte composition for the
  indication's TCGA study/studies).
- Fires the `immune_context_class` rules on the `surface_intrinsic` axis
  (immune_hot → bite_tce supportive; intermediate → neutral; cold → opposing).
- Resolves `immune_context_verdict` from the fired rule and emits the standard
  data-package (`decision.json` + summary + provenance) with the CD8 / total-T
  fractions + sample counts.

## How Claude invokes this skill

```
export AWS_PROFILE=cbg && \
python3 .../skills/immune-context/scripts/run.py \
  --target <ANY> --indication <INDICATION> --out <OUT_DIR>
```

`--target` is accepted for the wired-skill contract but IGNORED (v1 is
target-independent — the immune landscape is a property of the indication).

## Verified (live, real data)

SKCM → **immune_hot** (CD8 fraction 0.154 — the canonical T-cell-inflamed tumor);
COADREAD / NSCLC / PAAD → immune_intermediate; NSCLC correctly pools LUAD+LUSC
(n=1156); an unmapped indication → data_unavailable (abstain, never a false 'cold').

## Status: partial

Runnable on indications mapping to a TCGA study in the CIBERSORT vocabulary.
**Signals bite_tce only** — an ADC payload is T-cell-independent, so immune context
does not gate it. **Caveats** (from the card): CIBERSORT gives RELATIVE composition,
not absolute density; bulk deconvolution does not resolve spatial T-cell exclusion.
The antigen-conditioned join (T-cell infiltration among antigen-HIGH patients) is
the documented v2 next layer.

## v1.6.0 (2026-09-04) — --literature lane + the bulk-CD8-fraction annotation-INFLATION surface

VERDICT-INERT (the skill is gateless; `immune_context_verdict` is a direct read of `immune_context_class`
— the enrichment is a one-way projection that never moves it, so goldens/replay stay byte-stable):

- **`--literature`** — `make_literature_fn(IMMUNE_CONTEXT)` wired into `run_wired_skill` (Europe PMC →
  PubTator3 grounding + PMID `verify_citations`); refined IMMUNE query terms (immune exclusion /
  inflamed-excluded-desert phenotype / spatial multiplex-IHC / T-cell exhaustion / checkpoint response /
  tertiary lymphoid structure). Attaches `decision['literature_synthesis']` and feeds `--synthesize`.
- **`immune_confirmation_caveat`** — a bulk CIBERSORT LM22 CD8 FRACTION (relative, reference-model-dependent,
  NON-SPATIAL, FUNCTION-BLIND) OVER-CALLS spatial T-cell infiltration. Fires on a POSITIVE bulk read
  (immune_hot / immune_intermediate). Tiers: `bulk_fraction_til_discordant` (the orthogonal absolute H&E-DL
  TIL contradicts — CD8-rich SHARE but low ABSOLUTE density, the PRAD case, sharpest) ·
  `bulk_fraction_spatially_unconfirmed` (no orthogonal absolute-TIL check for this indication — LIHC/KIRC/GBM
  not in the 13 Saltz studies) · `orthogonally_corroborated` (the MILDER false-demote guard — absolute TIL is
  measured & non-contradicting, so a genuinely-inflamed ICI-validated indication like SKCM/MSI-H is spared;
  density confirmed, but localization/function still open). `None` on the immune_cold / insufficient paths.
- **`spatial_localization_caveat`** — names the inflamed-vs-EXCLUDED-vs-desert distinction a bulk fraction
  cannot make (the decisive TCE call, needs spatial / multiplex-IHC). Fires on every positive read.
- **`immune_provenance`** — bulk-CIBERSORT-vs-absolute-TIL quorum; `confirmed_tumor_nest_infiltration` is
  NEVER True from bulk alone.
- **IMMUNE_CONTEXT thesis + `polarity_note`** (was NONE) — the narrator now leads with
  spatially-confirmed-vs-bulk-fraction-annotated CD8 + the exclusion / exhaustion / cohort-median caveats,
  with the TCE surface hand-off to surface-modality-fit as a breadcrumb.

## v1.6.1 (2026-09-04) — VERDICT-INERT display follow-ups

- **Saltz `median_number_of_clusters`** lifted into `immune_provenance.absolute_til_corroboration` — a
  spatial-AGGREGATION statistic (clustered vs dispersed TIL), a first cheap proxy for spatial organization
  the CD8 fraction lacks (still NOT tumour-nest-vs-stroma; needs true multiplex-IHC).
- **Antigen-CONDITIONED join surfaced** (`antigen_conditioned_call` / `cd8_high_minus_low` /
  `antigen_high_immune_context_class`, in the headline + `immune_provenance.antigen_conditioned`) — the
  documented v2 facet the card already computes: are the ANTIGEN-HIGH (targetable) patients ALSO T-cell-high,
  or T-cell-POORER (effector escape)? These are the **ONLY target-DEPENDENT fields** the skill surfaces (the
  verdict stays target-independent), read via a defensive `_cf()` getter, `data_unavailable` when the
  CIBERSORT-barcode↔expression-UUID join is thin. Addresses sub-inflation (d), the cohort-median blind spot.
- **KNOWN GAP (verdict-inert, cross-repo — filed):** the `ici-response-imvigor210` display card keys on the
  genentech eSet's legacy Bioconductor `fData$symbol`, which was NOT run through the gene resolver — so a
  target queried by its MODERN HGNC symbol misses (confirmed: **NECTIN4** absent, its legacy alias **PVRL4**
  present). Fix belongs in the data product (re-derive through the resolver) or the analysis-methods reader
  (alias-fold on read), per the resolver-in-all-ingestion invariant. Verdict-inert (display card only); the
  target-independent verdict is unaffected.
