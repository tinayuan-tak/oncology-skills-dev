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
  immune_hot | immune_intermediate | immune_cold | lymphoid_denominator_unreliable
  | insufficient — from the indication's median CD8 T-cell fraction of the
  leukocyte compartment, anchored to pan-cancer quartiles.

  STANDALONE skill, NOT part of surface-modality-fit: immune context is the
  effector axis, orthogonal to surface biology. It composes into the TCE story
  ALONGSIDE surface-modality-fit (e.g. in target-profile), not inside it.

  The VERDICT is per-indication / target-INDEPENDENT (tier: indication) — the
  immune landscape of the indication. The antigen-CONDITIONED read (are the
  ANTIGEN-HIGH patients also T-cell-high, or T-cell-POORER = effector escape?)
  shipped in v1.6.1 as verdict-INERT display, alongside the v1.7.0 spatial
  co-localization reads — the only target-DEPENDENT fields the skill carries.

  The class token is a pan-cancer RANK of the CD8 SHARE of the leukocyte
  compartment, not an absolute T-cell density; `reference_frame` states the frame
  and confidence drops to `weak` when an orthogonal absolute-TIL or spatial
  platform contradicts it.

  Use for questions like "is COADREAD immune-hot enough for a TCE?", "is this
  indication a T-cell desert?"

metadata:
  version: 1.9.0
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
    - spatial-tumor-normal-colocalization    # T0-4: GeoMx/Xenium/CosMx spatial co-localization — resolves inflamed-vs-excluded (the bulk CD8 fraction can't); VERDICT-INERT facet
  measurement_types_pulled:
    - immune_context
    - sc_tumor_myeloid_state_expression      # DISPLAY-ONLY
    - sc_tumor_caf_state_expression          # DISPLAY-ONLY
    - ici_response_expression                # DISPLAY-ONLY
    - spatial_til_fraction                   # tcga-til-fraction-saltz (absolute H&E-DL TIL); DISPLAY-ONLY corroborator
    - spatial_colocalization                 # T0-4: spatial-tumor-normal-colocalization; VERDICT-INERT inflamed/excluded phenotype
  rules_scope:
    - surface_intrinsic       # the immune-context rules live on the surface_intrinsic axis (bite_tce)
  synthesis:
    - rule_engine
  output_shape:
    - data_package
  steps_covered: [1, 2, 3, 4, 6]
  status: partial             # verdict is per-indication; open = absolute desert threshold + pan-cancer
                              # cuts for the suppression ratios (the lymphoid-denominator guard SHIPPED v1.9.0)
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
does not gate it, and `modality_scope._refinements.bite_tce` rides the `skill_report`
spine (v1.8.0). **Caveats** (from the card): CIBERSORT gives RELATIVE composition,
not absolute density; bulk deconvolution does not resolve spatial T-cell exclusion.
Both are now CHECKED rather than merely conceded — the corroboration ruler demotes
confidence to `weak` when the orthogonal absolute (Saltz H&E-DL TIL) or spatial
(GeoMx/Xenium/CosMx co-localization) platform contradicts the CIBERSORT call.
The antigen-conditioned join (T-cell infiltration among antigen-HIGH patients)
SHIPPED in v1.6.1 and the lymphoid-DENOMINATOR guard in v1.9.0 (in a leukemia or a
normal lymphoid organ CIBERSORT's leukocyte denominator IS the malignant clone, so the
median is WITHHELD and the verdict is `lymphoid_denominator_unreliable` — an absent
MEASUREMENT, distinct from "no cohort"). The open layers are an absolute-density desert
threshold in the analysis-methods classifier and pan-cancer cuts for the suppression
ratios (surfaced in v1.9.0, deliberately non-gating until then).

**Read the class token as a pan-cancer RANK.** `immune_hot`/`immune_cold` are the Q3
(0.113) / Q1 (0.084) cuts of the 33-study distribution, so ~9 studies are hot and ~9
cold BY CONSTRUCTION: clinically-cold PRAD (0.1312) reads `immune_hot` while
ICI-approved LUAD (0.0876) / BLCA (0.1103) read `immune_intermediate`. The
`reference_frame` claim scalar states that frame next to the token.

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

## v1.7.0 (2026-09-10) — T0-4: spatial co-localization on the IMMUNE spine

