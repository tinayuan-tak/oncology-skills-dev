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
  version: 1.1.0
  owner: ryan.abo@takeda.com
  requires_preflight: true
  environment:
    - AWS_PROFILE=cbg

composition:
  data_mode: derived_read
  phase: [F]
  cards_used:
    - immune-context
  measurement_types_pulled:
    - immune_context
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
