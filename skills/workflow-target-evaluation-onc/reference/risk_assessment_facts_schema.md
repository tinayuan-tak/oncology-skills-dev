# Risk Assessment Facts Schema

**Version 1.0.0** · As of 2026-05-29

This document defines the structured input the Step 1 risk-assessment
generator (`scripts/generate_risk_assessment.py`) consumes to render
`{GENE}_risk_assessment_{disease}.md`.

The facts schema replaces hand-written risk-assessment markdown with a
structured input file. The analyst (or LLM-driven PubMed extraction)
populates the YAML; the generator produces schema-compliant markdown
deterministically. Output is automatically lint-passing because it's
generated, not hand-written.

## File location

```
{output_dir}/{GENE}_risk_assessment_facts.yaml
```

Same directory as the structured outputs from Step 2/3 — keeps all
per-gene artifacts together.

## Top-level shape

```yaml
gene: PCDH7
disease: nsclc                    # 'crc' or 'nsclc'
date: 2026-05-22
target_aliases: "Protocadherin-7, HGNC:8657"
modality_candidates:
  - Antibody
  - ADC
  - bispecific (cell-surface protocadherin)

background: |
  Multi-paragraph free-text background on the target. Rendered as
  Section "## Background" of the markdown.

risk_categories:                  # all 6 required
  biological: { ... }
  druggability: { ... }
  translational: { ... }
  clinical: { ... }
  safety: { ... }
  commercial: { ... }

# Optional. If omitted, derived from per-category levels.
overall_risk_profile: LOW-MEDIUM

idas_alignment:                   # whitespace alignment scores
  - whitespace: "2L Non-AGA (IO-experienced)"
    alignment: Strong             # Strong | Moderate | Weak | None
    rationale: "..."
  - ...

strengths:                        # numbered list in §"Key Strengths"
  - "..."

risks:                            # numbered list in §"Key Risks/Challenges"
  - "..."

mitigations:                      # table rows in §"Risk Mitigation Strategies"
  - title: "Modality engineering for CNS safety"
    risk_level: MEDIUM            # LOW | MEDIUM | HIGH
    strategy: "..."

recommendation:
  level: GO                       # GO | NO-GO | CONDITIONAL | CONDITIONAL NO-GO
  priority: MEDIUM-HIGH           # HIGH | MEDIUM-HIGH | MEDIUM | LOW (or omit)
  rationale: "..."                # 1-2 sentence narrative
```

## Per-category structure (`risk_categories.{name}`)

Each of the 6 categories takes the same shape:

```yaml
biological:
  level: LOW                      # LOW | MEDIUM | HIGH | LOW-MEDIUM | MEDIUM-HIGH
  key_driver: |
    One-sentence summary that lands in the Executive Risk Summary table.
  evidence:
    - claim: "Validated in vivo in KRAS-G12D GEMM"
      pmid: "30409919"
      study_type: "in vivo validation"   # optional, free-text
    - claim: "MAPK potentiation via SET/PP2A"
      pmid: "27821484"
      study_type: "mechanistic"
  justification: |
    Multi-line justification text. Rendered as the per-category section
    body (## N. <Category> Risk Assessment > Justification).
```

## Output contract

The generator produces markdown that:

1. Passes the existing `lint_risk_assessment.py` schema linter
2. Has all required sections in the required order
3. Has the Executive Risk Summary table populated with all 6 categories
4. Has `## N. <Category> Risk Assessment` per-category sections with
   `**Risk Level Assigned:** [x] **<level>**` and a `**Justification:**`
   line in each
5. Has the Recommendation phrase in bolded form, e.g.
   `**GO — MEDIUM-HIGH PRIORITY**`
6. Has the iDAS Strategic Alignment table

## Required vs optional fields

**Required at top level:** `gene`, `disease`, `date`, `risk_categories`
(all 6), `recommendation.level`, `mitigations` (≥1).

**Required per category:** `level`, `key_driver`, `justification`.

**Optional:** `target_aliases`, `modality_candidates`, `background`,
`overall_risk_profile` (derived if omitted), `idas_alignment`,
`strengths`, `risks`, per-category `evidence[]`, `recommendation.priority`,
`recommendation.rationale`.

## Derivation rules

When `overall_risk_profile` is omitted, the generator derives it from
per-category levels:

| Per-category levels | Derived overall |
|---|---|
| Any HIGH | HIGH |
| Any MEDIUM-HIGH (no HIGH) | MEDIUM-HIGH |
| Mix of MEDIUM and LOW | LOW-MEDIUM |
| Mostly MEDIUM | MEDIUM |
| All LOW | LOW |

Analysts can override the derivation by setting `overall_risk_profile`
explicitly.

## Migration path for existing genes

Existing hand-written markdowns (PCDH7, CRBN as of 2026-05-28) get
converted to facts.yaml form on this branch as part of v1.3.0. The
migration is one-time per gene; new genes start with facts.yaml directly.

## Forward-compatibility notes

| Future feature | How the schema accommodates it |
|---|---|
| Step 1 facts produced by an LLM extraction pipeline | Schema is structured YAML; LLM output can target it directly |
| Per-claim study quality score | Add `study_quality:` field under each `evidence[]` entry |
| Compound recommendation (e.g. GO for ADC, NO-GO for TCE) | Replace `recommendation` with `recommendations[]` keyed by modality |
| Multi-disease evaluation | Add `additional_diseases[]` block; one facts file per primary disease |

These are out of scope for v1.3.0 but the schema's nested-dict shape
makes them additive (no migration needed for existing files).
