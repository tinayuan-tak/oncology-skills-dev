---
name: target-evaluation
description: Full 4-step therapeutic target evaluation workflow. Use when evaluating drug targets in oncology. Accepts gene symbol and disease type (crc, nsclc). Orchestrates risk assessment with integrated literature review, expression analysis, ScholarEval scoring, and final report generation with PDF output.
---

# Target Evaluation Workflow

## Overview

Comprehensive 4-step pipeline for systematic evaluation of therapeutic targets in oncology. The workflow integrates literature evidence, transcriptomic analysis, and risk assessment to generate Go/No-Go recommendations.

## Parameters

| Parameter | Required | Options | Description |
|-----------|----------|---------|-------------|
| `--gene` | Yes | Any HGNC symbol | Target gene to evaluate (e.g., TNFRSF12A, EPCAM) |
| `--disease` | Yes | `crc`, `nsclc` | Disease indication |
| `--output-dir` | No | Path | Output directory (default: `./{disease}_analysis_results`) |

## Supported Diseases

| Disease | Config | Risk Template | Bulk RNA Skill | Data Sources |
|---------|--------|---------------|----------------|--------------|
| **CRC** | `configs/crc.yaml` | `reference/risk_assessment_template_crc.md` | `oncology-skills:crc-bulk-rna-analysis` | TCGA-COAD/READ, GTEx colon, CCLE |
| **NSCLC** | `configs/nsclc.yaml` | `reference/risk_assessment_template_nsclc.md` | `oncology-skills:nsclc-bulk-rna-analysis` | TCGA-LUAD/LUSC, GTEx lung, CCLE |

## 4-Step Workflow

```
┌─────────────────────────┐     ┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│ 1. DRUG TARGET RISK     │ ──▶ │ 2. EXPRESSION   │ ──▶ │ 3. SCHOLAREVAL  │ ──▶ │ 4. REPORT       │
│    ASSESSMENT           │     │    ANALYSIS     │     │    SCORING      │     │    + PDF        │
│                         │     │                 │     │                 │     │                 │
│ Risk framework +        │     │ Disease-specific│     │ 8-dimension     │     │ Integrated      │
│ PubMed literature       │     │ bulk RNA skill  │     │ target score    │     │ markdown + PDF  │
│ (template-guided)       │     │                 │     │                 │     │                 │
└─────────────────────────┘     └─────────────────┘     └─────────────────┘     └─────────────────┘
```

---

## Step 1: Drug Target Risk Assessment

This step combines the risk assessment framework with PubMed literature search, using disease-specific templates to guide comprehensive target evaluation.

### 1.1 Load Disease-Specific Risk Assessment Template

**For CRC:** Load `reference/risk_assessment_template_crc.md`
- Includes iDAS strategic context (priority whitespaces, biomarker landscape)
- CRC-specific validation criteria and competitive landscape
- Cross-GI portfolio synergy considerations

**For NSCLC:** Load `reference/risk_assessment_template_nsclc.md`
- Standard risk assessment framework

### 1.2 PubMed Literature Search (Template-Guided)

**Invoke:** `scientific-skills:pubmed-database`

Execute targeted PubMed searches for **each risk category** defined in the template:

#### Search Strategy by Risk Category

| Risk Category | Search Query Pattern | Key Evidence Types |
|---------------|---------------------|-------------------|
| **Biological** | `({gene}) AND ({disease}) AND (validation OR knockdown OR knockout OR CRISPR OR genetic association)` | Functional studies, GWAS, somatic mutations |
| **Druggability** | `({gene}) AND (drug target OR inhibitor OR antibody OR small molecule OR crystal structure)` | Tool compounds, structural data, modality options |
| **Translational** | `({gene}) AND ({disease}) AND (biomarker OR PDX OR organoid OR animal model)` | Preclinical models, biomarker studies |
| **Clinical** | `({gene}) AND ({disease}) AND (clinical trial OR patient OR phase I OR phase II)` | Trial results, patient stratification |
| **Safety** | `({gene}) AND (toxicity OR adverse OR normal tissue OR knockout mouse)` | Safety signals, expression in normal tissues |
| **Commercial** | `({gene}) AND ({disease}) AND (therapeutic OR drug development OR competitive)` | Pipeline analyses, market reports |

