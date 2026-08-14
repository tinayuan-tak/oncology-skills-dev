---
name: translational-readiness
description: |
  PARTIAL SKILL (graduated 2026-08-14, scientific-gap #1) — was a pure placeholder; now composes the
  target-model-availability card (public HCMI patient-derived model coverage per indication), the
  "can I preclinically validate a nomination in this indication?" leg of translational readiness.

  Question this skill answers (partially): How translationally ready is target X in indication Y —
  are patient-derived (HCMI organoid / next-generation cancer) models available to validate it?

  DESCRIPTIVE (emits no verdict — like target-intrinsic): model availability is translational CONTEXT
  that informs confidence, not a nomination gate.

  STILL PARTIAL: the PD-assay, imaging-tracer, and INTERNAL Takeda models (PDX/organoid/GEMM) legs
  remain un-wired (those catalogs are not in data-catalog). The genotype-MATCHED refinement (does an
  available model carry THIS target's alteration?) is a v2 (HCMI WXS MAF join).

metadata:
  version: 1.1.0
  owner: ryan.abo@takeda.com
  requires_preflight: true
  environment:
    - AWS_PROFILE=cbg

composition:
  data_mode: derived_read
  phase: [J]
  cards_used:
    - target-model-availability   # scientific-gap #1: per-indication HCMI patient-derived model coverage;
                                  # INDICATION-level, target-independent; VERDICT-INERT translational context
  measurement_types_pulled:
    - model_availability          # target-model-availability (cohort-grain, HCMI-CMDC-DR45 derived)
  rules_scope:
    - none                        # DESCRIPTIVE skill (verdict_fn=None) — no resolver rung
  synthesis:
    - none
  output_shape:
    - data_package
  steps_covered: [1, 2]
  status: partial
---

# translational-readiness — partial

## Status: partial (graduated from placeholder 2026-08-14)

This skill was a pure placeholder. It now composes ONE real translational signal — the public HCMI
patient-derived model-availability card — and honestly flags the remaining un-wired legs.

When invoked, it emits `decision.json` with:

- `status: "partial"`
- a DESCRIPTIVE headline (no verdict — `verdict_fn=None`):
  - `model_availability_class`: `deep_model_coverage` (>=50 models) / `moderate_model_coverage`
    (15-49) / `sparse_model_coverage` (<15) / `data_unavailable`
  - `n_patient_derived_models`: count of distinct HCMI models crosswalked to the indication
  - `primary_site_breakdown`: provenance of which GDC histologies mapped in
  - `model_source`: `HCMI-CMDC-DR45`
- `partial_status_note`: the still-un-wired legs.

## What this skill wires

- **target-model-availability** (scientific-gap #1, lighter-v1): per-indication HCMI (Human Cancer
  Models Initiative) patient-derived model coverage. INDICATION-level, target-INDEPENDENT translational
  cohort context — "how many patient-derived models exist to validate a target here?" Backed by
  `hcmi-model-availability-per-indication-v1` (376 models across COADREAD / PAAD / NSCLC / GC).

## Still un-wired (honest coverage gaps)

- **Internal Takeda models registry** (PDX/organoid/GEMM) — not catalogued in data-catalog.
- **PD-assay catalog** — not wired.
- **Imaging-tracer catalog** — not wired.
- **Genotype-matched model coverage** (does an available model carry THIS target's alteration?) — the
  v2 refinement (HCMI WXS aliquot-MAF join on top of the availability crosswalk).

## How Claude invokes this skill

1. Extract `target` (HGNC symbol, uppercase) + `indication` (OncoTree code).
2. Pick a durable `out` directory (avoid `/tmp`).
3. Run:
   ```
   export AWS_PROFILE=cbg && \
   python3 /home/sagemaker-user/rnd-computational-biology-oncology-claude-oncology-skills/skills/translational-readiness/scripts/run.py \
     --target <TARGET> --indication <INDICATION> --out <OUT_DIR>
   ```
4. Read `<OUT_DIR>/decision.json`; present `model_availability_class` +
   `n_patient_derived_models` inline, and surface `partial_status_note` for the un-wired legs.
