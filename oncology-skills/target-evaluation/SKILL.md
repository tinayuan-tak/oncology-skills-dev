---
name: target-evaluation
description: Full 5-step therapeutic target evaluation workflow. Use when evaluating drug targets in oncology. Accepts gene symbol and disease type (crc, nsclc). Orchestrates risk assessment, literature review, expression analysis, ScholarEval scoring, and final report generation with PDF output.
---

# Target Evaluation Workflow

## Overview

Comprehensive 5-step pipeline for systematic evaluation of therapeutic targets in oncology. The workflow integrates literature evidence, transcriptomic analysis, and risk assessment to generate Go/No-Go recommendations.

## Parameters

| Parameter | Required | Options | Description |
|-----------|----------|---------|-------------|
| `--gene` | Yes | Any HGNC symbol | Target gene to evaluate (e.g., TNFRSF12A, EPCAM) |
| `--disease` | Yes | `crc`, `nsclc` | Disease indication |
| `--output-dir` | No | Path | Output directory (default: `./{disease}_analysis_results`) |

## Supported Diseases

| Disease | Config | Bulk RNA Skill | Data Sources |
|---------|--------|----------------|--------------|
| **CRC** | `configs/crc.yaml` | `oncology-skills:crc-bulk-rna-analysis` | TCGA-COAD/READ, GTEx colon, CCLE |
| **NSCLC** | `configs/nsclc.yaml` | `oncology-skills:nsclc-bulk-rna-analysis` | TCGA-LUAD/LUSC, GTEx lung, CCLE |

