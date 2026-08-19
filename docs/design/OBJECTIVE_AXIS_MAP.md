# The Objective → Axis → Card → Skill Map (canonical)

**Status:** canonical (v1.0.0). Machine-readable source of truth:
[`vocabularies/target_profiling_axes.yaml`](../../vocabularies/target_profiling_axes.yaml).
This document is the human-readable companion + the durable card→skill map.

**Supersedes** three drifted generations that disagreed on their letter schemes:
the 8-gate scaffold doc (`CARD_ARCHITECTURE_DECISION.md`), `gate_coverage.yaml` v2
(content **ported** here, equivalence-checked), and the per-skill `SKILL.md composition.phase`
letters (**retired**). The ontology keys on the stable, letter-free `short` name and carries a
`legacy_letters` crosswalk so the old letters resolve but no longer govern.

---

## 1. The objective decomposition

The objective — *"should we nominate target X in indication Y?"* — decomposes into questions in
two bands. **Necessity** = *is this real, actionable biology?* **Sufficiency** = *will it become a
drug in a given modality?* Each question has a **home skill** and a framework coverage standing.

| Band | Question (`short`) | Home skill | Coverage | legacy (8-gate / phase) |
|---|---|---|---|---|
| necessity | **expression** — expressed/present? | tumor-presence | captured | A / A |
| necessity | **selectivity** — tumor-vs-normal window? | tumor-selectivity | captured | B / B |
| necessity | **dependency** — functional requirement? | functional-requirement | partial | C / C |
| necessity | **mechanism** — network/MoA hook? | mechanism-and-pharmacology | partial | D / D |
| necessity | **genomic_alteration** — how altered, which class? | genomic-alteration-profile | captured | A(overloaded) / E |
| sufficiency | **tractability_sm** — small-molecule druggable? | tractability-small-molecule | partial | E / F |
| sufficiency | **surface_modality** — ADC/TCE/antibody fit? | surface-modality-fit | **blind** | E / F |
| sufficiency | **safety** — LoF-intolerant / normal liability? | on-target-safety-liability | partial | F / G |
| sufficiency | **differentiation** — precedent/co-mutation/biomarker? | differentiation-landscape | partial→license_blocked | G / E |
| sufficiency | **translational** — validatable (models/PD)? | translational-readiness | **blind** (unbuilt) | H / J |

**Honesty guardrail:** `framework_can_evidence` is a static baseline used to *report* the deciding
axis (name what fired; list what we couldn't evidence), never to *predict* which axis will decide.

## 2. The scientific homing rule

- **Home** = the axis-question a card *primarily measures* (its measurement construct).
- **Foreign-consume** = another skill consumes the card *iff its verdict logic needs the evidence*
  (a resolver rung/veto fires on it). Foreign edges are **derived** from `rule_id → resolver → gate`,
  not authored freely.
- `consumed_by.lens` (in `card.schema.json`, plan Part 5) MUST name a question `short` or a
  conditioner id defined here.

## 3. Conditioner axes (orthogonal — not questions)

*"8 questions × modality × subtype × molecular-form."* Conditioners refine questions; they are not
themselves gates.

- **modality** `[small_molecule, degrader, adc, bite_tce, antibody]` — selects which sufficiency
  questions are relevant + tiers severity. Already encoded as `modality_relevance`.
- **subtype** — molecular/clinical subgroup partition; refines within strata (who responds). Opt-in
  `--subtypes`, negative-selection only, floor-gated (n≥30). Surfaces as `subtype_fit` + `*-by-subtype`.
- **molecular_form** — which isoform / splice variant / exon / epitope is present & targetable.
  Refines expression (which form), selectivity (a tumor-specific form is a strong selectivity
  signal), and the modality-fit questions (which epitope/domain). **Re-homing (plan 6.3)** unifies
  four scattered pieces:
  | piece | card | home | status |
  |---|---|---|---|
  | cell-line isoform | `cellline-isoform-expression` (NEW) | tumor-presence | promote from a `cellline-rna-distribution` sub-call |
  | tumor splice | `tumor-splice-expression` (NEW) | tumor-presence (→ foreign: tumor-selectivity) | promote from a `tumor-rna-distribution` sub-call |
  | exon window | `modality-exon-window` | surface-modality-fit | exists (inclusion-only; blind to transcript identity) |
  | isoform guardrail | `isoform_selective_targets.yaml` | surface + mechanism (caveat) | exists |

## 4. Per-skill objective + question-coverage contract

Every skill declares a *prevailing scientific objective* and the *questions it answers with its
card set*; a fail-closed guard requires the card set to **cover** those questions (every question
addressed by ≥1 card; every card answers ≥1 question — no unanchored cards). See
`skill_objectives` in the YAML. Template already live: the 7-question decompositions in
`_skills_common/presence_question_table.py` and `dependency_question_table.py` — generalize to all
skills.

## 5. Durable card→skill map (110 cards)

Cards live flat in `cards/<id>.card.yaml`; binding is per-skill `run.py CARDS`. `[V]` = resolver-
driven verdict card. (Full inventory + multi-homed/orphan/composer-drift tables in the review plan;
summary here.)

*Home skills and their card sets — see plan Parts 3a–3d for the complete listing.* Key structural
facts this map made explicit:
- **23 multi-homed cards** (e.g. `copy-number-distribution` → genomic-alteration + safety + surface).
- **12 orphans**: 6 dashboard-spec-only, 1 scan-hook, **5 genuinely dead**
  (`coessential-module`, `sc-surface-normal-safety`, `sc-surface-rna-protein-concordance`,
  `surface-colocalization-avidity`, `tumor-vs-normal-percentile-crossing-by-subtype`).
- **Cross-axis edges are cards, not skills** (`mutation-stratified-dependency` & siblings,
  `partner-conditional-dependency`, `paralog-buffering`, `mutation-drug-response`,
  `co-mutation-and-mutual-exclusivity`) — formalized via `axis_edge` (plan Part 5).

## 6. Known gaps + candidate edges

**Scientific gaps** (blind/partial axes): `surface_modality` (blind — surface MS data-blocked),
`translational` (unbuilt), `differentiation` (license_blocked decisive axis), `dependency` (pooled
scalar conflates 6 modes), `molecular_form` (bulk splice misses low-freq isoforms).

**Candidate edge — genomic feature × survival (does not exist).** The two prognostic cards
(`expression-clinical-association`, `precog-prognostic-association`) are **expression**-keyed. No
card tests whether a target's **mutation/CN/fusion status** stratifies OS in an indication or
subtype. Proposed: `alteration-clinical-association` (`axis_edge: clinical_outcome_os ×
genomic_alteration_status`, reports_into `differentiation`), buildable from TCGA MC3 + TCGA OS (same
substrate `expression-clinical-association` uses; by-subtype via strata). See `candidate_edges` in
the YAML.
