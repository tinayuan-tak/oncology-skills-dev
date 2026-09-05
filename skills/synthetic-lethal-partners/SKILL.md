---
name: synthetic-lethal-partners
description: |
  [RETIRED FROM THE target-profile FAN-OUT 2026-08-20] Consolidated into combination-and-vulnerability for composition (its cards compose there under the combination_vulnerability dimension + relational claim_vector). Still runnable standalone; do NOT re-add to SUB_SKILLS.
  Gate-C step 2 skill — curated synthetic-lethal partner annotation from the
  PUBLISHED SynLethDB v3 (CC-BY-4.0). Consumes the synthetic-lethal-partners card
  (derived synlethdb-sl-partners-per-gene-v1).

  Question this skill answers:
  Does {target} have a curated synthetic-lethal partner, and is the evidence
  experimental — such that a pooled pan-cancer non-dependent CRISPR read may be a
  CONTEXT-CONDITIONAL false negative (the target is required only once the partner is
  altered: SMARCA2←SMARCA4-loss, ARID1B←ARID1A)?

  ANNOTATION, not measurement: an experimentally-supported SL partner SUPPRESSES the
  dependency non_dependent veto → insufficient (nomination_verdict_gate.yaml
  veto_suppressors). It NEVER nominates (a curated SL relationship is not a measured
  dependency) and NEVER suppresses pan_essential. A computational-only partner is
  surfaced but does NOT suppress a veto.

  COMPLEMENTS functional-requirement's paralog-buffering (the DUA-measured, intra-gene-
  family self-rescue signal). This is the published/citable layer catching ARBITRARY
  partner-conditional SL that intra-family measurement cannot see. Runs as its OWN
  sub_skill (`synthetic_lethal_partners`) — a sub_skill cannot emit both the dependency
  veto AND its own suppressor, so the SL signal rides a separate sub_skill exactly as
  the biomarker-stratified suppressor rides genomic_alteration.

  Biology-first output; modality-independent primary verdict.

  v1.1.0 (2026-09-05, literature-and-claims arc; run.py SKILL_VERSION): NEW SYNTHETIC_LETHAL_PARTNERS narrator
  lens + --synthesize; a --literature lane (published SL literature — a GENUINE 2nd channel, UNLIKE the
  literature-native literature-context skill, since a curated SynLethDB edge is orthogonal to the primary
  literature); and a verdict-INERT sl_partner_confidence_caveat (3-tier: computational_only_sl_edge /
  curated_sl_edge_context_unconfirmed / validated_established_synthetic_lethal false-demote guard) +
  sl_partner_provenance QUORUM. The caveats REUSE the shared _skills_common/sl_crosswalks validated-SL corpus
  and gate on the already-emitted sl_partner_* headline fields (NO new card-field read), so the resolver
  verdict + golden snapshots are UNTOUCHED (verdict-INERT).
composition:
  data_mode: derived_read
  phase: [C]                        # Gate-C (dependency) — SL-partner annotation is a Gate-C veto-suppressor
  status: deprecated               # RETIRED FROM THE FAN-OUT 2026-08-20 — consolidated into combination-and-vulnerability. Runnable standalone; NOT composed. (see description note)
  cards_used:
    - synthetic-lethal-partners
  # DATA_TO_SKILL_CONTRACT Rule 3 — measurement_type claims pulled (annotation type; suppresses a
  # veto to insufficient, never nominates).
  measurement_types_pulled:
    - synthetic_lethal_partner
  rules_scope:
    - sl-experimental-partner-context-conditional
    - sl-computational-partner-informational
    - sl-no-partner-neutral
    - sl-data-unavailable-insufficient
  synthesis:
    - rule_engine
  output_shape:
    - data_package
  steps_covered: [1, 2, 3, 4, 6]
---

# synthetic-lethal-partners

See the description frontmatter. Emits `sl_partner_verdict` ∈
{`has_experimental_sl_partner` | `has_computational_sl_partner` |
`no_curated_sl_partner` | `data_unavailable` | `insufficient`}. The
`has_experimental_sl_partner` verdict is the gate-C veto-suppressor trigger.
