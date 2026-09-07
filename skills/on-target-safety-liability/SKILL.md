---
name: on-target-safety-liability
description: |
  Phase-G skill — on-target safety liability from HUMAN GENETICS: gnomAD LoF
  constraint + a 4-leg human-genetics HOLD axis (Open Targets 26.06: gene-burden,
  ClinGen dominant-loss dosage, mouse-KO phenotype, ClinVar pathogenicity) + GTEx
  normal-tissue breadth. (OT target-priority is orienting CONTEXT, verdict-inert —
  not one of the 4 HOLD legs.) The scalar verdict is the HONEST raw WT-loss
  concern; for an activating (GoF) driver the mutant-selective downgrade is
  MODALITY-CONDITIONAL and lives in the per-modality safety verdict
  (safety_verdict_by_modality), not the scalar (resolver role-proxy downgrade
  retired v2.0.0). Plus (data-utilization expansion 2026-08-21)
  DepMap pan-essentiality (broad-tox HOLD), HPA-IHC essential-tissue protein
  (HOLD), ClinGen recessive-only reassurance, and OT drug-warning pharmacovigilance context. 15 cards;
  verdict via the shared declarative resolver (safety.resolver.yaml).

  Question this skill answers:
  Is {target} intolerant of loss-of-function in humans (gnomAD constraint,
  population burden, dosage sensitivity, mouse-KO lethality, germline
  pathogenicity), and what does that imply for on-target safety of a full-KO
  modality (degrader, RNA therapeutic, full-inhibition SM)? For an activating
  (GoF) driver the WT-constraint concern is not eliminated but is MODALITY-
  CONDITIONAL — an allele-selective agent may spare the WT gene — a distinction
  carried by the per-modality safety verdict, not a scalar-verdict downgrade.

  History: graduated not_wired → partial 2026-07-08 (gnomAD leg, PR #79 + the
  gnomad_constraint method, merged AM #41 2026-07-19). Grew 2→15 cards over the
  P5 human-genetics-as-safety build (Slices 1-5, 2026-07-24). Stays `partial`
  because two axes remain placeholder (see status note).

metadata:
  version: 1.18.0    # 1.18.0 (2026-09-07, CASE-009): +VERDICT-INERT pharmacovigilance_scope_caveat (drug_warning_class='no_warning' = no OT-registered FDA warning among engaging drugs, NOT absence of on-target toxicity — mechanism-based dose-limiting tox often not boxed; byte-stable). # 1.17.0 (2026-09-04): +OPTIONAL --literature lane (verdict-INERT LLM literature
                     # synthesis, Europe-PMC-grounded + PMID-verified via _skills_common.literature_synthesis;
                     # run_wired_skill one-liner) mirroring genomic #982 / FR #987 / TP #965 / TS #968.
                     # + VERDICT-INERT signal-surfacing of rich safety sub-fields the capsule projection
                     # ignored: a new PHARMACOVIGILANCE claim axis (on-target FDA warnings + toxicity classes
                     # of target-engaging drugs; confounded CONTEXT, corroboration capped, orients-not-holds),
                     # MOUSE_KO claim evidence += affected organ systems, CLINVAR claim evidence += confident
                     # germline-pathogenic variant count. PHARMACOVIGILANCE stays OUT of the HeadlineSpec
                     # axis_keys so headline_block/confidence/hero + golden-oracle + test_safety_replay
                     # verdict fixtures are BYTE-STABLE. Verdict spine untouched.
  owner: ryan.abo@takeda.com
  requires_preflight: false

composition:
  data_mode: derived_read
  phase: [G]
  cards_used:                          # synced to run.py CARDS (P5 human-genetics + data-util expansion grew this to 15)
    - gnomad-lof-constraint            # Wired 2026-07-08 (Layer 6e)
    - shet-lof-intolerance             # 2026-08-28 — continuous GeneBayes s_het; VERDICT-INERT complement to gnomAD constraint
    - target-safety-prioritisation     # P5 composite safety-prioritisation
    - normal-tissue-liability-gtex     # P5: GTEx normal-tissue liability (re-scoped from the HPA-IHC normal-tissue-liability card, which was re-homed to surface-modality-fit/tumor-presence)
    - alteration-role                  # 2026-07-23 — mechanism CONTEXT for the modality-conditional
                                       # WT-loss reading. Its activating-driver-role-safety-context rule
                                       # is now ORPHAN in the safety resolver (role-proxy downgrade
                                       # retired v2.0.0); functional_direction feeds the per-modality
                                       # safety verdict (small_molecule=conditional) + claim_vector, not
                                       # a scalar-verdict downgrade.
    - clinvar-pathogenicity-safety     # P5: ClinVar germline pathogenicity
    - mouse-ko-phenotype               # P5: IMPC mouse-KO phenotype
    - clingen-dosage                   # P5: ClinGen haploinsufficiency/triplosensitivity dosage
    - gene-burden-safety               # P5: gene-burden safety signal
    - copy-number-distribution         # S1-1 (2026-08-17): was the AMPLIFICATION guard for the retired
                                       # resolver GROUP-0 downgrade. copy-number-amplified-oncogene-safety-
                                       # context is now ORPHAN (role-proxy downgrade retired v2.0.0); near-
                                       # dead composition, retained as amplification context only.
    - functional-gene-state            # PR-4c (2026-08-24): RARELY-ALTERED guard. functional_state_class
                                       # ==rarely_altered fires functional-gene-state-rarely-altered-neutral
                                       # (now ORPHAN in the resolver); the disqualifier moved to the per-
                                       # modality safety verdict — a rarely-altered oncogene (MCL1, pan-
                                       # inhibited) keeps small_molecule=hold so exists-safe-modality does
                                       # NOT clear the WT-loss concern (replaces the retired GROUP-0b guard).
    - pan-cancer-crispr-dependency-distribution  # data-util expansion 2026-08-21 — DepMap pan-essentiality
                                       # BROAD-TOX leg: dependency_class==common_essential fires
                                       # pan-essential-broad-tox-safety-warning → pan_essential_broad_tox_
                                       # concern HOLD. Same card the dependency skill vetoes; SAFETY reading.
    - drug-warning-safety              # (2026-08-21) OT pharmacovigilance CONTEXT (verdict-inert): black-box/withdrawn history of target-engaging drugs
    - onsides-adverse-event-safety     # (2026-08-25) OnSIDES drug-label ADE CONTEXT (verdict-inert DISPLAY): per-MedDRA-term adverse-effect profile (incl. boxed-warning severity) of target-engaging drugs. Fuzzy drug->gene join (~63% match) + per-term grain — context-only, NOT in rules_scope.
    - normal-tissue-liability          # data-util expansion 2026-08-21 — HPA-IHC essential-tissue PROTEIN
                                       # leg (the protein sibling of normal-tissue-liability-gtex, no longer
                                       # only on the surface axis): essential_tissue_flag==present fires
                                       # normal-tissue-protein-liability-safety-warning → normal_tissue_
                                       # protein_safety_concern HOLD.
    # NOTE: protein-surface-evidence was DROPPED from this skill — re-homed to
    # surface-modality-fit (LIVE there as surface_confirmation via the CSPA reader).
  # DATA_TO_SKILL_CONTRACT Rule 3 — the DISTINCT measurement_type claims this skill pulls, ONE per
  # card in cards_used. Every entry is registered in target-contracts/vocabularies/measurement_types.yaml.
  # 2026-08-14 review (S2): corrected from a 4-entry list that had DRIFTED — it declared
  # `normal_tissue_protein_breadth` (WRONG: the GTEx card's real type is normal_tissue_rna_breadth —
  # GTEx is RNA) and `surface_confirmation` (SPURIOUS: that type belonged to protein-surface-evidence,
  # which was DROPPED from this skill and re-homed to surface-modality-fit — see cards_used note), and
  # OMITTED the 5 P5 human-genetics/prioritisation types. test_safety_measurement_types.py now enforces
  # every used card's type is declared so this cannot silently re-drift.
  measurement_types_pulled:
    - gnomad_lof_constraint                    # gnomad-lof-constraint
    - shet_lof_selection                       # shet-lof-intolerance (continuous GeneBayes s_het)
    - target_safety_prioritisation             # target-safety-prioritisation
    - normal_tissue_rna_breadth                # normal-tissue-liability-gtex (GTEx = RNA)
    - alteration_role                          # alteration-role — modality-conditioning CONTEXT (role-proxy downgrade retired v2.0.0)
    - clinvar_germline_pathogenicity_safety    # clinvar-pathogenicity-safety
    - mouse_ko_phenotype_safety                # mouse-ko-phenotype
    - dosage_sensitivity_safety                # clingen-dosage
    - human_genetic_safety                     # gene-burden-safety
    - copy_number_alteration                   # copy-number-distribution — amplification context (guard rule now ORPHAN, GROUP-0 retired)
    - functional_gene_state                    # functional-gene-state — rarely-altered guard (rule now ORPHAN; disqualifier moved to per-modality verdict)
    - crispr_lof_dependency                    # pan-cancer-crispr-dependency-distribution — pan-essential broad-tox (data-util expansion)
    - normal_tissue_protein_breadth            # normal-tissue-liability — HPA-IHC essential-tissue protein (data-util expansion)
    - drug_warning_safety                      # drug-warning-safety — OT pharmacovigilance context (verdict-inert, 2026-08-21)
    - onsides_adverse_event_safety             # onsides-adverse-event-safety — OnSIDES drug-label ADE context (verdict-inert DISPLAY, 2026-08-25)
  # rules_scope = the CARDS whose rules enter the safety resolver (convention: card-ids, matching
  # the sibling skills). 2026-08-14 review (S3): completed from 2 entries — it listed the
  # gnomad-lof-constraint card + the activating-driver-role-safety-context RULE-id (inconsistent),
  # but OMITTED the 4 P5 human-genetics warning legs (gene-burden / clingen-dosage / mouse-ko /
  # clinvar), each of which fires a resolver rung (the human_genetics_safety_concern HOLD). The role-proxy
  # mutant-selective downgrade was RETIRED (resolver v2.0.0, 2026-08-24) → alteration-role / copy-number-
  # distribution / functional-gene-state remain LISTED for provenance but their rules are now ORPHAN in the
  # safety resolver (parked in rule_role_partition.yaml display:); the modality-conditional read moved to
  # the per-modality safety verdict. target-safety-prioritisation + normal-tissue-liability-gtex are
  # ADDITIVE (no resolver rung) — not here.
  rules_scope:
    - gnomad-lof-constraint            # highly/moderately/tolerant/data-unavailable constraint rungs
    - gene-burden-safety               # gene-burden-lof-safety-warning
    - clingen-dosage                   # clingen-dominant-loss-safety-warning
    - mouse-ko-phenotype               # mouse-ko-lethal-safety-warning
    - clinvar-pathogenicity-safety     # clinvar-germline-pathogenic-safety-warning
    - alteration-role                  # activating-driver-role-safety-context — ORPHAN (role-proxy downgrade retired v2.0.0); feeds per-modality verdict
    - copy-number-distribution         # copy-number-amplified-oncogene-safety-context — ORPHAN (GROUP-0 guard retired v2.0.0)
    - functional-gene-state            # functional-gene-state-rarely-altered-neutral — ORPHAN (GROUP-0b guard retired; disqualifier now per-modality)
    - pan-cancer-crispr-dependency-distribution  # pan-essential-broad-tox-safety-warning → pan_essential_broad_tox_concern (data-util expansion 2026-08-21)
    - normal-tissue-liability          # normal-tissue-protein-liability-safety-warning → normal_tissue_protein_safety_concern (data-util expansion 2026-08-21)
    # NOTE: clingen-dosage (above) ALSO fires clingen-recessive-only-safety-favorable →
    # tolerant_reduced_safety_risk reassurance (data-util expansion 2026-08-21) — no separate list entry.
  synthesis:
    - rule_engine
  output_shape:
    - data_package
  steps_covered: [1, 2, 3, 4, 6]
  status: partial
  # WHY still `partial` (2026-08-06 reconcile): the 6 verdict-moving human-genetics
  # legs are LIVE — gnomad-lof-constraint (method AM #41, merged 2026-07-19; NOT
  # missing), + the 5 Open-Targets-26.06 legs (gene-burden, clingen-dosage,
  # mouse-ko-phenotype, clinvar-pathogenicity, target-safety-prioritisation), all
  # with built readers + a v1.x safety.resolver.yaml. Two axes remain incomplete,
  # which keeps the honest ceiling at `partial`: (a) the readers are wired but have
  # not yet fired in an emitted evidence package / been added to a dashboard_spec
  # (framework-health "reader-live-never-fired"); (b) HPA-IHC normal-tissue liability
  # + protein-surface-evidence were RE-HOMED to surface-modality-fit, so this skill's
  # normal-tissue signal is GTEx-RNA breadth (normal-tissue-liability-gtex) only.
---

# on-target-safety-liability — Phase G partial skill

## What this skill does

Given a target, it assembles a WT-loss safety picture across 15 cards and resolves a
scalar `safety_verdict` via the shared declarative resolver
(`resolvers/safety.resolver.yaml`), plus a per-modality `safety_verdict_by_modality`.

**Scalar-verdict-driving legs** (a rung in safety.resolver.yaml — the honest raw WT-loss concern):
  1. **gnomad-lof-constraint** — population LoF intolerance (pLI, LOEUF, mis_z → constraint_class);
     `highly_constrained` (p0), `moderately_constrained` (p5), `tolerant` (p4), data_unavailable (p7).
  2. **pan-cancer-crispr-dependency-distribution** — DepMap pan-essentiality → `pan_essential_broad_tox_concern` (p1).
  3. **normal-tissue-liability** — HPA-IHC essential-tissue protein → `normal_tissue_protein_safety_concern` (p2).
  4–7. **human-genetics HOLD (p3, when_any of 4 legs)**: **gene-burden-safety** (OT rare-variant burden),
     **clingen-dosage** (dominant-loss; recessive-only is a p6 *reassurance*), **clinvar-pathogenicity-safety**
     (germline pathogenic), **mouse-ko-phenotype** (IMPC KO-lethal).

**Per-modality instruments** (feed `safety_verdict_by_modality`, NOT the scalar — the role-proxy scalar
downgrade was RETIRED v2.0.0):
  8. **alteration-role** — GoF/LoF direction: an activating (GoF) role makes the WT-constraint concern
     MODALITY-CONDITIONAL (an allele-selective agent spares WT) → small_molecule=conditional; eligibility.
  9. **copy-number-distribution** / 10. **functional-gene-state** — GROUP-0/0b disqualifiers that block the
     allele-selective escape for amplified (ERBB2/MDM2) / rarely-altered targets.
  gene-burden PROTECTIVE + clingen-recessive-only also condition the per-modality call.

**Context / display (verdict-inert)**: 11. **target-safety-prioritisation** (OT composite priority),
12. **shet-lof-intolerance** (continuous s_het, corroborates constraint), 13. **normal-tissue-liability-gtex**
(GTEx-RNA breadth; emits per-modality signals only), 14. **drug-warning-safety** + 15. **onsides-adverse-event-safety**
(pharmacovigilance CONTEXT; the CASE-009 `pharmacovigilance_scope_caveat` reads these — never a rung).

The rules engine maps each card's categorical to per-modality safety signals (e.g. highly_constrained →
warning for a full-KO modality; tolerant → supportive); the resolver combines them into the scalar
`safety_verdict` + `driving_rule_id` (the raw WT-loss concern); the GoF modality-conditional downgrade is
realised separately in `safety_verdict_by_modality`.