#### CRC-Specific Search Enhancements

For CRC evaluations, include additional strategic queries based on iDAS priorities:

```
# RAS mutation context (iDAS priority)
({gene}) AND (colorectal cancer) AND (KRAS OR RAS mutant OR RAS wild-type)

# MSI/MSS status
({gene}) AND (colorectal cancer) AND (MSI OR MSS OR microsatellite)

# Chemorefractory setting (iDAS priority)
({gene}) AND (colorectal cancer) AND (refractory OR resistant OR third-line OR 3L)

# CMS subtype relevance
({gene}) AND (colorectal cancer) AND (CMS1 OR CMS2 OR CMS3 OR CMS4 OR consensus molecular subtype)
```

### 1.3 Populate Risk Assessment Template

Use literature findings to complete each section of the template:

#### For CRC (using `risk_assessment_template_crc.md`)

**A. Strategic Alignment Assessment**
- Whitespace Alignment: Match target to iDAS priorities (3L+ chemorefractory, RAS mutant, resectable)
- Biomarker-Defined Population: Identify relevant patient subgroups

**B. Biological Risk (Section 1)**
- CRC-specific molecular subtype considerations (RAS status, MSI, CMS1-4)
- Validation in CRC PDX/organoid models

**C. Druggability Risk (Section 2)**
- Target tractability, structural information
- Available tool molecules

**D. Translational Risk (Section 3)**
- CRC-relevant model systems (PDX, PDO, GEMMs, syngeneic)
- RAS/MSI stratification in models

**E. Clinical Risk (Section 4)**
- CRC population stratification
- Biomarker testing considerations (RAS/BRAF, MSI, HER2)

**F. Safety Risk (Section 5)**
- Normal tissue expression data
- On-target safety concerns

**G. Commercial/Competitive Risk (Section 6)**
- CRC standard of care context
- Competitive landscape (KRAS inhibitors, anti-EGFR, IO)

**H. iDAS Strategic Alignment (Summary)**
- Whitespace alignment scoring
- Cross-GI portfolio synergy
- KRAS strategy synergy

### 1.4 Risk Level Determination

**Risk Levels:**
- **LOW**: Strong evidence supporting favorable profile
- **MEDIUM**: Mixed evidence or addressable gaps
- **HIGH**: Significant concerns or major unknowns

**Important:** Interpret criteria from left to right. If criteria for both Low and Medium risk levels are not met, default to HIGH.

### 1.5 Output: Completed Risk Assessment Document

Generate `{GENE}_risk_assessment_{disease}.md` with:
- All 6 risk categories populated with evidence
- Risk levels assigned with justification
- iDAS strategic alignment score (for CRC)
- Key references from PubMed search

---

## Step 2: Expression Analysis (Disease-Specific)

**Route to appropriate bulk RNA skill based on disease parameter:**

### For CRC (`--disease crc`)
**Invoke:** `oncology-skills:crc-bulk-rna-analysis`

#### Comprehensive Analysis (Recommended - TCGA + Tempus Combined)
```bash
pixi run python crc_comprehensive_analysis.py --genes {GENE} --output-dir ./{disease}_analysis_results/{GENE}
```

**This single script provides:**
- **TCGA raw expression:** Tumor vs Adjacent Normal (on-target toxicity assessment)
- **GTEx:** Healthy tissue baseline
- **CCLE:** Cell line expression for in vitro validation
- **Tempus RWD:** Line-of-therapy stratification (n>200,000)
- **iDAS alignment assessment:** Automatic whitespace scoring
- **Comprehensive visualizations:** 8-panel figure with all key metrics
- **Unified report:** Combined TCGA + Tempus evidence

