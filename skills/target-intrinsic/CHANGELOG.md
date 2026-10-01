# Changelog — target-intrinsic


`SKILL_VERSION` in [scripts/run.py](scripts/run.py) is the current semver; the dated
development history below was migrated verbatim from the former inline `SKILL_VERSION`
comment. Newest first.

## 1.6.1 (2026-09-12): _TARGET_INTRINSIC_VALUE_TIERS COMPLETED against the live card vocabulary — measured_bioactivity_class (potent/weak/no_measured_activity), shed_liability_class (clinically_shed/secretome_proxy_shed/not_shed_membrane_retained), pdb_coverage_class af_only/none, no_high_confidence_interactors, explicit data_unavailable->absent. Two live EGFR signals (potent_measured_ligand, secretome_proxy_shed) were being flipped to `absent` by the lens-blind default_classify fallback. VERDICT-INERT (--figures sub-group panel only; spine/claim_vector/narrator byte-stable). + data-driven vocabulary-coverage guard (test_subgroup_value_tiers.py), 20/20 re-frozen egfr.yaml, and a full-decision golden.

## 1.6.0 (2026-09-04): --literature lane (run_wired_skill make_literature_fn(TARGET_INTRINSIC); None-indication path via _indication_phrase->'cancer') + VERDICT-INERT experimental-vs-predicted INFLATION surfacing (intrinsic_confirmation_caveat = an AlphaFold/computational or homology-annotated actionable property [predicted_ligandable / annotation_ligandable pocket, predicted-surface, family-by-homology] over-calling a co-crystal-confirmed one, OR a meta-score / OT-composite double-count; experimentally_confirmed_intrinsic_property false-demote guard, pan-target gene-level BRAF/EGFR/KRAS-G12C; intrinsic_provenance quorum). Built on BOTH _headline AND the self-contained _synthesis_facet (fan-out carrier). TARGET_INTRINSIC thesis extend + ADD polarity_note. Gateless (verdict_fn=None) — dossier byte-stable.

## 1.5.1 (2026-09-02): _TARGET_INTRINSIC_VALUE_TIERS aligned to live card vocab (dead keys removed; positive subgroup signals no longer flip to `absent`). Verdict-INERT (subgroup --figures only).

## 1.4.0 (2026-08-28): capsule-driven narrator via generic engine. Verdict-INERT.

## 1.3.0 (2026-08-27): tuned signals-first sub-group reader. Verdict-INERT.   # stamped into provenance.yaml — MUST equal SKILL.md metadata.version
