# Card: cellline-rna-distribution
**card_id:** `cellline-rna-distribution` · **version:** 1.0.0 · **generation:** modern (rules externalized) · **schema_version:** 1

> Across ~1500 DepMap cell lines, what is the expression distribution of the target, and is it lineage-stratified?

## At a glance
```
depmap-consortium-26q1   (DepMap 26Q1 cell-line RNA, release-pinned)
      |   method: depmap-expression-distribution
      v
summary_fields  (percentiles, fractions, per-lineage stats)
      |   classify
      v
expression_class = one of { broadly_high | broadly_moderate | lineage_restricted | broadly_low | data_unavailable }
      |   5 rules  (intracellular-intrinsic axis)
      v
per-modality signal  ->  small_molecule / degrader
```

## Data source
| product_id | release_pin | What it is |
|---|---|---|
| `depmap-consortium-26q1` | `{release_pin}` | DepMap 26Q1 `OmicsExpressionTPMLogp1HumanProteinCodingGenes.csv` — per-gene log2(TPM+1) across ~1500 cell lines, release-pinned + md5. |

Read is manifest-mediated (no bare S3 paths) — provenance + release-pin are automatic.

## Method
| methods.call | args | Computes |
|---|---|---|
| `depmap-expression-distribution` | `target`, `release_pin`, `expressed_threshold` | Panel expression distribution: percentiles, expressed/highly-expressed fractions, per-lineage breakdown, and the `expression_class` categorical. |

## Emitted evidence (`summary_fields`)
| Field | Notes |
|---|---|
| `n_cell_lines_evaluated` | panel size (drives the low-coverage warning) |
| `median_log2tpm_panel`, `p25/p75/p5/p95_log2tpm_panel`, `log2tpm_iqr` | distribution shape |
| `fraction_expressed` | log2(TPM+1) ≥ 1.0 |
| `fraction_highly_expressed` | log2(TPM+1) ≥ 5.0 |
| `fraction_not_expressed` | log2(TPM+1) < 1.0 |
| **`expression_class`** | **DEPMAP-convention categorical — drives Tier-2 rules** |
| `n_lineages_evaluated`, `per_lineage_stats`, `n_lineage_restricted_lineages` | lineage stratification |

**Categorical vocabulary — `expression_class`** (the value set rules key off):
`broadly_high` (>70% highly expressed) · `broadly_moderate` (>70% expressed, <30% highly) · `lineage_restricted` (10–70% expressed, stratified) · `broadly_low` (<30% expressed) · `data_unavailable`

## Plots
| id | type | preferred surfaces | primary |
|---|---|---|---|
| `density_expression` | density histogram + KDE (threshold refs at 1.0 / 5.0) | markdown, ppt, decision_memo | yes |
| `lineage_strip_expression` | per-lineage strip plot (n≥5, ordered by median) | markdown, ppt | |
| `waterfall_expression` | ranked per-cell-line waterfall | markdown, ppt | |

plot_data: `per_cell_line_expression_with_lineage_tags`

## Interpretation rules
Interpretation lives in `interpretation-rules/intracellular-intrinsic.rules.yaml` (not the card). Each rule fires on an `expression_class` value → per-modality signal.

| rule_id | when expression_class = | small_molecule | degrader | dominant |
|---|---|---|---|---|
| `expression-broadly-high-supportive` | `broadly_high` | supportive | supportive | |
| `expression-lineage-restricted-supportive` | `lineage_restricted` | supportive | supportive | |
| `expression-broadly-moderate-neutral` | `broadly_moderate` | neutral | neutral | |
| `expression-broadly-low-degrader-killer` | `broadly_low` | — | killer | |
| `expression-data-unavailable-insufficient` | `data_unavailable` | insufficient | insufficient | |

Signal vocabulary: `killer` / `supportive` / `neutral` / `insufficient`, per modality.

## Gating, thresholds & warnings
- **applies_when:** `context.data_sources.depmap_expression_available == true`
- **thresholds:** `expressed_threshold_log2tpm=1.0` · `highly_expressed_threshold_log2tpm=5.0` · `broadly_expressed_fraction_threshold=0.70` · `broadly_high_fraction_threshold=0.30` · `lineage_restricted_min/max_fraction=0.10/0.70` · `min_lineage_size=5`
- **warning:** `low_panel_expression_coverage` — if `n_cell_lines_evaluated < 500` → "panel coverage unusually low; matrix subset may be biased" (→ `passed_with_warnings`)

## Caveats (verbatim)
- Cell-line expression does not match tumor expression directly; DepMap lines are immortalized cultures biased toward proliferation programs.
- Expression class is descriptive — therapeutic interpretation lives in `interpretation-rules/`.
- Lineage-restricted expression in DepMap is informative, but the gold-standard normal-tissue safety signal comes from GTEx via the `lineage-restriction-evidence` card.

## Used by
`tumor-presence` (leaf) · `target-profile` (composer, via tumor-presence)
