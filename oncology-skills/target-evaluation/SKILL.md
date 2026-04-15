---
name: target-evaluation
description: Full 4-step therapeutic target evaluation workflow. Use when evaluating drug targets in oncology. Accepts gene symbol and disease type (crc, nsclc). Orchestrates risk assessment with integrated literature review, multi-omics analysis, ScholarEval scoring, and final report generation with PDF output.
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
┌─────────────────────────┐
│ 1. DRUG TARGET RISK     │ ───────┐
│    ASSESSMENT           │        │
│                         │        │     ┌─────────────────┐     ┌─────────────────┐
│ Risk framework +        │        ├───▶ │ 3. SCHOLAREVAL  │ ──▶ │ 4. REPORT       │
│ PubMed literature       │        │     │    SCORING      │     │    + PDF        │
│ (template-guided)       │        │     │                 │     │                 │
└─────────────────────────┘        │     │ 8-dimension     │     │ Integrated      │
         [PARALLEL]                │     │ target score    │     │ markdown + PDF  │
┌─────────────────────────┐        │     │                 │     │                 │
│ 2. EXPRESSION           │ ───────┘     └─────────────────┘     └─────────────────┘
│    ANALYSIS             │
│                         │
│ Disease-specific        │
│ bulk RNA skill          │
└─────────────────────────┘
```

## Workflow Dependencies (CRITICAL)

**Steps 1 and 2 can run in parallel. Step 3 MUST wait for BOTH to complete.**

### Dependency Rules

| Step | Dependencies | Parallel Execution |
|------|--------------|-------------------|
| Step 1 (Risk Assessment) | None | Can run with Step 2 |
| Step 2 (Expression Analysis) | None | Can run with Step 1 |
| **Step 3 (ScholarEval)** | **Step 1 AND Step 2 must be COMPLETED** | Cannot start until both done |
| Step 4 (Report + PDF) | Step 3 must be COMPLETED | Sequential |

### Task-Based Dependency Tracking

**MANDATORY:** Use TaskCreate/TaskUpdate to track workflow progress and enforce dependencies.

#### At Workflow Start
```
TaskCreate: "Step 1: {GENE} Drug Target Risk Assessment ({disease})" - status: pending
TaskCreate: "Step 2: {GENE} Multi-omics Expression Analysis" - status: pending  
TaskCreate: "Step 3: {GENE} ScholarEval Scoring" - status: pending, blockedBy: [Step1, Step2]
TaskCreate: "Step 4: {GENE} Integrated Report + PDF" - status: pending, blockedBy: [Step3]
```

#### Before Starting Step 3
```python
# REQUIRED CHECK - Do not skip
step1_task = TaskGet(step1_id)
step2_task = TaskGet(step2_id)

if step1_task.status != "completed" or step2_task.status != "completed":
    # DO NOT PROCEED - wait for completion
    raise DependencyError("Step 3 requires Step 1 AND Step 2 to be completed")
```

### Background Agent Handling

If Step 1 runs as a background agent (e.g., PubMed literature search):

1. **Launch agent with `run_in_background: true`**
2. **DO NOT proceed to Step 3** until you receive the agent completion notification
3. **When agent completes**, update the task status to "completed"
4. **Only then** check if both Step 1 and Step 2 are complete before Step 3

**NEVER assume an agent is complete based on time elapsed. Wait for the explicit completion notification.**

### Required Outputs Checklist

Before Step 3, verify these outputs exist AND their source tasks are marked complete:

| Step | Task Status | Required Output File |
|------|-------------|---------------------|
| Step 1 | `completed` | `{GENE}_risk_assessment_{disease}.md` |
| Step 2 | `completed` | `{GENE}_comprehensive_report.md` |
| Step 2 | `completed` | `{GENE}_subgroup_suitability.csv` |

**Both conditions must be met: task status = completed AND file exists.**

---

## Validation Framework (V1.0)

The validation framework ensures consistency between literature and omics data integration through deterministic scoring and validation checkpoints.

### Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                        VALIDATION FRAMEWORK                                      │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                  │
│  EXTRACTION (LLM)           SCORING (Rules)           REPORTING (LLM)           │
│  ─────────────────         ───────────────           ─────────────────          │
│  - Extract FACTS           - Apply thresholds        - Narrate from             │
│  - NO interpretation       - Deterministic           fixed scores               │
│  - Structured output       - Auditable               - Cannot change scores     │
│                                                                                  │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### Three Validation Checkpoints

| Checkpoint | When | Validates |
|------------|------|-----------|
| **1. Input Completeness** | Before Step 3 | Both Step 1 (literature) AND Step 2 (omics) outputs exist and contain required fields |
| **2. Scoring Determinism** | During Step 3 | Re-running scoring engine with same inputs produces identical scores |
| **3. Report Consistency** | Before Step 4 | Scores in final report match computed ScholarEval YAML |

### Configuration Files

| File | Location | Purpose |
|------|----------|---------|
| `evidence_extraction_schema.yaml` | `reference/` | Schema for structured evidence extraction (LLM outputs) |
| `scoring_rules.yaml` | `configs/` | Deterministic scoring thresholds and weights |
| `scoring_engine.py` | `scripts/` | Python scoring engine (no LLM interpretation) |
| `validation_checkpoints.py` | `scripts/` | Checkpoint validation functions |

### Using the Validation Framework

#### Checkpoint 1: Before Starting Step 3

```python
# REQUIRED: Validate inputs are complete before ScholarEval
from scripts.validation_checkpoints import CheckpointValidator

validator = CheckpointValidator(output_dir)
result = validator.validate_input_completeness(
    gene="TNFRSF12A",
    disease="crc",
    risk_assessment_path=Path(f"{GENE}_risk_assessment_{disease}.md"),
    comprehensive_report_path=Path(f"{GENE}_comprehensive_report.md"),
    idas_yaml_path=Path(f"{GENE}_idas_assessment.yaml")
)