- **`spatial-tumor-normal-colocalization`** (GeoMx / Xenium / CosMx) wired in, projecting
  `spatial_immune_phenotype` ∈ `inflamed` / `excluded` / `spatial_immune_indeterminate` — the spatial
  resolution of the inflamed-vs-EXCLUDED TCE call the bulk CD8 FRACTION structurally cannot make (the
  exact gap `spatial_localization_caveat` concedes). `data_unavailable` outside the ~6 coloc-covered
  indication families (degrades honestly, never a false 'inflamed').
- The spatial `bite_tce` rules are deliberately NOT in `_RULE_TO_VERDICT`, so the gateless
  `immune_context_verdict` spine stays byte-stable.
- **Open:** a clean three-way inflamed/excluded/DESERT split needs an ABSOLUTE-adjacency desert threshold
  in the analysis-methods classifier — today a stroma-enriched + immune-depleted tumour can class as
  `stromal_niche_colocalized` and the TCE liability is masked.

## v1.8.0 (2026-09-12) — the CARD-DATA RULERS: a non-vacuous confidence ladder + `modality_scope` on the spine

The verdict spine is **byte-stable** (still a direct read of `immune_context_class`); `confidence` and
`modality_scope` MOVE by design.

- **The confidence ruler was VACUOUS (F2).** `_immune_corr` returned the CONSTANT `moderate` for every
  measured indication and the IMMUNE atom never carried a `conflict`, so `headline_block.confidence` and
  `skill_report.confidence` were a constant: `strong` and `weak` were UNREACHABLE and `derive_confidence`'s
  conflict cap + coverage floor were dead code on this single-axis skill. Measured consequence: a
  DISCORDANT PRAD (relative-CD8-hot, absolute-TIL-LOW) read exactly as confidently as a corroborated SKCM.
  It is now an **orthogonal-platform ruler** — `high` = an ABSOLUTE (Saltz H&E-DL TIL) or SPATIAL
  co-localization read AGREES → `strong`; `moderate` = CIBERSORT alone (no orthogonal check for the
  indication); `low` = an orthogonal platform CONTRADICTS → `weak` + a first-class `conflict` naming it.
  A contradiction always beats a corroboration (weakest-link honesty).
- **Spatial EXCLUSION is now a contradiction, not decoration (F4).** `spatial_immune_phenotype ==
  "excluded"` on a POSITIVE bulk read (effectors in the leukocyte compartment but DEPLETED from the
  target-positive malignant neighbourhood — a TCE has nothing to redirect in the nest) contradicts the
  claim AND caps `bite_tce` at `conditional`. **DEMOTE-ONLY:** it never promotes a cold/intermediate read,
  because the coloc products carry no donor floor and the immune rules are `opposing`, never `killer`.
- **`modality_scope` on the `skill_report` SPINE (F1).** It previously rode ONLY the legacy
  `claim_record_shadow`, so `tp_facets._modality_scope_by_axis` reached the TCE arm's one modality
  contribution through its FALLBACK leg and a standalone `decision.json` carried no `bite_tce` read at
  all. Now first-class, like every other modality-speaking skill. The shadow and the spine are pinned to
  agree by test.
