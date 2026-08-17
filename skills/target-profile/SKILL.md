---
name: target-profile
description: |
  Composed target-profile skill: "Give me the full biology + tractability +
  mutation + prevalence picture of target X in indication Y, with narrative
  synthesis." Fans out (in parallel, in-process) to the 10 wired
  question-answering skills:
    - tumor-presence
    - tumor-selectivity
    - functional-requirement
    - synthetic-lethal-partners         (SL co-dependency / combination discovery)
    - mechanism-and-pharmacology
    - genomic-alteration-profile        (SNV + copy-number + fusion [LIVE, additive])
    - differentiation-landscape
    - tractability-small-molecule       (small-molecule chemical-genetic half)
    - surface-modality-fit              (biologics ADC/TCE half)
    - on-target-safety-liability
  Collects each sub-verdict, then invokes Tier-3 structured LLM synthesis
  (Bedrock tool_choice-forced) for executive_summary + tension_analysis +
  recommendation. Emits `target_profile.md` + `nomination.json` +
  provenance.

  RESTRUCTURED 2026-07-14 (scope deep-dive): tractability-and-modality SPLIT
  into tractability-small-molecule + surface-modality-fit; mutation-profile
  REFRAMED to genomic-alteration-profile; patient-population-and-access DELETED
  (prevalence folded into genomic-alteration-profile); surfaceome-cohort-ranking
  DROPPED from the fan-out (per-indication scan, not a per-target skill).

  Every LLM-produced field is tagged with `_source: llm_synthesized`,
  `_model_id`, and `_prompt_hash`. Sub-verdicts (deterministic, rule-
  fired) are stored in distinct schema slots from LLM narrative — the
  audit spine is invariant even if narrative drifts between runs.

  Use for full biologist-oriented profile requests: "profile TP53 in
  COADREAD", "give me the full picture on KRAS in colorectal cancer",
  "should we nominate MET in NSCLC?"

metadata:
  version: 1.0.0
  owner: ryan.abo@takeda.com
  requires_preflight: true
  environment:
    - AWS_PROFILE=cbg
    - AWS_REGION=us-east-1  # Bedrock

composition:
  data_mode: derived_read
  phase: [A, B, C, D, E, F, G, H, K]           # EXTENDED 2026-07-08: added D, E, G
  cards_used:
    # Phase A + B (presence + selectivity)
    - cellline-rna-distribution
    - tumor-rna-vs-adjacent
    - tumor-vs-normal-selectivity
    - tumor-protein-abundance-cptac                   # Layer 6h addition (Phase A)
    # Phase C (requirement)
    - pan-cancer-crispr-dependency-distribution
    - pan-cancer-rnai-dependency-distribution
    - crispr-rnai-dependency-concordance
    - dependency-lineage-selectivity
    - paralog-buffering                        # Layer 6h addition (Phase C-adjacent)
    # Phase A/E (genomic-alteration-profile: SNV + copy-number + fusion)
    - mutation-type-counts
    - mutation-stratified-dependency
    - mutation-hotspot-frequency
    - copy-number-distribution                 # 2026-07-14 CN axis wired
    - fusion-rearrangement-landscape           # LIVE (tcga-fusion-consensus-v1); additive signal-only
    - co-mutation-and-mutual-exclusivity       # (differentiation-landscape)
    - pathway-node-leverage                    # WS3 (differentiation-landscape): comparative node-leverage; verdict-inert soft context
    # Phase D (mechanism)
    - signaling-network-mechanism              # Layer 6h addition (Phase D)
    # Phase F (tractability-small-molecule: chemical-genetic)
    - prism-compound-activity
    - prism-crispr-concordance
    - dependency-predictability
    # Phase F (surface-modality-fit: biologics ADC/TCE)
    - surface-topology-and-ptm
    - surfaceome-family-classification
    - structure-features-static
    - surface-abundance-density
    - adc-tce-modality-fit
    # (surfaceome-cohort-ranking DROPPED from fan-out 2026-07-14 — per-indication scan)
    # Phase G (safety)
    - gnomad-lof-constraint                    # Layer 6h addition (Phase G)
  rules_scope:
    - all
  synthesis:
    - rule_engine
    - structured_llm
  output_shape:
    - target_profile
  steps_covered: [1, 2, 3, 4, 5, 6]
  optional_lenses:
    - modality
    - therapeutic_hypothesis
  status: wired
---

# target-profile

## What this skill does

- Runs the 10 wired question-answering skills in parallel (all data-package
  producers): tumor-presence, tumor-selectivity, functional-requirement,
  synthetic-lethal-partners, mechanism-and-pharmacology, genomic-alteration-profile,
  differentiation-landscape, tractability-small-molecule, surface-modality-fit,
  on-target-safety-liability.