## 5-Step Workflow

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│ 1. RISK         │ ──▶ │ 2. PUBMED       │ ──▶ │ 3. EXPRESSION   │ ──▶ │ 4. SCHOLAREVAL  │ ──▶ │ 5. REPORT       │
│    FRAMEWORK    │     │    SEARCH       │     │    ANALYSIS     │     │    SCORING      │     │    + PDF        │
│                 │     │                 │     │                 │     │                 │     │                 │
│ Define 6 risk   │     │ Guided by risk  │     │ Disease-specific│     │ 8-dimension     │     │ Integrated      │
│ categories      │     │ categories      │     │ bulk RNA skill  │     │ target score    │     │ markdown + PDF  │
└─────────────────┘     └─────────────────┘     └─────────────────┘     └─────────────────┘     └─────────────────┘
```

---

## Step 1: Risk Assessment Framework

Define the 6 risk categories that guide all downstream analysis:

| Category | Key Questions | Evidence Sources |
|----------|---------------|------------------|
| **Biological** | Target validated? Genetic evidence? | GWAS, knockout studies, functional validation |
| **Druggability** | Tractable? Tool molecules? Assays? | Structural data, compound literature |
| **Translational** | Disease models? Biomarkers? | Preclinical studies, biomarker publications |
| **Clinical** | Patient population? Trial feasible? | Clinical trial databases |
| **Safety** | On-target risks? Normal tissue expression? | Toxicity reports, GTEx expression |
| **Commercial** | Unmet need? Competition? | Market reports, pipeline analyses |

**Risk Levels:**
- **LOW**: Strong evidence supporting favorable profile
- **MEDIUM**: Mixed evidence or addressable gaps
- **HIGH**: Significant concerns or major unknowns

---

## Step 2: PubMed Literature Search

**Invoke:** `scientific-skills:pubmed-database`

Use disease-specific query template from config:

**CRC Example:**
```
"({gene} OR {aliases}) AND (colorectal cancer OR colon cancer OR CRC)"
```

**NSCLC Example:**
```
"({gene} OR {aliases}) AND (non-small cell lung cancer OR NSCLC OR lung adenocarcinoma OR LUAD)"
```

**Organize findings by risk category:**
- Biological: Genetic studies, CRISPR screens, disease models
- Druggability: Drug development, structural biology, tool compounds
- Translational: Biomarkers, animal models
- Clinical: Clinical trials, patient stratification
- Safety: Toxicity reports, normal tissue expression
- Commercial: Competitive landscape

---

## Step 3: Expression Analysis (Disease-Specific)

**Route to appropriate bulk RNA skill based on disease parameter:**

### For CRC (`--disease crc`)
**Invoke:** `oncology-skills:crc-bulk-rna-analysis`

```bash
pixi run python crc_gene_analysis.py --genes {GENE} --output-dir ./{disease}_analysis_results/{GENE}
```

**Cohorts:** 2A (RAS-mut MSS), 2B (RAS-WT MSS), 4 (Early Stage), 5 (All MSS), 6 (MSI-H)
**Subtypes:** CMS1-4
**Normal:** TCGA Adjacent, GTEx Colon

### For NSCLC (`--disease nsclc`)
**Invoke:** `oncology-skills:nsclc-bulk-rna-analysis`

```bash
pixi run python nsclc_gene_analysis.py --genes {GENE} --output-dir ./{disease}_analysis_results/{GENE}
```

**Cohorts:** LUAD, LUSC, Stage I-IV
**Normal:** TCGA Adjacent, GTEx Lung

---

## Step 4: ScholarEval Target Scoring

**Invoke:** `scientific-skills:scholar-evaluation`

### 8 Evaluation Dimensions

| Dimension | Weight | Scoring Criteria |
|-----------|--------|------------------|
| Differential Expression | 0.15 | **PRIMARY: Tumor vs Adjacent Normal** |
| Pathway Relevance | 0.15 | Connection to disease pathways |
| Druggability | 0.15 | Surface receptor, enzyme, etc. |
| Genetic Validation | 0.10 | Knockout/knockdown evidence |
| Disease Association | 0.10 | Prognostic/diagnostic value |
| Safety Profile | 0.15 | Normal tissue expression, known toxicities |
| Clinical Validation | 0.10 | Human trial data |
| Biomarker Potential | 0.10 | Patient selection feasibility |

### Differential Expression Scoring (Critical)

| Score | Criteria | Interpretation |
|-------|----------|----------------|
| **5/5** | >2x vs adjacent normal AND >4x vs GTEx | True tumor-specific |
| **4/5** | >2x vs adjacent normal | Good tumor specificity |
| **3/5** | 1.5-2x vs adjacent normal | Moderate specificity |
| **2/5** | ~1x vs adjacent normal (high vs GTEx only) | Epithelial marker - ON-TARGET TOXICITY RISK |
| **1/5** | No significant overexpression | Poor target |

### Score Interpretation

| Score | Assessment | Recommendation |
|-------|------------|----------------|
| 4.5-5.0 | Excellent | Priority development |
| 4.0-4.4 | Strong | Advance with confidence |
| 3.5-3.9 | Moderate | Proceed with caution |
| 3.0-3.4 | Weak | Requires validation |
| <3.0 | Poor | Not recommended |

---

## Step 5: Report Generation + PDF

**Invoke:** `scientific-skills:scientific-writing`

### Generate Integrated Report Markdown

Create `{GENE}_integrated_target_report.md` with standardized format:

```markdown
# {GENE} Target Evaluation Report: {Disease}

## Executive Summary

**Target**: {GENE} ({aliases})
**Indication**: {Disease Full Name}
**ScholarEval Score**: X.XX/5.0 (Assessment)
**Overall Risk Profile**: LEVEL
**Recommendation**: **GO/NO-GO** - Description

---

## 1. Introduction
[Disease context, target rationale]

## 2. Methods
[5-step pipeline description]

## 3. Results
### 3.1 Differential Expression
[Expression analysis results - Tumor vs Adjacent Normal as PRIMARY]

### 3.2 Literature Evidence
[Organized by risk category]

### 3.3 Target Validation Scorecard
[8-dimension ScholarEval table]

## 4. Risk Assessment Summary
[6-category risk table]