## What this skill does NOT do (yet) — why status is `partial`

- **Not yet exercised end-to-end:** the 15 readers are BUILT and fire live; the
  package-level dashboard_spec exercise is pending.
- **Two normal-tissue legs:** this skill carries BOTH the GTEx-RNA breadth leg
  (`normal-tissue-liability-gtex`, per-modality signals only) AND — since the
  data-utilization expansion (2026-08-21) — the HPA-IHC essential-tissue-protein
  leg (`normal-tissue-liability`), which DOES drive a scalar rung
  (`normal_tissue_protein_safety_concern`, p2). (protein-surface-evidence remains
  homed in surface-modality-fit.)
- **On-target clinical-precedent / trial-outcome:** external trial-outcome feed
  licensing pending — no card in the runtime set.

## Output tree (data_package shape)

```
<out>/
├── decision.json                 # safety_verdict + driving_rule_id + fired rules
├── summary.yaml                  # per-card summary_fields (15 cards)
├── tables/                       # per-card CSVs (emitted for cards that resolve)
└── provenance.yaml               # data_provenance (manifest IDs) + partial-status notice
```

(No `figures/` are emitted by this skill — no figure emitter is wired.)

## Invocation

```
/on-target-safety-liability KRAS
```

Optional flags: `--synthesize` attaches a verdict-INERT LLM narration of the LIABILITY
axes; `--literature` attaches a verdict-INERT, Europe-PMC-grounded + PMID-verified
literature lane (`decision['literature_synthesis']`) and feeds it to the narrator as a
corroboration/contradiction channel — e.g. it surfaces mouse-KO lethality or on-target
clinical toxicity (hematologic DLTs, boxed warnings) that the omics cards are blind to
when no drug is approved / the gene is un-phenotyped. Both NEVER alter the verdict spine.

## Provenance discipline

- `data_provenance`: per-card data_source (derived-manifest ID) + missing
  flag/reason, emitted by the shared writer.
- `skill_status`: `partial` — surfaced in every output so consumers see the
  epistemic ceiling (see the status note above for exactly what is + is not live).

## Roadmap to `wired`

1. Exercise the 15-card set in an emitted evidence package + add to a
   dashboard_spec (clears the "reader-live-never-fired" health flag).
2. Add an on-target clinical-precedent card (external trial-outcome feed
   licensing).