- Collects each sub-verdict + fired rules + card summaries.
- Invokes Bedrock (Opus by default via env `ANTHROPIC_MODEL`) with a
  structured tool_use forcing the LLM to emit:
  - `executive_summary` — 3-5 sentence overall picture
  - `tension_analysis` — where sub-verdicts disagree + why
  - `top_arguments_for` — up to 5 strongest positive points
  - `top_arguments_against` — up to 5 strongest negatives
  - `overall_recommendation` — nominate / hold / veto (enum)
  - `confidence` — high / medium / low / insufficient (enum)
- Emits:
  - `target_profile.md` — rendered narrative with clearly-tagged LLM
    sections + rule-derived sub-verdict tables
  - `nomination.json` — structured version of the full profile
    (sub_verdicts + LLM output + provenance)
  - `provenance.yaml` — audit anchor

## What this skill does NOT do

- Does NOT run compose-dashboard's dashboard_spec-driven card dispatch. This is a
  fan-out-over-sub-skills composer with a cross-gate nomination — a legitimately
  distinct composition pattern. (It CAN now emit an `evidence_package.json`
  envelope of its own composed verdict — see Output modes below — but does not
  consume a dashboard_spec.)
- Does NOT synthesize LLM output for the categorical spine — that stays
  deterministic (rule-fired). LLM only writes narrative + high-level
  recommendation.

## Output modes (`--emit`)

`--emit` selects the output shape over the SAME deterministic verdict spine:

- `--emit nomination` (default) — the biologist-facing narrated profile:
  `nomination.json` + `target_profile.md` + `target_profile.html` + `provenance.yaml`
  (+ figures), with the Tier-3 LLM narrative.
- `--emit evidence-package` — the machine-facing artifact: a deterministic, **LLM-free**
  `evidence_package.json` envelope in the same shape compose-dashboard emits (validates
  against `target-contracts/schemas/evidence_package.schema.json`). It implies
  `--no-synthesis` + `--no-figures` and writes **no** nomination.json / md / html. Its
  `synthesis` block is a SUPERSET: target-profile's nomination fields
  (`recommendation_gate` / `confidence_tier` / `deciding_axis`) + a compose-dashboard-style
  `primary_gate_verdict` + `additional_gate_verdicts` split + the full per-sub-skill
  `sub_verdicts` — all sourced from each sub-skill's shared `CompositionResult`, with no
  re-resolution. `governance.data_mode` is `exploratory` (live, unpinned, not
  concurrence-reviewed).

## Optional lenses

- `--modality <M>` — projects each sub-skill's fired rules onto a
  modality lens (small_molecule / degrader / adc / bite / antibody).
  Sub-verdicts unchanged; the LLM synthesis reshapes the executive-summary
  language to lens-emphasized reasoning.
- `--therapeutic-hypothesis "<text>"` — free-text clinical framing (line-
  of-therapy, patient state, clinical goal). Reshapes the executive-
  summary and argument prioritization to hypothesis-relevant evidence.
  Sub-verdicts unchanged.

## Fast modes (deterministic spine, no LLM)

The deterministic verdict spine — sub-verdicts, the recommendation gate, the positive tier, the
deciding axis, the gate scorecard, and the biomarker/subtype facets — is computed independently
of the Tier-3 LLM synthesis. These flags skip verdict-inert work and leave that spine
**byte-identical** to a full run:

- `--verdict-only` — umbrella fast mode (implies `--no-synthesis` + `--no-figures`). Emits
  `nomination.json` + a narrative-free `target_profile.md` + `provenance.yaml` with **no Bedrock
  call** and no figure/panel render. Use for CI, iteration, and re-runs where only the auditable
  nomination is needed. `nomination.json` marks `llm_synthesis._synthesis_skipped: true`, and the
  report shows a note in place of the narrative.
- `--no-synthesis` — skip only the LLM synthesis tail (keep figures).
- `--no-figures` — skip only figure/HTML rendering (keep synthesis).

## How Claude invokes this skill

When called as `/target-profile`, Claude should:

1. Extract `target` + `indication`. Optionally extract `modality`
   and/or `therapeutic-hypothesis` from the user's natural-language
   prompt if named.
2. Pick an `out` directory (default `/tmp/target-profile/{target}-{indication}`).
3. Run:
   ```
   export AWS_PROFILE=cbg && \
   python3 /home/sagemaker-user/rnd-computational-biology-oncology-claude-oncology-skills/skills/target-profile/scripts/run.py \
     --target <TARGET> --indication <INDICATION> --out <OUT_DIR>
   ```
   Add `--modality <M>` and/or `--therapeutic-hypothesis "<text>"` if
   supplied by the user. Add `--emit evidence-package` when the user wants the
   machine-facing `evidence_package.json` envelope instead of the narrated profile
   (deterministic, LLM-free — no `AWS_PROFILE`/Bedrock needed).
4. Read `<OUT_DIR>/target_profile.md` and present the executive summary
   inline; offer the full nomination.json for detail. (For `--emit
   evidence-package`, read `<OUT_DIR>/evidence_package.json`.)
