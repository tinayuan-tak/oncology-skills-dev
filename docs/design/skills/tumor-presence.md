# Skill: tumor-presence
**status:** wired · **phase:** A · **version:** 1.1.0

> Is the target expressed in the indication's tumor tissue, and how does its expression distribute across cancer cell lines vs. paired tumor/adjacent samples?

A skill is a thin projection over evidence cards: it resolves each card's categorical through the shared rules engine, then collapses the fired rules into one rank-ordered verdict. The detail lives in the card design docs linked below.

## Composition
| field | value |
|---|---|
| data_mode | derived_read |
| synthesis | rule_engine |
| output_shape | data_package |
| steps_covered | 1, 2, 3, 4, 6 |
| optional_lenses | modality |
| rules axis | intracellular_intrinsic |

## Cards composed
| Card | Question | Data source | Layer | Detail |
|---|---|---|---|---|
| expression-distribution | expression distribution across ~1500 DepMap cell lines | DepMap 26Q1 (cell-line **RNA**) | RNA | [card doc](../cards/expression-distribution.md) |
| expression-tumor-vs-adjacent | upregulated in tumor vs matched adjacent normal? | TCGA tumor-vs-adjacent (**RNA-seq**) | RNA | *(doc pending)* |
| protein-presence-cptac | present at the **protein** level vs matched normals per CPTAC? | CPTAC (**protein**, mass-spec) | protein | *(doc pending)* |

## Verdict ladder
`_verdict()` resolves the fired rules in this fixed priority order (first match wins); this is deterministic, no LLM:

1. `broadly_high_expression` ← expression-broadly-high-supportive
2. `strongly_upregulated_in_tumor` ← expression-strong-upregulation-supportive
3. `lineage_restricted` ← expression-lineage-restricted-supportive
4. `modestly_upregulated_in_tumor` ← expression-modest-upregulation-neutral
5. `broadly_moderate_expression` ← expression-broadly-moderate-neutral
6. `broadly_low_expression` ← expression-broadly-low-degrader-killer
7. `not_informative` ← expression-call-not-informative-degrader-killer
8. `data_unavailable` ← expression-(call-)data-unavailable-insufficient
9. `insufficient` ← (no rule fired)

## What it does NOT do
- Does NOT compare tumor to GTEx population-normal — that's `tumor-selectivity` (phase B).
- Does NOT synthesize narrative — the composed `target-profile` skill does that.
- Does NOT own dispatcher or rule content — it references card IDs + rule IDs from `target-contracts`.
