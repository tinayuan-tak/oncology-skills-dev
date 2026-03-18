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
3. **PDF reads from markdown** - no hard-coded values in PDF script
4. **Standardized report format** - enables reliable parsing
5. **Strategic alignment** - CRC evaluations include iDAS whitespace scoring

## Example Results

| Target | Disease | Tumor vs Normal | ScholarEval | Risk | Recommendation |
|--------|---------|-----------------|-------------|------|----------------|
| **TNFRSF12A (Fn14)** | CRC | **+2.96 log2FC (7.8x ↑)** | 4.15/5.0 | LOW-MEDIUM | **GO** |
| **CDCP1** | CRC | **-0.41 log2FC (tumor < normal)** | 2.75/5.0 | HIGH | **NO-GO** |

**Key insight:** TNFRSF12A shows excellent tumor specificity (7.8x higher in tumor), while CDCP1 fails due to higher expression in normal colon epithelium - demonstrating why tumor vs adjacent normal is the critical safety metric.

## Files

| File | Description |
|------|-------------|
| `SKILL.md` | Main skill definition with full 4-step workflow |
| `generate_target_report_pdf.py` | PDF report generator (300 DPI, 13 pages) |
| `reference/risk_assessment_template_crc.md` | CRC-specific risk template with iDAS context |
| `reference/risk_assessment_template_nsclc.md` | NSCLC-specific risk template |
| `configs/crc.yaml` | CRC-specific configuration |
| `configs/nsclc.yaml` | NSCLC-specific configuration |
| `pixi.toml` | Python dependencies |

## Output Files

### Per-Target Outputs
| File | Description |
|------|-------------|
| `{GENE}_integrated_target_report.md` | Final integrated report with ScholarEval |
| `{GENE}_risk_assessment_{disease}.md` | 6-category risk assessment with literature |
| `{GENE}_final_risk_report.pdf` | Professional 13-page PDF report |
| `{GENE}_comprehensive_analysis.png` | 8-panel expression visualization |
| `{GENE}_risk_assessment_figure.png` | Risk category visualization |
| `{GENE}_scholar_eval_figure.png` | ScholarEval scoring visualization |
| `{GENE}_tcga_statistics.csv` | TCGA cohort expression statistics |
| `{GENE}_pairwise_comparisons.csv` | Tumor vs Normal statistical comparisons |
| `{GENE}_idas_assessment.yaml` | iDAS whitespace alignment (CRC only) |

### PDF Report Structure (13 pages)
| Page | Content |
|------|---------|
| 1 | Title Page with recommendation badge |
| 2 | Executive Summary |
| 3 | Methods |
| 4 | Results: Expression & Literature |
| 5 | Figure 1: Comprehensive Expression Analysis |
| 6 | Figure 2: CMS/Subtype Expression |
| 7 | ScholarEval Scoring Table |
| 8 | Risk Assessment Table |
| 9 | Figure 3: 6-Category Risk Assessment |
| 10 | Figure 4: ScholarEval Target Scoring |
| 11 | Key Strengths & Risks |
| 12 | Risk Mitigation & Recommendations |
| 13 | Conclusions & References |

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
- **Tempus RWD**: >200,000 patients with line-of-therapy stratification
- **PubMed**: Literature evidence by risk category

### NSCLC Analysis
- **TCGA-LUAD/LUSC**: Tumor vs adjacent normal
- **GTEx**: Healthy lung tissue baseline
- **CCLE**: NSCLC cell line expression

## Adding New Diseases

1. Create disease-specific risk template: `reference/risk_assessment_template_{disease}.md`
2. Create bulk RNA analysis skill: `oncology-skills:{disease}-bulk-rna-analysis`
3. Add config file: `configs/{disease}.yaml`
4. Update SKILL.md routing table