**Quick options:**
```bash
# Full analysis (recommended)
python crc_comprehensive_analysis.py --genes {GENE}

# Tempus only (faster, no raw expression processing)
python crc_comprehensive_analysis.py --genes {GENE} --skip-tcga

# TCGA only (no Tempus data)
python crc_comprehensive_analysis.py --genes {GENE} --skip-tempus
```

**Data Sources:**
- **TCGA/GTEx:** Raw expression for tumor vs normal (on-target toxicity)
- **Tempus RWD:** Pre-computed summaries with line-of-therapy stratification (n>200,000)

**TCGA Cohorts (unified naming):**
| New Name | Legacy | Description |
|----------|--------|-------------|
| TCGA_RASMut_MSS | Cohort_2A | RAS-mutant, MSS |
| TCGA_RASWT_MSS | Cohort_2B | RAS wild-type, MSS |
| TCGA_Resectable | Cohort_4 | Early stage I/II |
| TCGA_MSS_All | Cohort_5 | All MSS samples |
| TCGA_MSIH | Cohort_6 | MSI-H |

**Tempus Cohorts (iDAS-aligned):**
| Cohort | N Samples | iDAS Alignment |
|--------|-----------|----------------|
| Tempus_RASMut_MSS_1L2L | 85,560 | RAS mutant frontline |
| Tempus_RASMut_MSS_3Lplus | 26,319 | **RAS mutant refractory** |
| Tempus_MSS_3Lplus | 39,618 | **Chemorefractory 3L+** |
| Tempus_RASWT_MSS_1L2L | 58,683 | Contrast group |

**CMS Subtypes:** CMS1-4
**Normal Tissue:** TCGA Adjacent, GTEx Colon

#### Legacy Analysis (TCGA only)
```bash
pixi run python crc_gene_analysis.py --genes {GENE} --output-dir ./{disease}_analysis_results/{GENE}
```

### For NSCLC (`--disease nsclc`)
**Invoke:** `oncology-skills:nsclc-bulk-rna-analysis`

```bash
pixi run python nsclc_gene_analysis.py --genes {GENE} --output-dir ./{disease}_analysis_results/{GENE}
```

**Cohorts:** LUAD, LUSC, Stage I-IV
**Normal:** TCGA Adjacent, GTEx Lung

---

## Step 3: ScholarEval Target Scoring

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

## Step 4: Report Generation + PDF

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
[4-step pipeline description]

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
# Setup
DISEASE="crc"  # or "nsclc"
GENE="TNFRSF12A"

# Step 1: Drug Target Risk Assessment
# - Load disease-specific risk template (e.g., reference/risk_assessment_template_crc.md)
# - Execute PubMed searches for each risk category
# - Populate template with evidence and assign risk levels
# - Output: {GENE}_risk_assessment_{disease}.md

# Step 2: Setup environment and run expression analysis
cp "$SKILL_BASE_DIR/pixi.toml" ./
cp "$SKILL_BASE_DIR/pixi.lock" ./
cp "$SKILL_BASE_DIR/generate_target_report_pdf.py" ./
pixi install

# For CRC (Recommended - Comprehensive TCGA + Tempus):
pixi run python crc_comprehensive_analysis.py --genes $GENE --output-dir ./${DISEASE}_analysis_results/$GENE

# Alternative: Legacy TCGA-only analysis
# pixi run python crc_gene_analysis.py --genes $GENE

# Step 3: ScholarEval scoring
# [Claude calculates 8-dimension target score]