- **`reference_frame` claim SCALAR (S2).** `immune_hot` READS as absolute biology but ENCODES a pan-cancer
  PERCENTILE — the cuts ARE the 33-study Q1/Q3, so ~9 studies are hot and ~9 cold by construction. One
  honest line now gauges the CD8 share against its own frame ("a pan-cancer RANK of the CD8 share, NOT an
  absolute T-cell density and NOT a spatial or functional read"), riding `skill_report.claim_scalars`
  losslessly (the `homogeneity` precedent — a STRING, so it renders verbatim in every consumer).
- **One prose source.** Three duplicate discordance-prose builders (run.py-local `_til_discordance_text`,
  the `key_signals` caveat, the claim conflict) collapsed onto ONE `orthogonal_discordance_text` in
  `_skills_common/immune_context_claims.py`, so the claim `conflict`, the `key_signals` caveat and the
  headline `top_tension` are the SAME string and cannot drift. It also now covers the SPATIAL
  contradiction, which the TIL-only builder could not express.
- **Tests:** `tests/test_ruler_and_spine.py` pins all four corroboration tiers as REACHABLE (the
  anti-vacuous-pass guard asserts the ladder SPANS `{strong, moderate, weak, insufficient}` — a collapse
  back to a constant fails there), the demote-only spatial cap, shadow↔spine agreement, and the
  `reference_frame` scalar's honesty claims.
- **Deferred (filed, out of branch scope):** a `reference_frame` entry in `evidence_salience.py`'s
  `immune_context` SALIENCE_SPEC (collides with PR #1309 `feat/cohort-percentile-meters`); the S1 lymphoid
  DENOMINATOR guard, the `n_samples` floor and the CD8:Treg / CD8:M2 ratios (analysis-methods).

## v1.9.0 (2026-09-12) — the six INVISIBLE fields + the fourth class token

Two gaps of the same shape: something the pipeline already produced that no consumer read.

- **Six `summary_fields` were emitted and consumed by NOTHING.** The card has declared and the reader has
  emitted `cd8_hot_sample_fraction`, `cd8_treg_ratio`, `cd8_m2_ratio` and the Treg / M2 / M1 medians since
  card v1.2.0 — and they appeared in no headline, no citable atom, no synthesis facet. **The mirror guard
  cannot catch this**: `test_card_output_emission.py` runs card-DECLARES → reader-must-EMIT, so a field the
  reader emits and no consumer consumes is structurally invisible to it. They are now on the headline, the
  IMMUNE atom, `_SYNTHESIS_FACET_KEYS` and `immune_provenance`, plus **two new frame scalars**:
  - `heterogeneity_frame` — gauges the cohort MEDIAN against the PREVALENCE of samples clearing the *same*
    hot cut. The median is a poor summary of a BIMODAL cohort: MSI-H colorectal (~15% of CRC) is strongly
    infiltrated and the other ~85% is not, so the pooled median reads `immune_intermediate` and the
    population a TCE would actually be developed FOR is invisible in the token. Names the two divergent
    shapes explicitly (a not-hot median with a substantial hot minority; a hot median where fewer than half
    of patients clear the cut).
  - `suppression_frame` — CD8:Treg and CD8:M2 (ratios OF MEDIANS, recomputable from the medians printed
    beside them). Effector PRESENCE is half a TCE read: inflamed-but-SUPPRESSED is a different proposition
    from a bare hot call. ABSTAINS when a suppressor median sits at the LM22 noise floor (an *absent*
    denominator, not a small one — GBM's median Treg of 0.0002 otherwise turned CD8:Treg into 176 in an
    indication whose own class token says `immune_cold`).

  **Both are DESCRIPTIVE and NON-GATING, deliberately.** `0.113`/`0.084` are the 33-study Q3/Q1 of the CD8
  *share*; no equivalent pan-cancer distribution has been derived for a hot-sample prevalence or a
  CD8:suppressor ratio. A demote cut here would be an unanchored number wearing a threshold's clothes —
  derive one from the same 11,373-sample product first. The panel gives an observed CD8:Treg range
  (2.6–13.8), which is a range, not a percentile.

- **`lymphoid_denominator_unreliable` is now a first-class verdict.** It was declared on the card and
  emitted by the reader with **no rule** and no `_RULE_TO_VERDICT` entry, so it fired nothing and fell
  through to a bare `insufficient` **indistinguishable from "no CIBERSORT cohort"** — collapsing the
  specific answer ("there IS a cohort and its reference frame does not apply") onto the generic one, on
  TCE-VALIDATED indications (glofitamab / mosunetuzumab in DLBCL) where that is the whole point. Now: its
  own verdict phrase, **NEUTRAL** polarity (never red — an absent MEASUREMENT is not measured effector
  absence, and a TCE-risk badge here would be backwards), `unmeasured` signal, its own `reference_frame`
  line instead of the bare sentinel, a severity-2 `top_tension`, and `modality_scope` **SILENT** (`na`,
  matching the rule's `bite_tce: neutral`).

  Requires target-contracts #747 (the rule + `applies_when`) and analysis-methods #610 (the indication map),
  which is what makes the guard reachable at all. The verdict spine MOVES for lymphoid indications by
  design; byte-stable everywhere else.

- **Known, not fixed (in-code note + filed).** The sub-group presence ladder (`strong/moderate/weak/absent`
  in `subgroup_derivation._TIERV`) has **no abstention rung**, so both `lymphoid_denominator_unreliable`
  and the long-standing `data_unavailable` fall to `default_classify` and are tiered `absent` — reading
  "could not measure" as "no effectors". Mapping them to a presence tier here would only pick which wrong
  answer to give; the fix is a fifth rung in the shared fleet file, out of this branch's scope.
