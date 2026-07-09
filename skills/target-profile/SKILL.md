---
name: target-profile
description: |
  Composed target-profile skill: "Give me the full biology + tractability +
  mutation + prevalence picture of target X in indication Y, with narrative
  synthesis." Fans out to the 5 wired question-answering skills:
    - tumor-presence
    - tumor-selectivity
    - functional-requirement
    - mutation-profile
    - tractability-and-modality
    - patient-population-and-access
  Collects each sub-verdict, then invokes Tier-3 structured LLM synthesis
  (Bedrock tool_choice-forced) for executive_summary + tension_analysis +
  recommendation. Emits `target_profile.md` + `nomination.json` +
  provenance.

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
    - expression-distribution
    - expression-tumor-vs-adjacent
    - tumor-vs-normal-selectivity
    - protein-presence-cptac                   # Layer 6h addition (Phase A)
    # Phase C (requirement)
    - pan-cancer-crispr-dependency-distribution
    - pan-cancer-rnai-dependency-distribution
    - crispr-rnai-dependency-concordance
    - dependency-lineage-selectivity
    - paralog-buffering                        # Layer 6h addition (Phase C-adjacent)
    # Phase E (mutation profile + differentiation)
    - mutation-type-counts
    - mutation-stratified-dependency
    - mutation-hotspot-frequency
    - co-mutation-and-mutual-exclusivity       # Layer 6h addition (Phase E)
    # Phase D (mechanism)
    - signaling-network-mechanism              # Layer 6h addition (Phase D)
    # Phase F (tractability + modality)
    - prism-compound-activity
    - prism-crispr-concordance
    - dependency-predictability
    - surface-topology-and-ptm                 # Layer 6h addition (Phase F)
    - surfaceome-family-classification         # Layer 6h addition
    - structure-features-static                # Layer 6h addition
    - surface-abundance-density                # Layer 6h addition
    - adc-tce-modality-fit                     # Layer 6h addition (composed)
    - surfaceome-cohort-ranking                # Layer 6h addition (target-scan)
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

- Runs the 6 wired question-answering skills in parallel (all data-package
  producers): tumor-presence, tumor-selectivity, functional-requirement,
  mutation-profile, tractability-and-modality, patient-population-and-access.
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

- Does NOT run compose-dashboard's 16-card Macro pipeline. This is a
  composed compositional skill, not Macro. Compose-dashboard remains
  available for the full evidence_package.json artefact.
- Does NOT synthesize LLM output for the categorical spine — that stays
  deterministic (rule-fired). LLM only writes narrative + high-level
  recommendation.

## Optional lenses

- `--modality <M>` — projects each sub-skill's fired rules onto a
  modality lens (small_molecule / degrader / adc / bite / antibody).
  Sub-verdicts unchanged; the LLM synthesis reshapes the executive-summary
  language to lens-emphasized reasoning.
- `--therapeutic-hypothesis "<text>"` — free-text clinical framing (line-
  of-therapy, patient state, clinical goal). Reshapes the executive-
  summary and argument prioritization to hypothesis-relevant evidence.
  Sub-verdicts unchanged.

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
   supplied by the user.
4. Read `<OUT_DIR>/target_profile.md` and present the executive summary
   inline; offer the full nomination.json for detail.