if not result.passed:
    # DO NOT PROCEED - report errors and wait
    for error in result.errors:
        print(f"BLOCKED: {error}")
```

#### Step 3 with Deterministic Scoring

```python
from scripts.scoring_engine import ScoringEngine

# Initialize scoring engine with rules
engine = ScoringEngine()

# Provide structured evidence (extracted by LLM in schema format)
literature_evidence = {
    "biological_validation": {
        "n_crispr_studies": 3,
        "n_animal_models": 2,
        "n_human_genetic": 1
    },
    "clinical_validation": {
        "highest_phase": 1,
        "n_trials": 3
    },
    "druggability": {
        "has_clinical_compound": True,
        "has_tool_compound": True,
        "best_ic50_nm": 50
    }
}

omics_evidence = {
    "rna_expression": {
        "tumor_vs_adjacent_fc": 7.8,
        "tumor_median_log2tpm": 5.2,
        "normal_median_log2tpm": 2.3
    }
}

# Run deterministic scoring
result = engine.evaluate_target(
    gene="TNFRSF12A",
    disease="CRC",
    literature_evidence=literature_evidence,
    omics_evidence=omics_evidence
)

# Export results with full audit trail
engine.export_result(result, Path(f"{GENE}_scholareval.yaml"))
engine.export_audit_trail(Path(f"{GENE}_audit_trail.json"))
```

#### Checkpoint 3: Before Generating Final Report

```python
# REQUIRED: Validate report matches computed scores
result = validator.validate_report_consistency(
    report_path=Path(f"{GENE}_integrated_target_report.md"),
    scholareval_yaml_path=Path(f"{GENE}_scholareval.yaml")
)

if not result.passed:
    # Report has inconsistent scores - regenerate from YAML
    for error in result.errors:
        print(f"INCONSISTENCY: {error}")
```

### Audit Trail

The scoring engine generates a full audit trail for reproducibility:

```json
{
  "timestamp": "2026-04-01T15:30:00",
  "dimension": "differential_expression",
  "input_data": {
    "tumor_vs_adjacent_fc": 7.8
  },
  "rule_path": "omics_scoring.differential_expression",
  "calculated_value": 7.8,
  "output_score": 5.0,
  "checksum": "a1b2c3d4"
}
```

### Validation Errors and Recovery

| Error Type | Cause | Recovery |
|------------|-------|----------|
| `Input Completeness Failed` | Step 1 or 2 not complete | Wait for background agents to complete; check file paths |
| `Score Mismatch` | Non-deterministic scoring | Re-extract evidence using schema; re-run scoring engine |
| `Report Inconsistency` | Manual edits or LLM drift | Regenerate report from ScholarEval YAML |
| `Hash Mismatch` | Input data changed | Re-run full workflow with new data |

---

## Step 1: Drug Target Risk Assessment

This step combines the risk assessment framework with PubMed literature search, using disease-specific templates to guide comprehensive target evaluation.

### 1.1 Read Disease-Specific Risk Assessment Template (MANDATORY)

**CRITICAL:** You MUST use the Read tool to read the disease-specific risk assessment template BEFORE any other actions in this workflow. The template contains:
- iDAS strategic context and priority whitespaces
- Disease-specific search query enhancements for PubMed
- Validation criteria and risk level definitions
- Biomarker landscape and population stratification guidance

**Template Paths (relative to skill base directory):**

| Disease | Template File | Read Command |
|---------|--------------|--------------|
| **CRC** | `reference/risk_assessment_template_crc.md` | `Read: {SKILL_BASE_DIR}/reference/risk_assessment_template_crc.md` |
| **NSCLC** | `reference/risk_assessment_template_nsclc.md` | `Read: {SKILL_BASE_DIR}/reference/risk_assessment_template_nsclc.md` |

**For CRC:** Read `reference/risk_assessment_template_crc.md`
- Includes iDAS strategic context (priority whitespaces, biomarker landscape)
- CRC-specific validation criteria and competitive landscape
- Cross-GI portfolio synergy considerations

**For NSCLC:** Read `reference/risk_assessment_template_nsclc.md`
- Includes iDAS strategic context (2L Non-AGA, 2L EGFR mutant, 1L/2L KRAS mutant)
- NSCLC-specific biomarker landscape (EGFR, KRAS, STK11, KEAP1, AGA status)
- Line-of-therapy stratification considerations

**DO NOT SKIP THIS STEP.** The template guides all subsequent actions in Step 1.

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

**Disease-Specific Search Enhancements:** Defined in the risk assessment templates (`reference/risk_assessment_template_{disease}.md`). Follow the template guidance for iDAS-aligned queries.

### 1.3 Populate Risk Assessment Template

Use literature findings to complete each section of the disease-specific template. The templates define:
- Strategic alignment assessment (iDAS whitespace scoring)
- 6 risk categories with disease-specific criteria
- Biomarker and population stratification guidance

**Templates:**
- CRC: `reference/risk_assessment_template_crc.md`
- NSCLC: `reference/risk_assessment_template_nsclc.md`

### 1.4 Risk Level Determination (Rubric-Based)

**IMPORTANT:** Use the rubric-based criteria tables in the templates to determine risk levels. Each category has explicit criteria for LOW, MEDIUM, and HIGH.

#### 6-Category Risk Assessment Criteria Summary

| Risk Category | LOW | MEDIUM | HIGH |
|---------------|-----|--------|------|
| **Biological** | Clinically validated target | Validated in ≥1 in vivo model (Onc) OR Totality of human biological evidence highly favorable OR Human genetic association | Novel target OR Limited external validation/low replication |
| **Druggability** | Target has approved/clinical/in vivo PoC **AND** Established CMC expertise, GMP & supply chain | Homologous to validated target OR Limited CMC expertise | Weak/no tractability evidence **OR** No CMC expertise |
| **Translational** | Validated animal models **AND** TE biomarkers **AND** PD biomarkers exist | All three available but not validated | Any component not available |
| **Clinical** | Clearly defined patient population + clinical-grade biomarker **AND** feasible trial | Biomarker needs development OR trial feasibility challenges | Difficult biomarker path **OR** significant trial feasibility challenges |
| **Safety** | Clinically validated safety, no compound class risks, OR minimal/mitigated risks | Some target/compound risks, R/B manageable, premonitory biomarkers available | Strong evidence of risks, R/B questionable **AND** no premonitory biomarkers |
| **Commercial** | Market ≥$5bn **AND** competitive profile (1st/2nd to market, BiC) | Everything not Low or High | Market <$0.5bn **OR** 4th+ to market with no differentiation **OR** poor strategic fit |

**Decision Rule:** Evaluate criteria from LOW → MEDIUM → HIGH. If LOW criteria are not met, check MEDIUM. If neither LOW nor MEDIUM criteria are met, assign **HIGH** by default.

### 1.5 Output: Completed Risk Assessment Document

Generate `{GENE}_risk_assessment_{disease}.md` with:
- All 6 risk categories populated with evidence
- Risk levels assigned with justification
- iDAS strategic alignment score (for CRC)
- Key references from PubMed search

---

## Step 2: Multi-omics Analysis (Disease-Specific)

**Route to appropriate bulk RNA skill based on disease parameter:**

### For CRC (`--disease crc`)
**Invoke:** `oncology-skills:crc-bulk-rna-analysis`

#### Comprehensive Analysis (Recommended - TCGA + Tempus Combined)
```bash
# Run from skill base directory - do NOT copy the script
pixi run python "$SKILL_BASE_DIR/crc_comprehensive_analysis.py" --genes {GENE} --output-dir ./{disease}_analysis_results
```

**This single script provides:**
- **TCGA raw expression:** Tumor vs Adjacent Normal (on-target toxicity assessment)
- **GTEx:** Healthy tissue baseline
- **CCLE:** Cell line expression for in vitro validation
- **Tempus RWD:** Line-of-therapy stratification (n~2,183)
- **iDAS alignment assessment:** Automatic whitespace scoring
- **3-Phase Subgroup Suitability:** Phase 1 (TCGA molecular) → Phase 2 (Tempus RAS) → Phase 3 (iDAS whitespace)
- **Comprehensive visualizations:** 8-panel figure with all key metrics
- **Unified report:** Combined TCGA + Tempus evidence with subgroup suitability table

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
- **Tempus RWD:** Pre-computed summaries with line-of-therapy stratification (n~2,183)

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
| Tempus_RASMut_MSS_1L2L | 920 | RAS mutant frontline |
| Tempus_RASMut_MSS_3Lplus | 283 | **RAS mutant refractory** |
| Tempus_MSS_3Lplus | 426 | **Chemorefractory 3L+** |
| Tempus_RASWT_MSS_1L2L | 631 | Contrast group |

**CMS Subtypes:** CMS1-4
**Normal Tissue:** TCGA Adjacent, GTEx Colon

### For NSCLC (`--disease nsclc`)
**Invoke:** `oncology-skills:nsclc-bulk-rna-analysis`

```bash
# Run from skill base directory - do NOT copy the script
pixi run python "$SKILL_BASE_DIR/nsclc_comprehensive_analysis.py" --genes {GENE} --output-dir ./{disease}_analysis_results
```

**Quick options:**
```bash
# Full analysis (recommended)
python nsclc_comprehensive_analysis.py --genes {GENE}

