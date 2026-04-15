# Target Evaluation Skill

Comprehensive 4-step therapeutic target evaluation workflow for oncology indications. Generates Go/No-Go recommendations based on integrated evidence from literature, transcriptomics, and risk assessment.

## Overview

This skill orchestrates the full target evaluation pipeline:

```
┌─────────────────────────┐     ┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│ 1. DRUG TARGET RISK     │ ──▶ │ 2. EXPRESSION   │ ──▶ │ 3. SCHOLAREVAL  │ ──▶ │ 4. REPORT       │
│    ASSESSMENT           │     │    ANALYSIS     │     │    SCORING      │     │    + PDF        │
│                         │     │                 │     │                 │     │                 │
│ Risk framework +        │     │ Disease-specific│     │ 8-dimension     │     │ Integrated      │
│ PubMed literature       │     │ bulk RNA skill  │     │ weighted score  │     │ markdown + PDF  │
└─────────────────────────┘     └─────────────────┘     └─────────────────┘     └─────────────────┘
```

## Usage

```
Evaluate {GENE} as a target in {disease}
```

**Examples:**
```
target evaluation on TNFRSF12A in CRC
target evaluation on CDCP1 --disease crc
Evaluate EGFR as a target in NSCLC
```

**Supported diseases:**
- `crc` - Colorectal Cancer (with iDAS strategic alignment)
- `nsclc` - Non-Small Cell Lung Cancer

## Key Design Principles

1. **Tumor vs Adjacent Normal is the PRIMARY metric** - predicts on-target toxicity
2. **Template-guided risk assessment** - disease-specific templates drive structured PubMed searches
3. **Deterministic scoring** - rule-based scoring engine ensures reproducibility
4. **Validation checkpoints** - 3 checkpoints ensure consistency across workflow
5. **PDF reads from markdown** - no hard-coded values in PDF script
6. **Standardized report format** - enables reliable parsing
7. **Strategic alignment** - evaluations include iDAS whitespace scoring

## Validation Framework

Ensures consistency between literature and omics data integration through deterministic scoring and validation checkpoints.

### Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                        VALIDATION FRAMEWORK                                      │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                  │
│  EXTRACTION (LLM)           SCORING (Rules)           REPORTING (LLM)           │
│  ─────────────────         ───────────────           ─────────────────          │
│  - Interpret text          - Apply thresholds        - Narrate from             │
│  - Classify studies        - Deterministic           fixed scores               │
│  - Extract structured      - Auditable               - Cannot change scores     │
│    facts → JSON            - NO LLM judgment         - Explain rationale        │
│                                                                                  │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### LLM Interpretation Guidelines

| Phase | LLM Interpretation | Examples |
|-------|-------------------|----------|
| **Literature Mining** | YES - Required | Read abstracts, classify study types, identify relevant findings |
| **Evidence Extraction** | YES - Structured | Extract facts (counts, yes/no, categories) into JSON schema |
| **Scoring** | NO - Rule-based | Apply thresholds from `scoring_rules.yaml`, no subjective weighting |
| **Report Writing** | YES - Constrained | Narrate rationale, but scores are locked from Step 3 |

**Key principle:** LLM extracts **FACTS** (3 CRISPR studies, Phase 2 trial exists) not **JUDGMENTS** (strong evidence, high risk).

### Literature Mining Limitations

**Current:** Abstract-only access via PubMed API
- Sufficient for study type classification and key findings
- May miss detailed methods, dosing, patient numbers

**Future enhancements:**
- PubMed Central (PMC) for open-access full text
- Publisher API integration for subscribed journals
- PDF parsing for internal documents

### Three Validation Checkpoints

| Checkpoint | When | Validates |
|------------|------|-----------|
| **1. Input Completeness** | Before Step 3 | Step 1 (literature) AND Step 2 (omics) outputs exist with required fields |
| **2. Scoring Determinism** | During Step 3 | Re-running scoring engine produces identical scores |
| **3. Report Consistency** | Before Step 4 | Scores in report match computed ScholarEval YAML |

### Scoring Engine

The deterministic scoring engine (`scripts/scoring_engine.py`) applies rules from `configs/scoring_rules.yaml`:

- **Literature scoring**: biological validation, clinical validation, druggability, safety
- **Omics scoring**: differential expression, safety profile, iDAS alignment
- **ScholarEval**: 8-dimension weighted scoring with recommendation rules

### Audit Trail

Every scoring decision is logged with:
- Input data and checksums
- Rule path applied
- Calculated values
- Output scores
- Timestamp

Export to `{GENE}_audit_trail.json` for full reproducibility verification.

## Files

