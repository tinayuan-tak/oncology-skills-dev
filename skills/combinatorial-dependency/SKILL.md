---
name: combinatorial-dependency
description: |
  [RETIRED FROM THE target-profile FAN-OUT 2026-08-20] Consolidated into combination-and-vulnerability for composition (its cards compose there under the combination_vulnerability dimension + relational claim_vector). Still runnable standalone; do NOT re-add to SUB_SKILLS.
  Focused question skill: "Is target X a COMBINATORIAL (paralog dual-KO) dependency —
  when co-knocked-out with a paralog partner, is there a synthetic-lethal / buffering
  genetic interaction, and is it constitutive or context/genotype-conditional?"
  Consumes the combinatorial-dependency card + its rule subset. Emits a data-package
  output tree with a self-contained combinatorial_dependency_verdict.

  This is the MEASURED combinatorial-KO complement to two existing skills:
    - functional-requirement (single-GENE dependency; CRISPR/RNAi), and
    - synthetic-lethal-partners (CURATED SL annotation → dependency veto-suppressor).
  It sees paralog co-dependencies that single-KO screens miss: a gene buffered by its
  paralog reads non-essential alone yet is a real co-dependency once the partner is lost
  (CDK2/CDK4, KAT6A/KAT6B, MARK2/MARK3, ARID1A/ARID1B). This was the single biggest
  uncovered theme in the TIDVAL target-project benchmark.

  Use for questions like "is CDK4 a paralog co-dependency (with CDK6)?", "is the MARK2/
  MARK3 interaction constitutive or lineage-conditional?", "does KAT6A have a synthetic-
  lethal paralog partner?"

  Biology-first output. Modality is a POST-HOC lens (the rules carry small_molecule /
  degrader co-targeting signals); the primary output (combinatorial_dependency_verdict
  + driving_rule_id) is modality-independent.

metadata:
  version: 1.1.0    # 1.1.0 (2026-09-05, literature-and-claims arc): NEW COMBINATORIAL_DEPENDENCY narrator
                    # lens + --synthesize; --literature lane (published paralog-SL literature — a genuine 2nd
                    # channel vs the measured GI); verdict-INERT combinatorial_dependency_confidence_caveat
                    # (validated_paralog_synthetic_lethal DATA-BLIND-TOLERANT guard / pan_essential_or_context_
                    # restricted / measured_gi_functionally_unconfirmed) + combinatorial_druggability_caveat
                    # (scaffold→degrader) + combinatorial_dependency_provenance. Reuses the shared
                    # _skills_common/sl_crosswalks corpus; self-contained verdict byte-stable.
  owner: ryan.abo@takeda.com
  requires_preflight: false

composition:
  data_mode: derived_read
  phase: [C]                          # Gate-C adjacent — a combinatorial (paralog) dependency signal
  cards_used:
    - combinatorial-dependency
  # DATA_TO_SKILL_CONTRACT Rule 3 — the measurement_type claim this skill PULLs.
  measurement_types_pulled:
    - combinatorial_ko_dependency
  rules_scope:
    - combinatorial-dependency
  # SELF-CONTAINED verdict: run.py's _verdict maps the fired combinatorial-dependency rules
  # directly → combinatorial_dependency_verdict. Deliberately NOT wired into the shared
  # nomination_verdict_gate resolver ladder (composes into target-profile as a follow-on; the
  # existing dependency/nomination resolver golden snapshots stay byte-stable — avoids the
  # rule_id-ladder trap). Uses a DEDICATED rules axis `combinatorial_dependency` so its rules
  # never cross-load with the shared intracellular-intrinsic ladder.
  synthesis:
    - rule_engine
  output_shape:
    - data_package
  steps_covered: [1, 2, 3, 4, 6]
  optional_lenses:
    - modality
  status: deprecated               # RETIRED FROM THE FAN-OUT 2026-08-20 — consolidated into combination-and-vulnerability. Runnable standalone; NOT composed. (see description note)
---

# combinatorial-dependency — Paralog Dual-KO Genetic Interaction

## What this skill does

Given a target (+ optional indication):
  1. Loads the target's paralog genetic-interaction summary from
     `depmap-paralog-genetic-interaction-per-pair-v1` (DepMap ParalogV2 26Q1 dual-KO),
     via `methods/paralog_genetic_interaction`.
  2. Classifies via the combinatorial-dependency card into `combinatorial_dependency_class`:
     `strong_synthetic_lethal` | `context_synthetic_lethal` | `suppressive_interaction` |
     `no_interaction` | `no_paralog_screened` | `data_unavailable`.
  3. Fires the `combinatorial-dependency` rule subset and resolves a self-contained
     `combinatorial_dependency_verdict`:
       - `constitutive_combinatorial_dependency` — broad co-dependency → co-targeting rationale
       - `context_combinatorial_dependency` — lineage/genotype-conditional → stratified hypothesis
       - `suppressive_combinatorial_interaction` — co-loss LESS lethal (masking)
       - `no_combinatorial_dependency` — measured negative
       - `combinatorial_dependency_insufficient` — coverage gap (gene not in the paralog library)
         or read failure (measured-vs-null discipline).

## Verdict semantics

A combinatorial dependency is a rationale for **co-targeting** (both nodes, or the buffered node
in the partner-loss context) — NOT a single-agent dependency (single-KO of either gene alone is
buffered by construction). Constitutive = broad; context = the therapeutically selective but
conditional case (read the per-lineage breakdown; where the partner is a tumor suppressor,
condition on partner LOSS).

## Boundaries

DepMap ParalogV2 is a PARALOG library (curated paralog pairs, not arbitrary pairs). Absence of a
partner → `combinatorial_dependency_insufficient` (coverage gap), never a negative. Genotype-
conditional SL (e.g. SMARCA2 conditional on SMARCA4 loss) may read `no_interaction`/`context` on
the pan-line summary if the panel is thin in the conditioning genotype — the honest path is a
per-line join to partner alteration status (a follow-on). Published CC-BY GI maps (Dede/in4mer/
Horlbeck) are a future corroboration leg for non-covered genes.

## How Claude invokes this skill

`/combinatorial-dependency --target CDK4 [--indication LUAD]`. Reads the emitted `decision.json`;
`combinatorial_dependency_verdict` + `driving_rule_id` are the audit spine; `top_partners` carries
the ranked partner evidence (mean GI, p-value, n_lines, lineage conditionality).