# Tempus only (faster, no raw expression processing)
python nsclc_comprehensive_analysis.py --genes {GENE} --skip-tcga

# TCGA only (no Tempus data)
python nsclc_comprehensive_analysis.py --genes {GENE} --skip-tempus
```

**Data Sources:**
- **TCGA/GTEx:** Raw expression for tumor vs normal (on-target toxicity)
- **Tempus RWD:** ~1,800 patients with biomarker stratification
- **3-Phase Subgroup Suitability:** Phase 1 (TCGA histology + mutation) → Phase 2 (Tempus mutation) → Phase 3 (iDAS whitespace)

**TCGA Cohorts:**
| Cohort | Description |
|--------|-------------|
| TCGA_LUAD | Lung adenocarcinoma |
| TCGA_LUSC | Lung squamous cell carcinoma |
| TCGA_Adjacent | Adjacent normal lung |
| GTEx_Lung | Normal lung tissue |
| CCLE_NSCLC | NSCLC cell lines |

**TCGA Mutation Status (treatment-naive):**
| Mutation | Description |
|----------|-------------|
| KRAS Mut/WT | KRAS mutation status |
| EGFR Mut/WT | EGFR mutation status |
| STK11 Mut/WT | STK11 mutation status (IO resistance) |
| KEAP1 Mut/WT | KEAP1 mutation status (IO resistance) |

**Tempus Cohorts (iDAS-aligned):**
| Cohort | N Samples | iDAS Alignment |
|--------|-----------|----------------|
| Tempus_2L_NonAGA | 518 | **2L Non-AGA (IO-experienced)** |
| Tempus_2L_EGFR | 38 | **2L EGFR Mutant (post-TKI)** |
| Tempus_1L2L_KRAS | 1,021 | **1L/2L KRAS Mutant** |

**Biomarker Stratification:** EGFR, KRAS, STK11, KEAP1, AGA status
**Normal Tissue:** TCGA Adjacent, GTEx Lung

---

## Step 3: ScholarEval Target Scoring

**Invoke:** `scientific-skills:scholar-evaluation`

### Primary Data Source: `{GENE}_comprehensive_report.md`

**IMPORTANT:** The comprehensive report generated by Step 2 (`{GENE}_comprehensive_report.md`) is the **primary source** for Steps 3 and 4. This markdown file contains:
- TCGA/GTEx cohort statistics with sample sizes and p-values
- Tempus RWD expression by line of therapy and biomarker status
- iDAS whitespace alignment assessment
- On-target toxicity analysis (tumor vs adjacent normal)
- **3-Phase Subgroup Suitability Analysis** (new):
  - Phase 1: TCGA Analysis (treatment-naive histology + mutation status)
  - Phase 2: Tempus Mutation Status (IO-experienced population)
  - Phase 3: iDAS Whitespace Suitability (integrated expression + toxicity + mutation data)

Read this file first to extract evidence for all 8 ScholarEval dimensions.

**Additional structured files** (for programmatic use):
- `{GENE}_subgroup_suitability.csv`: Tabular subgroup suitability scores
- `{GENE}_idas_assessment.yaml`: Structured iDAS alignment data
- `{GENE}_tcga_statistics.csv`: Raw TCGA cohort statistics

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

### Standard ScholarEval Table Format (REQUIRED)

**IMPORTANT:** Use this exact format for the ScholarEval table in integrated reports to ensure PDF parsing works correctly.

```markdown
| Dimension | Weight | Score | Rationale |
|-----------|--------|-------|-----------|
| Differential Expression | 0.15 | 4/5 | Evidence text |
| Pathway Relevance | 0.15 | 5/5 | Evidence text |
| Druggability | 0.15 | 4/5 | Evidence text |
| Genetic Validation | 0.10 | 5/5 | Evidence text |
| Disease Association | 0.10 | 5/5 | Evidence text |
| Safety Profile | 0.15 | 4/5 | Evidence text |
| Clinical Validation | 0.10 | 3/5 | Evidence text |
| Biomarker Potential | 0.10 | 4/5 | Evidence text |
| **TOTAL** | **1.00** | **X.XX/5.0** | **Assessment** |
```

**Format Rules:**
1. **Score format**: Plain `digit/5` (NO bold `**` markers around score)
2. **Columns**: Exactly 4 columns: `Dimension | Weight | Score | Rationale`
3. **Score position**: Always 3rd column
4. **TOTAL row**: Include weighted total with assessment (Strong/Moderate/Weak)

### Subgroup-Specific ScholarEval (CRC and NSCLC)

**IMPORTANT:** Use the `{GENE}_subgroup_suitability.csv` and `{GENE}_comprehensive_report.md` from Step 2 to inform subgroup-specific recommendations rather than a single overall score.

#### Reading Subgroup Suitability Data

The bulk RNA analysis generates `{GENE}_subgroup_suitability.csv` with 3-phase structure:

**For NSCLC:**
- **Phase 1 (TCGA Analysis)**: Histology (LUAD/LUSC) + mutation status (KRAS, EGFR, STK11, KEAP1) - treatment-naive
- **Phase 2 (Tempus Mutation)**: KRAS, EGFR, STK11, KEAP1 mutation status - IO-experienced population
- **Phase 3 (iDAS Whitespace)**: 2L Non-AGA, 2L EGFR, 1L/2L KRAS - integrates expression + toxicity + mutation data

**For CRC:**
- **Phase 1 (TCGA Molecular)**: RAS Mut MSS, RAS WT MSS, MSI-H, Resectable - treatment-naive
- **Phase 2 (Tempus RAS)**: RAS mutation status from Tempus - CPI-naive/treated population
- **Phase 3 (iDAS Whitespace)**: Chemorefractory 3L+, RAS Mutant Refractory, RAS Mutant Frontline, Resectable

#### Subgroup-Specific Differential Expression Scoring

| Subgroup Score | Criteria | ScholarEval Differential Expression |
|----------------|----------|-------------------------------------|
| 5/5 (PRIORITY) | >2x vs adjacent OR upregulated in mutant | 5/5 |
| 4/5 (GO) | 1.5-2x vs adjacent OR high expression + low tox | 4/5 |
| 3/5 (CONDITIONAL/NEUTRAL) | Moderate enrichment | 3/5 |
| 2/5 (CAUTION) | Low enrichment OR downregulated in mutant | 2/5 |
| 1/5 (EXCLUDE) | No enrichment OR significantly downregulated | 1/5 |

#### Subgroup-Stratified Recommendations Table

The `comprehensive_report.md` already includes the 3-phase subgroup suitability table. Copy this section into the integrated report:

```markdown
### Subgroup-Stratified Target Suitability