| File | Description |
|------|-------------|
| `SKILL.md` | Main skill definition with full 4-step workflow |
| `scripts/generate_target_report_pdf.py` | PDF report generator (300 DPI, 14 pages) |
| `scripts/scoring_engine.py` | Deterministic scoring engine with audit trail |
| `scripts/validation_checkpoints.py` | 3-checkpoint validation framework |
| `configs/crc.yaml` | CRC-specific configuration |
| `configs/nsclc.yaml` | NSCLC-specific configuration |
| `configs/scoring_rules.yaml` | Deterministic scoring thresholds and weights |
| `reference/risk_assessment_template_crc.md` | CRC-specific risk template with iDAS context |
| `reference/risk_assessment_template_nsclc.md` | NSCLC-specific risk template |
| `reference/evidence_extraction_schema.yaml` | Schema for structured LLM evidence extraction |
| `pixi.toml` | Python dependencies |

## Output Files

### Per-Target Outputs
| File | Description |
|------|-------------|
| `{GENE}_integrated_target_report.md` | Final integrated report with ScholarEval |
| `{GENE}_risk_assessment_{disease}.md` | 6-category risk assessment with literature |
| `{GENE}_final_risk_report.pdf` | Professional 14-page PDF report |
| `{GENE}_comprehensive_analysis.png` | 8-panel expression visualization |
| `{GENE}_comprehensive_report.md` | Expression analysis report (Step 2 output) |
| `{GENE}_subgroup_suitability.csv` | 3-phase subgroup suitability scores |
| `{GENE}_scholareval.yaml` | Deterministic scoring output |
| `{GENE}_audit_trail.json` | Full scoring audit trail |
| `{GENE}_risk_assessment_figure.png` | Risk category visualization |
| `{GENE}_scholar_eval_figure.png` | ScholarEval scoring visualization |
| `{GENE}_tcga_statistics.csv` | TCGA cohort expression statistics |
| `{GENE}_pairwise_comparisons.csv` | Tumor vs Normal statistical comparisons |
| `{GENE}_idas_assessment.yaml` | iDAS whitespace alignment |

### PDF Report Structure (14 pages)
| Page | Content |
|------|---------|
| 1 | Title Page with recommendation badge |
| 2 | Executive Summary |
| 3 | Methods |
| 4 | Results: Expression & Literature |
| 5 | Figure 1: Comprehensive Expression Analysis |
| 6 | Figure 2: CMS/Subtype Expression |
| 7 | ScholarEval Scoring Table |
| 8 | Subgroup Suitability Table + Figure |
| 9 | Risk Assessment Table |
| 10 | Figure 3: 6-Category Risk Assessment |
| 11 | Figure 4: ScholarEval Target Scoring |
| 12 | Key Strengths & Risks |
| 13 | Risk Mitigation & Recommendations |
| 14 | Conclusions & References |

## ScholarEval Scoring

8-dimension weighted scoring system:

| Dimension | Weight | Description |
|-----------|--------|-------------|
| Differential Expression | 0.15 | **Tumor vs Adjacent Normal** (primary) |
| Pathway Relevance | 0.15 | Connection to disease pathways |
| Druggability | 0.15 | Surface receptor, enzyme, etc. |
| Genetic Validation | 0.10 | Knockout/knockdown evidence |
| Disease Association | 0.10 | Prognostic/diagnostic value |
| Safety Profile | 0.15 | Normal tissue expression |
| Clinical Validation | 0.10 | Human trial data |
| Biomarker Potential | 0.10 | Patient selection feasibility |

**Score Interpretation:**
- 4.5-5.0: Excellent - Priority development
- 4.0-4.4: Strong - Advance with confidence
- 3.5-3.9: Moderate - Proceed with caution
- 3.0-3.4: Weak - Requires validation
- <3.0: Poor - Not recommended

## Data Sources

### CRC Analysis
- **TCGA-COAD/READ**: Tumor vs adjacent normal (on-target toxicity)
- **GTEx**: Healthy colon tissue baseline
- **CCLE**: CRC cell line expression
- **Tempus RWD**: ~2,183 patients with line-of-therapy stratification
- **PubMed**: Literature evidence by risk category

### NSCLC Analysis
- **TCGA-LUAD/LUSC**: Tumor vs adjacent normal (on-target toxicity)
- **GTEx**: Healthy lung tissue baseline
- **CCLE**: NSCLC cell line expression
- **Tempus RWD**: ~1,800 patients with EGFR/KRAS/STK11/KEAP1 stratification
- **PubMed**: Literature evidence by risk category

## Adding New Diseases

1. Create disease-specific risk template: `reference/risk_assessment_template_{disease}.md`
2. Create bulk RNA analysis skill: `oncology-skills:{disease}-bulk-rna-analysis`
3. Add config file: `configs/{disease}.yaml`
4. Update SKILL.md routing table

