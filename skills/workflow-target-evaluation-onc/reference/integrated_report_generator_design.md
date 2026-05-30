# Integrated Report Generator — Design

**Task #21** · v1.2.0 / v1.3.0 candidate · Author: Claude · Date: 2026-05-28

## Problem statement

Today, the `{GENE}_workflow-target-evaluation-onc_report.md` integrated
markdown is **hand-written**. The PDF generator parses it via regex,
which means any markdown drift produces silent fallbacks (TBD fields,
empty tables, default-MEDIUM risk levels). v1.1.0 hit this; v1.2.0 hit
it again with the PCDH7_TCE run. The 18 PDF extractor tests catch
parser bugs but don't prevent authoring drift.

**Goal:** Eliminate the hand-writing step. Generate the integrated
markdown deterministically from the structured outputs of Steps 1-3.

## Inputs (all already exist per gene)

| File | Source | Format | Hand-written? | Maps to |
|---|---|---|---|---|
| `{GENE}_risk_assessment_{disease}.md` | Step 1 | Markdown w/ template | **Yes** (analyst, template-guided) | §3.1 + §4.1/4.2 + §5 + §6 |
| `{GENE}_analysis-bulk-rna-{disease}_idas.yaml` | Step 2 | YAML | No (auto) | §3.2 (whitespace table), §3.4 (Phase 3) |
| `{GENE}_analysis-bulk-rna-{disease}_suitability.csv` | Step 2 | CSV | No (auto) | §3.4 (Phase 1, 2, 3 tables) |
| `{GENE}_analysis-bulk-rna-{disease}_comparisons.csv` | Step 2 | CSV | No (auto) | §3.2 (tumor vs adjacent table) |
| `{GENE}_analysis-bulk-rna-{disease}_report.md` | Step 2 | Markdown w/ schema | No (auto) | §3.2 narrative, fold-change context |
| `{GENE}_scholareval.yaml` | Step 3 | YAML | No (auto) | §3.3 (8-dim ScholarEval table) + Exec Summary |
| `{GENE}_audit_trail.json` | Step 3 | JSON | No (auto) | Audit metadata in §3.3 footer |

**Optional context** (template populates if file exists, gracefully
falls back if absent):
- `--modality` flag value passed at orchestration time (drives §3.4 Phase 3 narrative)

## Output contract

Single markdown file at:
```
{output_dir}/{GENE}_workflow-target-evaluation-onc_report.md
```

Must satisfy:

1. **Parses cleanly through `parse_integrated_report()`** — zero TBD fields.
2. **Round-trips with `_build_slide_data()`** — page-1 slide data populated.
3. **Section structure matches v1.1.0 template** — same 8-section layout
   (Exec Summary, §1 Intro, §2 Methods, §3 Results [3.1-3.4], §4 Discussion,
   §5 Risk Mitigation, §6 Recommendations, §7 Conclusions, §8 References).
4. **Required fields present**: Modality (in Key Findings + Exec Summary),
   ScholarEval Score (X.XX/5.0 format), Risk Profile (LOW/MEDIUM/HIGH/
   compound), Recommendation (GO/NO-GO/CONDITIONAL with optional priority
   qualifier).
5. **Existing 18 PDF extractor tests pass** against generated output.
6. **PDF generation against the output produces no fallback warnings**
   (no "TBD" in 3.1 risk table, no MEDIUM-default in 6-cat chart).

## Deferred for v1.3.0