#### Phase 1: TCGA Analysis (Treatment-Naive)
| Subgroup | Key Metric | Score | Recommendation |
|----------|------------|-------|----------------|
| TCGA Histology: LUSC | 2.0x vs adjacent (TCGA) | 4/5 | GO |
| TCGA Histology: LUAD | 1.4x vs adjacent (TCGA) | 3/5 | CONDITIONAL |
| TCGA Mutation: STK11+ | 0.5x vs WT (TCGA) | 2/5 | CAUTION |

#### Phase 2: Tempus Mutation Status (IO-Experienced)
| Subgroup | Key Metric | Score | Recommendation |
|----------|------------|-------|----------------|
| Tempus Mutation: KRAS+ | 1.2x vs WT (Tempus) | 4/5 | GO |
| Tempus Mutation: STK11+ | 0.8x vs WT (Tempus) | 3/5 | NEUTRAL |

#### Phase 3: iDAS Whitespace Suitability
| Whitespace | Key Metric | Score | Recommendation |
|------------|------------|-------|----------------|
| iDAS: 2L Non-AGA | expr=5.33, tox=Medium | 4/5 | GO |
| iDAS: 1L/2L KRAS Mutant | expr=5.56, 1.2x vs WT (Tempus), tox=Medium | 4/5 | GO |
```

#### Subgroup-Specific Recommendations

Based on subgroup suitability analysis, provide stratified recommendations:

1. **Priority Subgroups** (score ≥4): Proceed with development
2. **Conditional Subgroups** (score 3): Requires additional validation
3. **Caution/Exclude Subgroups** (score ≤2): Consider exclusion criteria or biomarker selection

**Example (CDCP1 in NSCLC):**
> "CDCP1 shows strongest suitability for **LUSC histology** (2.0x tumor enrichment) and all **iDAS priority whitespaces**. Consider **excluding STK11-mutant patients** from trials due to significantly lower target expression (log2FC=-0.92 vs WT). LUAD shows moderate suitability (1.4x enrichment) and may require patient selection strategies."

---

## Step 4: Report Generation + PDF

**Invoke:** `scientific-skills:scientific-writing`

### Primary Data Source: `{GENE}_comprehensive_report.md`

**IMPORTANT:** Use `{GENE}_comprehensive_report.md` from Step 2 as the **primary source** for writing the integrated report. This file contains all bulk RNA analysis results including:
- TCGA/GTEx expression statistics with sample sizes
- Tempus RWD evidence with line-of-therapy stratification
- On-target toxicity assessment with log2FC and p-values
- iDAS whitespace alignment with expression levels
- **3-Phase Subgroup Suitability Analysis** with scoring rationale

Combine this with:
- Step 1 risk assessment (`{GENE}_risk_assessment_{disease}.md`)
- Step 3 ScholarEval scoring

### Generate Integrated Report Markdown

Create `{GENE}_integrated_target_report.md` with **this exact standardized format** (use across ALL disease indications):

```markdown
# {GENE} Target Evaluation Report: {DISEASE}