# Step 4: Generate integrated report and PDF
pixi run python generate_target_report_pdf.py --gene $GENE --output-dir ./${DISEASE}_analysis_results/$GENE
```

### Adding New Disease Support

1. Create disease-specific risk assessment template: `reference/risk_assessment_template_{disease}.md`
   - Include strategic context (e.g., iDAS priorities, biomarker landscape)
   - Define disease-specific validation criteria
2. Create disease-specific bulk RNA skill: `oncology-skills:{disease}-bulk-rna-analysis`
3. Add config file: `configs/{disease}.yaml`
4. Update this SKILL.md with new disease routing

---

## Output Files

### Comprehensive Analysis Outputs (`crc_comprehensive_analysis.py`)
| File | Description |
|------|-------------|
| `{GENE}_comprehensive_analysis.png` | 8-panel figure: TCGA cohorts, toxicity, Tempus LOT, iDAS cohorts, RAS status, CMS, alignment summary, recommendation |
| `{GENE}_comprehensive_report.md` | Full report with TCGA + Tempus evidence, iDAS alignment, recommendations |
| `{GENE}_idas_assessment.yaml` | Structured iDAS whitespace alignment assessment |
| `{GENE}_tcga_statistics.csv` | TCGA cohort expression statistics |
| `{GENE}_pairwise_comparisons.csv` | Tumor vs Normal statistical comparisons |

### Target Evaluation Workflow Outputs
| File | Description |
|------|-------------|
| `{GENE}_risk_assessment_{disease}.md` | Step 1 output: Risk assessment with literature evidence |
| `{GENE}_integrated_target_report.md` | Final integrated report (standardized format) |
| `{GENE}_final_risk_report.pdf` | 13-page professional PDF |
| `{GENE}_risk_assessment_figure.png` | 6-category risk assessment visualization |
| `{GENE}_scholar_eval_figure.png` | ScholarEval scoring visualization |

### Legacy Script Outputs (`crc_gene_analysis.py`)
| File | Description |
|------|-------------|
| `{GENE}_expression_analysis.png` | TCGA cohort boxplots |
| `{GENE}_CMS_boxplot.png` | CMS subtype expression |
| `{GENE}_target_report.md` | TCGA-only analysis report |

---

## Example Usage

**User:** "Evaluate TNFRSF12A as a target in CRC"

**Response:**
1. **Step 1: Drug Target Risk Assessment**
   - Load `configs/crc.yaml` and `reference/risk_assessment_template_crc.md`
   - Execute PubMed searches for each risk category (Biological, Druggability, Translational, Clinical, Safety, Commercial)
   - Include CRC-specific searches (RAS mutation context, MSI/MSS status, chemorefractory setting)
   - Populate template with evidence, assess iDAS whitespace alignment
   - Output: `TNFRSF12A_risk_assessment_crc.md`
2. **Step 2: Expression Analysis** - Run CRC bulk RNA analysis
3. **Step 3: ScholarEval Scoring** - Calculate 8-dimension target score
4. **Step 4: Report Generation** - Generate integrated report + PDF
5. Present key findings:
   - Fold change vs adjacent normal: 7.3x ↑
   - ScholarEval Score: 4.2/5.0 (Strong)
   - Risk Profile: LOW-MEDIUM
   - iDAS Alignment: Strong (3L+ chemorefractory, RAS-agnostic)
   - Recommendation: **GO**
6. Point to output files in `crc_analysis_results/TNFRSF12A/`

**User:** "Now evaluate EPCAM in CRC"

**Response:**
1. Same 4-step workflow, different gene
2. Key findings:
   - Fold change vs adjacent normal: ~1x (no change)
   - ScholarEval Score: 3.55/5.0 (Moderate)
   - Risk Profile: HIGH (Safety concern)
   - iDAS Alignment: Moderate (broad applicability but toxicity risk)
   - Recommendation: **CONDITIONAL NO-GO** (on-target toxicity risk)

---

## Key Design Principles

1. **Tumor vs Adjacent Normal is PRIMARY metric** - predicts on-target toxicity
2. **Template-guided risk assessment** - disease-specific templates (e.g., CRC with iDAS context) drive structured PubMed searches
3. **Integrated Step 1** - Risk framework and literature search combined for efficiency
4. **PDF reads from markdown** - no hard-coded values in PDF script
5. **Disease-agnostic orchestration** - add new diseases via config + risk template
6. **Standardized report format** - enables reliable parsing
7. **Strategic alignment** - CRC evaluations include iDAS whitespace and cross-GI synergy assessment