The protein-evidence integration is a separate task (#15). The
generator's *structure* should accommodate a future protein YAML input,
but v1.2.0/v1.2.1 doesn't need to consume it. Concretely: the template
should have an optional `{{ protein_evidence }}` block, populated only
if `{GENE}_protein_summary.yaml` exists in the output dir.

## Architecture

### Three-layer separation

```
┌────────────────────────────────────────────────────────────────────┐
│  LAYER 1 — INPUT PARSERS (one per file type)                       │
│    parse_risk_assessment_md(path) → RiskAssessment dataclass       │
│    load_idas_yaml(path)           → IDASAssessment dataclass       │
│    load_suitability_csv(path)     → list[SubgroupRow] dataclass    │
│    load_scholareval_yaml(path)    → ScholarEvalResult dataclass    │
│    load_audit_trail(path)         → AuditTrail dataclass           │
│                                                                    │
│  Each parser is pure: file path in, dataclass out. No formatting,  │
│  no template logic. Independently testable with fixtures.          │
└────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────────────┐
│  LAYER 2 — TEMPLATE CONTEXT BUILDER                                │
│    build_context(gene, disease, modality, parsed_inputs)           │
│      → dict[str, Any]   (Jinja-ready render context)               │
│                                                                    │
│  Pulls from parsed inputs, applies per-disease config (cohort      │
│  names, market sizes, etc. from configs/{disease}.yaml). Computes  │
│  derived fields (overall_risk_profile, recommendation_qualifier).  │
└────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────────────┐
│  LAYER 3 — RENDERER                                                │
│    render_integrated_report(context, template_path) → str          │
│                                                                    │
│  Jinja2 (NOT raw str.format — too brittle for tables). Template    │
│  lives at templates/integrated_report.md.j2. Output is the         │
│  final markdown.                                                   │
└────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
                    Write to disk → PDF script
```

### Why Jinja2 not str.format

| Concern | str.format | Jinja2 |
|---|---|---|
| Multi-row table rendering | Painful (per-row format calls) | Native (`{% for %}`) |
| Conditional sections (e.g. modality-specific footer) | Awkward | Native (`{% if %}`) |
| Markdown-specific escaping | Manual | Filters available |
| Maintainability | Template-as-code | Template-as-data |
| Existing in repo | No | No (new dep — but lightweight) |

Jinja2 adds one pinned dep to `pixi.toml` (~30KB pure-Python install).
For the size of this generator, it's worth it.

## Required parsers — detail

### `parse_risk_assessment_md(path)`

The Step 1 markdown has a well-defined template (`reference/risk_assessment_template_{disease}.md`).
Parser must extract:

- **Executive Risk Summary table** (6 rows, columns: Risk Factor / Risk Level / Key Considerations) → `dict[category, RiskRow]`
- **Per-category sections** (## 1. Biological, ## 2. Druggability, etc.) — extract Justification text + cited PMIDs
- **iDAS Strategic Alignment** section — whitespace alignments, cross-portfolio synergy, modality recommendations
- **Key Strengths / Risks / Mitigations** sections — bulleted lists
- **Recommendation** section — overall recommendation + iDAS priority

Edge cases to handle:
- Risk levels with `**bold**` markers (`**LOW**` vs `LOW`)
- Compound risk levels (`LOW-MEDIUM`, `MEDIUM-HIGH`)
- Em-dash variations (`—`, `–`, `-`)
- Missing optional sections (just emit empty section in output, don't crash)

### `load_idas_yaml(path)`

Already structured. Direct YAML load → dataclass with fields matching
the existing schema. Fields used:

- `on_target_toxicity.{risk_level, tumor_vs_adjacent_log2FC,
   luad_vs_luad_adjacent_log2FC, lusc_vs_lusc_adjacent_log2FC}`
- `whitespace_alignment.{cohort}.{alignment, expression, n_samples, source}`
- `subgroup_analysis.idas_whitespace.{cohort}.{tox_penalty, adjusted_score,
   recommendation, rule_applied, rationale}` (v1.2.0+)
- `recommendation`, `overall_alignment`

### `load_suitability_csv(path)`

CSV columns: subgroup, category, key_metric, score, recommendation.
Parser groups rows by `category` (`tcga_analysis`, `tempus_mutation`,
`idas_whitespace`) for §3.4 Phase 1/2/3 tables.

### `load_scholareval_yaml(path)`

Direct YAML load. Fields used:

- `total_score`, `assessment`, `recommendation`, `high_risk_count`,
  `input_hash`
- `dimension_scores.{dim}.{score, risk_level, rationale, rule_applied}`

### `load_audit_trail(path)`

JSON load. Used for input_hash citation in §3.3 footer.

## Template structure

`templates/integrated_report.md.j2` — Jinja template with the v1.1.0
section layout. Sketch:

```jinja
# {{ gene }} Target Evaluation Report: {{ disease.full_name }}

**Generated:** {{ today }}
**Workflow:** Oncology Target Evaluation Pipeline v{{ version }}

---

## Executive Summary

| Metric | Value |
|--------|-------|
| **Target** | {{ gene }}{% if aliases %} ({{ aliases }}){% endif %} |
| **Indication** | {{ disease.full_name }} |
| **ScholarEval Score** | **{{ scholar.total_score }}/5.0 ({{ scholar.assessment }})** |
| **Overall Risk Profile** | **{{ risk.overall_profile }}** |
| **Recommendation** | **{{ recommendation.full_string }}** |

### Key Findings at a Glance
- **Modality**: {{ modality.display_string }}
- **On-target toxicity**: {{ idas.tox_summary }}
- **iDAS alignment**: {{ idas.alignment_summary }}
{% for finding in key_findings %}
- {{ finding }}
{% endfor %}

...

### 3.1 Risk Assessment Summary

| Risk Category | Risk Level | Key Driver | Key Evidence (PMID) |
|---------------|------------|------------|---------------------|
{% for cat in risk.categories %}
| {{ cat.name }} | {{ cat.level }} | {{ cat.driver }} | {{ cat.evidence }} |
{% endfor %}

**Overall Risk Profile: {{ risk.overall_profile }}**

...

### 3.4 Subgroup-Stratified Suitability

#### Phase 1: TCGA Analysis (Treatment-Naive)

| Subgroup | Key Metric | Score | Risk Level | Recommendation |
|----------|------------|-------|------------|----------------|
{% for row in suitability.phase1 %}
| {{ row.subgroup }} | {{ row.key_metric }} | {{ row.score }}/5 | {{ row.risk_level }} | **{{ row.recommendation }}** |
{% endfor %}

...
```

## CLI surface

```bash
pixi run python scripts/generate_integrated_report.py \
    --gene PCDH7 \
    --disease nsclc \
    --output-dir /path/to/PCDH7_TCE \
    [--modality "T-cell engager"]
```

Reads all 5 inputs from `--output-dir`, writes
`{GENE}_workflow-target-evaluation-onc_report.md` to the same dir.

## Testing strategy

### Layer 1 — parser tests (~30 tests)

Each parser tested against a small fixture file. Edge cases for the
markdown parser get explicit cases (compound risk levels, em-dash
variations, bold markers).

### Layer 2 — context builder tests (~10 tests)

Given parsed inputs (mocked dataclasses), verify the context dict has
the expected shape. Test modality-aware branches (degrader → expression-
floor wording in 3.4; antibody → tumor-vs-normal wording).

### Layer 3 — renderer tests (~5 tests)

Render the template with a known context, assert the output matches a
golden file. Detects template drift.

### Integration / golden-file tests (~3 tests)

Run the full generator on real input dirs:
- `target_evaluation_bulk/crc_bulk_rna/CRBN/` (degrader case)
- `target_evaluation_bulk/nsclc_bulk_rna/PCDH7/` (antibody-default case)
- `target_evaluation_bulk/nsclc_bulk_rna/PCDH7_TCE/` (TCE case)

Each produces a generated markdown. Compare against a golden file
checked in to `tests/fixtures/golden_reports/`. Diffs require explicit
regeneration via `pixi run python -m generator.regenerate_golden`.

### Round-trip parser test (~5 tests)

For each generated markdown, run it through `parse_integrated_report()`
and `_build_slide_data()`. Assert no TBD fields, no fallback values, all
expected sections detected. This is the critical regression guard:
**generated output must satisfy the existing PDF parser**.

## File layout

```
skills/workflow-target-evaluation-onc/
  scripts/
    generate_integrated_report.py     ← CLI entry point
    integrated_report/                ← module
      __init__.py
      parsers/
        __init__.py
        risk_assessment_parser.py     (Layer 1)
        idas_parser.py
        suitability_parser.py
        scholareval_parser.py
      context_builder.py              (Layer 2)
      renderer.py                     (Layer 3)
  templates/
    integrated_report.md.j2           ← Jinja template
  tests/
    test_integrated_report_parsers.py
    test_integrated_report_context.py
    test_integrated_report_renderer.py
    test_integrated_report_e2e.py
    fixtures/
      sample_risk_assessment.md
      sample_idas.yaml
      golden_reports/
        CRBN_crc_degrader.md
        PCDH7_nsclc_antibody.md
        PCDH7_nsclc_tce.md
```

## Risks / open questions

| # | Risk | Mitigation |
|---|---|---|
| 1 | Risk-assessment markdown parser is the hardest piece — humans write the file with formatting variations the parser can't fully anticipate | Strict template enforcement: ship a *linter* alongside the generator that validates the input markdown before parsing. Fail loud on missing sections rather than silent fallback. |
| 2 | Jinja2 dep adds to pixi env | One small dep, pure Python, no build deps; acceptable cost |
| 3 | Golden files drift when we genuinely improve template wording | Documented regen process via `regenerate_golden.py`; PR review catches unintended drift |
| 4 | Scope creep: generator could grow to consume protein evidence (v1.3.0) | Define `protein_evidence` as optional context field now; renderer renders empty section if absent. Defer the protein parser to task #15. |

## Build estimate

| Phase | Hours |
|---|---|
| Parsers (Layer 1) — 4 files, ~80 LOC each | 2-3 |
| Context builder (Layer 2) | 1 |
| Template (Layer 3) | 2 (most time spent matching v1.1.0 layout exactly) |
| CLI script | 0.5 |
| Tests + golden files (regenerate from existing 3 reports) | 1.5 |
| Audit + bugfixes | 1 |
| **Total** | **8-10** |

Expensive enough to gate v1.2.0 on, but worth it: the generator solves
a recurring class of bugs (v1.1.0 retro item, v1.2.0 manual run) and
unblocks v1.3.0 (protein integration) by giving it a clean place to
plug in.

## Decision points before implementation

Three questions for the user before I start writing code:

1. **Jinja2 vs Python f-string templates** — is adding a dependency acceptable? (Recommend Jinja2; one dep.)
2. **Golden-file workflow** — should regeneration be a make target / pixi task, or a manual `python script` invocation? (Recommend: pixi task `pixi run regen-goldens`.)
3. **Linter scope** — should the input-markdown linter be a separate `lint_risk_assessment.py` script, or embedded in the generator's parser layer? (Recommend: separate script, so analysts can run it pre-commit on their hand-written risk assessments.)