**Generated:** YYYY-MM-DD
**Workflow:** Oncology Target Evaluation Pipeline v2.0

---

## Executive Summary

| Metric | Value |
|--------|-------|
| **Target** | {GENE} ({aliases}) |
| **Indication** | {Disease Full Name} |
| **ScholarEval Score** | **X.XX/5.0 (Assessment)** |
| **Overall Risk Profile** | **LEVEL** |
| **Recommendation** | **GO/NO-GO - PRIORITY** - Brief description |

### Key Findings at a Glance
- **On-target toxicity**: Risk level (Xx tumor vs adjacent normal)
- **iDAS alignment**: Alignment level across N priority whitespaces
- **Best populations**: List top populations with metrics
- **Caution populations**: List any populations to exclude/monitor
- **Modality**: Recommended therapeutic modality with validation status

---

## 1. Introduction

### 1.1 Target Background
[Target biology, structure, signaling pathway, function - 1 paragraph]

### 1.2 Rationale for {Disease}
- Bullet point 1: Expression/upregulation evidence
- Bullet point 2: Functional role in disease
- Bullet point 3: Druggability rationale
- Bullet point 4: Key unmet need addressed

### 1.3 iDAS Strategic Context
{Disease} represents a key focus area with N priority whitespaces:
1. **Whitespace 1**: Description
2. **Whitespace 2**: Description
3. **Whitespace N**: Description

---

## 2. Methods

### 2.1 Four-Step Evaluation Pipeline

| Step | Description | Data Sources |
|------|-------------|--------------|
| 1. Risk Assessment | Literature-based target risk evaluation | PubMed (N articles) |
| 2. Expression Analysis | Multi-omics bulk RNA analysis | TCGA, GTEx, Tempus RWD |
| 3. ScholarEval | 8-dimension target scoring | Integrated evidence |
| 4. Report Generation | Integrated findings + PDF | All steps |

### 2.2 Data Sources
- **TCGA**: N tumors, N adjacent normal (treatment-naive)
- **GTEx**: N normal tissue samples
- **Tempus RWD**: ~N patients (CPI status breakdown)
- **CCLE**: N cell lines
- **PubMed**: Literature search across 6 risk categories

---

## 3. Results

### 3.1 Risk Assessment Summary (Step 1: Literature-Based)

> **Data Source:** PubMed literature search across 6 risk categories
>
> **IMPORTANT:** This section contains ONLY literature-based evidence from Step 1 PubMed searches. Do NOT include omics data (expression values, fold changes, log2TPM) here. Omics data belongs in Section 3.2 (Step 2). The ScholarEval in Section 3.3 combines both literature and omics evidence.

| Risk Category | Risk Level | Key Driver | Key Evidence (PMID) |
|---------------|------------|------------|---------------------|
| Biological | LOW/MEDIUM/HIGH | Literature-based summary | Key finding from paper (PMID: XXXXXXXX) |
| Druggability | LOW/MEDIUM/HIGH | Literature-based summary | Key finding from paper (PMID: XXXXXXXX) |
| Translational | LOW/MEDIUM/HIGH | Literature-based summary | Key finding from paper (PMID: XXXXXXXX) |
| Clinical | LOW/MEDIUM/HIGH | Literature-based summary | Key finding from paper (PMID: XXXXXXXX) |
| Safety | LOW/MEDIUM/HIGH | Literature-based summary | Key finding from paper (PMID: XXXXXXXX) |
| Commercial | LOW/MEDIUM/HIGH | Literature-based summary | Market data or competitive intelligence |

**Overall Risk Profile: LEVEL**

### 3.2 Differential Expression Analysis (Step 2: Multi-omics)

#### Primary On-Target Toxicity Metric: Tumor vs Adjacent Normal

| Comparison | Tumor N | Normal N | Tumor Median | Normal Median | Fold Change | Risk Level | p-value |
|------------|---------|----------|--------------|---------------|-------------|------------|---------|
| Cohort_1 vs Adjacent | N | N | X.XX | X.XX | **X.Xx** | LOW/MEDIUM/HIGH | X.XXe-XX |
| Cohort_2 vs Adjacent | N | N | X.XX | X.XX | **X.Xx** | LOW/MEDIUM/HIGH | X.XXe-XX |
| All Tumors vs GTEx | N | N | X.XX | X.XX | X.Xx | - | X.XXe-XX |