## 5. Discussion
### 5.1 Key Strengths
### 5.2 Key Risks/Challenges

## 6. Risk Mitigation Strategies

## 7. Recommendations

## 8. Conclusions

## 9. References
```

### Generate PDF Report

```bash
pixi run python generate_target_report_pdf.py --gene {GENE} --output-dir ./{disease}_analysis_results/{GENE}
```

**PDF Structure (13 pages):**

| Page | Content |
|------|---------|
| 1 | Title Page (Professional design with recommendation badge) |
| 2 | Executive Summary |
| 3 | Methods |
| 4 | Results: Expression & Literature |
| 5 | Figure 1: Comprehensive Expression Analysis |
| 6 | Figure 2: Subtype Expression |
| 7 | ScholarEval Scoring Table |
| 8 | Risk Assessment Table |
| 9 | Figure 3: 6-Category Risk Assessment |
| 10 | Figure 4: ScholarEval Target Scoring |
| 11 | Key Strengths & Risks |
| 12 | Risk Mitigation & Recommendations |
| 13 | Conclusions & References |

---

## Implementation

### Full Workflow Execution

```bash
# 1. Load disease config
DISEASE="crc"  # or "nsclc"
GENE="TNFRSF12A"

# 2. Setup environment
cp "$SKILL_BASE_DIR/pixi.toml" ./
cp "$SKILL_BASE_DIR/pixi.lock" ./
cp "$SKILL_BASE_DIR/generate_target_report_pdf.py" ./
pixi install

# 3. Run expression analysis (routes to disease-specific skill)
# For CRC:
pixi run python crc_gene_analysis.py --genes $GENE

# 4. Generate integrated report (uses scientific-writing skill)
# [Claude generates markdown report]

# 5. Generate PDF
pixi run python generate_target_report_pdf.py --gene $GENE --output-dir ./${DISEASE}_analysis_results/$GENE
```

### Adding New Disease Support

1. Create disease-specific bulk RNA skill: `oncology-skills:{disease}-bulk-rna-analysis`
2. Add config file: `configs/{disease}.yaml`
3. Update this SKILL.md with new disease routing

---

## Output Files

| File | Description |
|------|-------------|
| `{GENE}_integrated_target_report.md` | Source markdown (standardized format) |
| `{GENE}_final_risk_report.pdf` | 13-page professional PDF |
| `{GENE}_comprehensive_analysis.png` | Multi-panel expression figure |
| `{GENE}_CMS_boxplot.png` | Subtype expression (CRC) |
| `{GENE}_risk_assessment_figure.png` | Figure 3 |
| `{GENE}_scholar_eval_figure.png` | Figure 4 |
| `{GENE}_pairwise_comparisons.csv` | Statistical results |

---

## Example Usage

**User:** "Evaluate TNFRSF12A as a target in CRC"

**Response:**
1. Load `configs/crc.yaml`
2. Run Step 1-5 workflow
3. Present key findings:
   - Fold change vs adjacent normal: 7.3x ↑
   - ScholarEval Score: 4.2/5.0 (Strong)
   - Risk Profile: LOW-MEDIUM
   - Recommendation: **GO**
4. Point to output files in `crc_analysis_results/TNFRSF12A/`

**User:** "Now evaluate EPCAM in CRC"

**Response:**
1. Same workflow, different gene
2. Key findings:
   - Fold change vs adjacent normal: ~1x (no change)
   - ScholarEval Score: 3.55/5.0 (Moderate)
   - Risk Profile: HIGH
   - Recommendation: **CONDITIONAL NO-GO** (on-target toxicity risk)

---

## Key Design Principles

1. **Tumor vs Adjacent Normal is PRIMARY metric** - predicts on-target toxicity
2. **PDF reads from markdown** - no hard-coded values in PDF script
3. **Disease-agnostic orchestration** - add new diseases via config
4. **Standardized report format** - enables reliable parsing