**On-Target Toxicity Risk Criteria:**
- **LOW**: >2x tumor vs adjacent normal (good therapeutic window)
- **MEDIUM**: 1.5-2x tumor vs adjacent normal (moderate window)
- **HIGH**: <1.5x tumor vs adjacent normal (narrow window, toxicity concern)

**Interpretation**: [1-2 sentence summary of tumor specificity and toxicity risk]

#### Tempus iDAS Priority Whitespaces

| Priority Whitespace | Expression (log2TPM) | Alignment | N Samples |
|---------------------|----------------------|-----------|-----------|
| Whitespace 1 | X.XX | **Strong/Moderate/Weak** | N |
| Whitespace 2 | X.XX | **Strong/Moderate/Weak** | N |

### 3.3 Target Validation Scorecard (Step 3: ScholarEval)

> **Data Source:** Integrated evidence from Step 1 (Literature) + Step 2 (Multi-omics)
>
> **NOTE:** The Rationale column COMBINES both literature evidence (from 3.1) and omics data (from 3.2). This is where expression values, fold changes, and log2TPM data should appear alongside literature citations.

| Dimension | Weight | Score | Risk Level | Rationale |
|-----------|--------|-------|------------|-----------|
| Differential Expression | 0.15 | X/5 | LOW/MEDIUM/HIGH | Omics: Xx vs adjacent (from 3.2); Literature support (PMID) |
| Pathway Relevance | 0.15 | X/5 | LOW/MEDIUM/HIGH | Literature evidence (PMID) |
| Druggability | 0.15 | X/5 | LOW/MEDIUM/HIGH | Literature evidence (PMID) |
| Genetic Validation | 0.10 | X/5 | LOW/MEDIUM/HIGH | Literature evidence (PMID) |
| Disease Association | 0.10 | X/5 | LOW/MEDIUM/HIGH | Literature + omics evidence |
| Safety Profile | 0.15 | X/5 | LOW/MEDIUM/HIGH | Omics: X.XX log2TPM normal (from 3.2); Literature (PMID) |
| Clinical Validation | 0.10 | X/5 | LOW/MEDIUM/HIGH | Literature evidence (PMID) |
| Biomarker Potential | 0.10 | X/5 | LOW/MEDIUM/HIGH | Literature + omics evidence |
| **TOTAL** | **1.00** | **X.XX/5.0** | **LEVEL** | **Assessment - Recommendation** |

### 3.4 Subgroup-Stratified Suitability (Steps 2+3 Integration)

#### Phase 1: TCGA Analysis (Treatment-Naive)

| Subgroup | Key Metric | Score | Risk Level | Recommendation |
|----------|------------|-------|------------|----------------|
| Subgroup 1 | Metric | X/5 | LOW/MEDIUM/HIGH | **GO/CONDITIONAL/CAUTION** |
| Subgroup 2 | Metric | X/5 | LOW/MEDIUM/HIGH | **GO/CONDITIONAL/CAUTION** |

#### Phase 2: Tempus Mutation Status (IO-Experienced/CPI-Naive)

| Subgroup | Key Metric | Score | Risk Level | Recommendation |
|----------|------------|-------|------------|----------------|
| Mutation 1 | X.Xx vs WT (Tempus) | X/5 | LOW/MEDIUM/HIGH | **GO/NEUTRAL/CAUTION** |
| Mutation 2 | X.Xx vs WT (Tempus) | X/5 | LOW/MEDIUM/HIGH | **GO/NEUTRAL/CAUTION** |

#### Phase 3: iDAS Whitespace Suitability

| Whitespace | Key Metric | Score | Risk Level | Recommendation |
|------------|------------|-------|------------|----------------|
| iDAS: Whitespace 1 | expr=X.XX, tox=Level | X/5 | LOW/MEDIUM/HIGH | **PRIORITY/GO/CONDITIONAL** |
| iDAS: Whitespace 2 | expr=X.XX, tox=Level | X/5 | LOW/MEDIUM/HIGH | **PRIORITY/GO/CONDITIONAL** |

#### Subgroup Recommendations Summary
- **PRIORITY Subgroups**: List
- **GO Subgroups**: List
- **CAUTION/EXCLUDE**: List or "None identified"

---

## 4. Discussion

### 4.1 Key Strengths

1. **Strength 1**: Detailed explanation
2. **Strength 2**: Detailed explanation
3. **Strength 3**: Detailed explanation
4. **Strength 4**: Detailed explanation
5. **Strength 5**: Detailed explanation

### 4.2 Key Risks/Challenges

1. **Risk 1**: Detailed explanation
2. **Risk 2**: Detailed explanation
3. **Risk 3**: Detailed explanation
4. **Risk 4**: Detailed explanation

### 4.3 Subgroup-Specific Considerations

**Optimal Populations:**
- Population 1: Rationale
- Population 2: Rationale

**Populations Requiring Caution:**
- Population 1: Rationale (or "None identified")

---

## 5. Risk Mitigation Strategies

| Risk | Risk Level | Mitigation Strategy |
|------|------------|---------------------|
| Risk 1 | LOW/MEDIUM/HIGH | Strategy description |
| Risk 2 | LOW/MEDIUM/HIGH | Strategy description |
| Risk 3 | LOW/MEDIUM/HIGH | Strategy description |
| Risk 4 | LOW/MEDIUM/HIGH | Strategy description |

---

## 6. Recommendations

### 6.1 Overall Recommendation: **GO/NO-GO - PRIORITY/CONDITIONAL**

[1 paragraph summary of why target is recommended for advancement]

### 6.2 Recommended Development Path

1. **Modality**: Recommended approach with rationale
2. **Initial indication**: Target population with rationale
3. **Biomarker strategy**: Patient selection approach
4. **Expansion**: Future opportunities

### 6.3 Subgroup-Specific Recommendations

| Population | Recommendation | Risk Level | Rationale |
|------------|----------------|------------|-----------|
| Population 1 | **Priority/Include/Conditional/Exclude** | LOW/MEDIUM/HIGH | Brief rationale |
| Population 2 | **Priority/Include/Conditional/Exclude** | LOW/MEDIUM/HIGH | Brief rationale |
| Population 3 | **Priority/Include/Conditional/Exclude** | LOW/MEDIUM/HIGH | Brief rationale |

---

## 7. Conclusions

{GENE} emerges as a **priority/conditional/not recommended** therapeutic target for {Disease} based on comprehensive multi-omics and literature evaluation. The target demonstrates:

1. **Finding 1** - brief detail
2. **Finding 2** - brief detail
3. **Finding 3** - brief detail
4. **Finding 4** - brief detail
5. **Finding 5** - brief detail

[Final recommendation statement]

---

## 8. References

1. Author A et al. (Year) Title. *Journal*. PMID: XXXXXXXX.
2. Author B et al. (Year) Title. *Journal*. PMID: XXXXXXXX.
[Continue with all references]
```

**IMPORTANT FORMAT RULES:**
1. Use **exact section numbering** matching workflow order: 3.1 Risk Assessment (Step 1), 3.2 Expression (Step 2), 3.3 ScholarEval (Step 3), 3.4 Subgroups (Steps 2+3)
2. Risk Assessment (3.1) includes **PMID column** for literature evidence - NO separate Literature Evidence section
3. All tables with scores/assessments must include **Risk Level column** (LOW/MEDIUM/HIGH)
4. On-Target Toxicity Risk: LOW (>2x), MEDIUM (1.5-2x), HIGH (<1.5x) vs adjacent normal
5. Risk Mitigation (Section 5) uses **table format with Risk Level column**
6. Recommendations (Section 6) has **3 subsections** (6.1, 6.2, 6.3) with Risk Level in 6.3 table
7. Always include **"Key Findings at a Glance"** in Executive Summary
8. Always include **Generated date and Workflow version** at top

### Generate PDF Report (Automatic)

**IMPORTANT:** PDF generation is automatic and MUST be executed at the end of every target evaluation workflow.

```bash
# Run from skill base directory - do NOT copy to working directory
pixi run python "$SKILL_BASE_DIR/scripts/generate_target_report_pdf.py" --gene {GENE} --disease {DISEASE} --output-dir ./{disease}_analysis_results
```

**Required Parameters:**
- `--gene`: Target gene symbol (e.g., PCDH7, TNFRSF12A)
- `--disease`: Disease indication (`crc` or `nsclc`)
- `--output-dir`: Directory containing the integrated report markdown

The script automatically:
1. Parses `{GENE}_integrated_target_report.md` for content
2. Generates disease-specific text (full disease name, TCGA projects, normal tissue references)
3. Includes comprehensive multi-omics analysis figure
4. Creates professional 13-page PDF with visualizations

**PDF Structure (14 pages):**

| Page | Content |
|------|---------|
| 1 | Title Page (Professional design with recommendation badge) |
| 2 | Executive Summary |
| 3 | Methods |
| 4 | Results: Expression & Literature |
| 5 | Figure 1: Comprehensive Multi-omics Analysis |
| 6 | Figure 2: Subtype Expression |
| 7 | ScholarEval Scoring Table |
| 8 | Subgroup Suitability Table + Figure |
| 9 | Risk Assessment Table |
| 10 | Figure 3: 6-Category Risk Assessment |
| 11 | Figure 4: ScholarEval Target Scoring |
| 12 | Key Strengths & Risks (including Subgroup Considerations) |
| 13 | Risk Mitigation & Recommendations |
| 14 | Conclusions & References |

---

## Implementation

### Full Workflow Execution

```bash
# Setup
DISEASE="crc"  # or "nsclc"
GENE="TNFRSF12A"
```

**Step 1: Drug Target Risk Assessment**
```
# 1.1 MANDATORY: Read the disease-specific risk assessment template FIRST
Read: {SKILL_BASE_DIR}/reference/risk_assessment_template_{DISEASE}.md

# 1.2 Execute PubMed searches for each risk category (guided by template)
# 1.3 Populate template with evidence and assign risk levels
# 1.4 Output: {GENE}_risk_assessment_{disease}.md
```

**Step 2: Setup environment and run multi-omics analysis**
```bash
cp "$SKILL_BASE_DIR/pixi.toml" ./
cp "$SKILL_BASE_DIR/pixi.lock" ./
pixi install

# For CRC (Comprehensive TCGA + Tempus):
# Run from CRC bulk RNA skill base directory - do NOT copy the script
pixi run python "$SKILL_BASE_DIR/crc_comprehensive_analysis.py" --genes $GENE --output-dir ./${DISEASE}_analysis_results

# For NSCLC:
# Run from NSCLC bulk RNA skill base directory - do NOT copy the script
pixi run python "$SKILL_BASE_DIR/nsclc_comprehensive_analysis.py" --genes $GENE --output-dir ./${DISEASE}_analysis_results
```

**Step 3: ScholarEval scoring**
```
# Read {GENE}_comprehensive_report.md (primary source from Step 2)
# Claude calculates 8-dimension target score based on:
# - Expression results from comprehensive_report.md
# - 3-phase subgroup suitability analysis
# - Literature evidence from Step 1
```

**Step 4: Generate integrated report markdown + PDF**
```bash
# Claude generates {GENE}_integrated_target_report.md

# AUTOMATIC: Generate PDF report (ALWAYS run at end of workflow)
# Run script from skill base directory - do NOT copy to working directory
pixi run python "$SKILL_BASE_DIR/scripts/generate_target_report_pdf.py" --gene $GENE --disease $DISEASE --output-dir ./${DISEASE}_analysis_results
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

### Comprehensive Analysis Outputs (CRC: `crc_comprehensive_analysis.py`)
| File | Description |
|------|-------------|
| `{GENE}_comprehensive_analysis.png` | 8-panel figure: TCGA cohorts, toxicity, Tempus LOT, iDAS cohorts, RAS status, CMS, alignment summary, recommendation |
| `{GENE}_comprehensive_report.md` | **PRIMARY SOURCE for Steps 3/4** - Full report with TCGA + Tempus evidence, iDAS alignment, 3-phase subgroup suitability, recommendations |
| `{GENE}_idas_assessment.yaml` | Structured iDAS whitespace alignment assessment |
| `{GENE}_subgroup_suitability.csv` | 3-phase subgroup suitability scores (Phase 1: TCGA molecular, Phase 2: Tempus RAS, Phase 3: iDAS whitespace) |
| `{GENE}_tcga_statistics.csv` | TCGA cohort expression statistics |
| `{GENE}_pairwise_comparisons.csv` | Tumor vs Normal statistical comparisons |
| `figures/{GENE}_panel_*.png` | Individual high-resolution (300 DPI) figures for each panel |
| `figures/{GENE}_subgroup_suitability.png` | Subgroup suitability chart with scores and recommendations |

### Comprehensive Analysis Outputs (NSCLC: `nsclc_comprehensive_analysis.py`)
| File | Description |
|------|-------------|
| `{GENE}_comprehensive_analysis.png` | 8-panel figure: TCGA cohorts + mutations, toxicity, Tempus LOT, iDAS cohorts, biomarker status, alignment summary, recommendation |
| `{GENE}_comprehensive_report.md` | **PRIMARY SOURCE for Steps 3/4** - Full report with TCGA + Tempus evidence, iDAS alignment, 3-phase subgroup suitability, recommendations |
| `{GENE}_idas_assessment.yaml` | Structured iDAS whitespace alignment + subgroup analysis (histology, mutations, iDAS whitespaces) |
| `{GENE}_subgroup_suitability.csv` | 3-phase subgroup suitability scores (Phase 1: TCGA analysis, Phase 2: Tempus mutation, Phase 3: iDAS whitespace) |
| `{GENE}_tcga_statistics.csv` | TCGA cohort expression statistics |
| `{GENE}_pairwise_comparisons.csv` | Tumor vs Normal statistical comparisons |
| `{GENE}_tcga_mutation_statistics.csv` | TCGA mutation status expression (KRAS, EGFR, STK11, KEAP1 Mut vs WT) |
| `figures/{GENE}_panel_*.png` | Individual high-resolution (300 DPI) figures for each panel |
| `figures/{GENE}_subgroup_suitability.png` | Subgroup suitability heatmap with scores and recommendations |

### Target Evaluation Workflow Outputs
| File | Description |
|------|-------------|
| `{GENE}_risk_assessment_{disease}.md` | Step 1 output: Risk assessment with literature evidence |
| `{GENE}_integrated_target_report.md` | Final integrated report (includes 3-phase subgroup suitability for CRC and NSCLC) |
| `{GENE}_final_risk_report.pdf` | 13-page professional PDF (includes subgroup analysis) |
| `{GENE}_summary_slide.png` | Landscape (16:9) presentation slide with executive summary |
| `{GENE}_summary_slide.pdf` | Landscape (16:9) presentation slide with executive summary |
| `{GENE}_risk_assessment_figure.png` | 6-category risk assessment visualization |
| `{GENE}_scholar_eval_figure.png` | ScholarEval scoring visualization |

---

## Example Usage

**User:** "Evaluate TNFRSF12A as a target in CRC"

**Response:**
1. **Step 1: Drug Target Risk Assessment**
   - **FIRST:** Read `reference/risk_assessment_template_crc.md` using the Read tool
   - Execute PubMed searches for each risk category (Biological, Druggability, Translational, Clinical, Safety, Commercial)
   - Follow template guidance for CRC-specific searches (RAS mutation context, MSI/MSS status, chemorefractory setting)
   - Populate template with evidence, assess iDAS whitespace alignment
   - Output: `TNFRSF12A_risk_assessment_crc.md`
2. **Step 2: Multi-omics Analysis** - Run CRC bulk RNA analysis
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

**User:** "Evaluate CDCP1 as a target in NSCLC"

**Response:**
1. Same 4-step workflow for NSCLC
2. Key findings:
   - LUSC: 2.0x vs adjacent (GO) | LUAD: 1.4x vs adjacent (CONDITIONAL)
   - Tempus KRAS+: 1.2x vs WT (GO) | Tempus STK11+: 0.8x vs WT (NEUTRAL)
   - iDAS 2L Non-AGA: Strong (4/5) | iDAS KRAS: Strong (4/5)
   - **CAUTION:** TCGA STK11+ shows 0.5x vs WT - consider excluding STK11-mutant patients
   - Recommendation: **GO** with STK11 biomarker selection

---

## Key Design Principles

1. **Tumor vs Adjacent Normal is PRIMARY metric** - predicts on-target toxicity
2. **Template-guided risk assessment** - disease-specific templates (e.g., CRC with iDAS context) drive structured PubMed searches
3. **Integrated Step 1** - Risk framework and literature search combined for efficiency
4. **PDF reads from markdown** - no hard-coded values in PDF script
5. **Disease-agnostic orchestration** - add new diseases via config + risk template + DISEASE_CONFIG entry in PDF script
6. **Standardized report format** - enables reliable parsing
7. **Strategic alignment** - evaluations include iDAS whitespace and portfolio synergy assessment
8. **Automatic PDF generation** - PDF MUST be generated at end of every workflow (requires `--disease` parameter)
9. **Subgroup-stratified analysis** - Both CRC and NSCLC evaluations include 3-phase subgroup suitability scores (Phase 1: TCGA treatment-naive, Phase 2: Tempus mutation IO-experienced, Phase 3: iDAS whitespace) to identify optimal patient populations and exclusion criteria
